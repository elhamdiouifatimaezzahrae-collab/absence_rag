"""Import des données journalières (feuilles Affectations et Absences).

Déroulement :
1. le référentiel doit être appliqué ; empreinte du fichier ; auteur existant et actif ;
2. même fichier déjà appliqué en JOURNALIER → DEJA_IMPORTE (rien n'est écrit) ;
3. lecture et contrôle complets, sans écriture ; archivage du fichier source ;
4. anomalie bloquante → lot REJETE tracé, aucune donnée écrite ;
5. sinon une transaction unique, sous verrou de chaque date concernée (S_D) :
   - lot APPLIQUE, lignes d'affectation et d'absence ;
   - pour chaque (date, chaîne, type) couvert : l'ancienne couverture COURANTE passe à REMPLACE
     (fin de validité, lot remplaçant) et la nouvelle devient COURANTE — rien n'est supprimé ;
   - version des données de chaque date incrémentée.
   Toute erreur annule la transaction entière ; le rejet est alors tracé.

Choix provisoires TEST (registre) :
- D10 : pas de validation préalable des lots (application directe) ;
- D18 : la complétude des absences est attestée par l'auteur de l'import (--attester-absences),
  pour les (date, chaîne) couverts par les affectations du même fichier.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from agent_tag.imports import classeur, journalier
from agent_tag.services import allocation as allocation_services
from agent_tag.imports import rapport as r
from agent_tag.imports.import_referentiel import (
    ImportImpossible,
    _archiver,
    _auteur,
    _tracer_rejet,
    empreinte,
)

NS_VERROU_DATE = 10   # espace de noms des verrous S_D (clé : numéro ordinal de la date)


def _contexte(conn) -> journalier.ContexteReferentiel:
    ouvriers = {i: (n, ch, p) for i, n, ch, p in conn.execute(
        "SELECT id_ouvrier, nom, id_chaine_origine, code_poste_principal FROM worker")}
    chaines = dict(conn.execute("SELECT id_chaine, produit FROM production_line"))
    postes = dict(conn.execute("SELECT libelle, code_poste FROM position"))
    return journalier.ContexteReferentiel(ouvriers, chaines, postes)


def _lot_applique(conn, hachage: str) -> int | None:
    ligne = conn.execute(
        "SELECT id FROM import_batch WHERE perimetre = 'JOURNALIER' AND statut = 'APPLIQUE' "
        "AND empreinte_fichier = %s", (hachage,)).fetchone()
    return ligne[0] if ligne else None


def importer(url: str, chemin: Path, auteur_identifiant: str, dossier_archives: Path,
             attester_absences: bool = False) -> r.Rapport:
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ImportImpossible(f"fichier introuvable : {chemin}")
    rap = r.Rapport(fichier=chemin.name, empreinte=empreinte(chemin))

    with psycopg.connect(url) as conn:
        auteur = _auteur(conn, auteur_identifiant)
        if conn.execute("SELECT count(*) FROM import_batch WHERE perimetre = 'REFERENTIEL' "
                        "AND statut = 'APPLIQUE'").fetchone()[0] == 0:
            raise ImportImpossible("aucun référentiel appliqué : importer d'abord le référentiel")
        existant = _lot_applique(conn, rap.empreinte)
        ctx = _contexte(conn)

    if existant:
        rap.statut, rap.id_lot = r.DEJA_IMPORTE, existant
        rap.ajouter(r.INFORMATION, "DEJA_IMPORTE",
                    f"ce fichier a déjà été importé en données journalières (lot {existant}) ; "
                    "aucune donnée écrite")
        return rap

    archive = _archiver(chemin, rap.empreinte, dossier_archives)
    try:
        feuilles = classeur.lire(chemin, rap, obligatoires=classeur.FEUILLES_JOURNALIERES,
                                 controlees=())
    except classeur.ClasseurIllisible as exc:
        rap.ajouter(r.BLOQUANTE, "FICHIER_ILLISIBLE", str(exc))
        _tracer_rejet(url, rap, auteur, archive, "JOURNALIER")
        return rap

    donnees = journalier.controler(feuilles, ctx, rap, attester_absences)
    if rap.bloquantes:
        _tracer_rejet(url, rap, auteur, archive, "JOURNALIER")
        return rap

    try:
        with psycopg.connect(url) as conn:
            for jour in donnees.dates:
                conn.execute("SELECT pg_advisory_xact_lock(%s, %s)",
                             (NS_VERROU_DATE, jour.toordinal()))
            concurrent = _lot_applique(conn, rap.empreinte)
            if concurrent:
                conn.rollback()
                rap.statut, rap.id_lot = r.DEJA_IMPORTE, concurrent
                rap.ajouter(r.INFORMATION, "DEJA_IMPORTE",
                            f"fichier appliqué par un import concurrent (lot {concurrent})")
                return rap

            remplacees = _couvertures_courantes(conn, donnees)
            rap.couvertures = [
                {"date": c.date.isoformat(), "id_chaine": c.id_chaine,
                 "type_donnee": c.type_donnee, "etat": c.etat,
                 "remplace_lot": remplacees.get((c.date, c.id_chaine, c.type_donnee))}
                for c in donnees.couvertures]
            n_remplacees = sum(1 for c in rap.couvertures if c["remplace_lot"])
            if n_remplacees:
                rap.ajouter(r.INFORMATION, "COUVERTURE_REMPLACEE",
                            f"{n_remplacees} couverture(s) courante(s) remplacée(s) ; anciens lots "
                            "et lignes conservés")
            rap.statut = r.APPLIQUE
            rap.finaliser_compteurs(applique=True, feuilles_importees=classeur.FEUILLES_JOURNALIERES)

            id_lot = conn.execute(
                "INSERT INTO import_batch (type, perimetre, fichier_source, empreinte_fichier, "
                "reference_archive, auteur, statut, date_application, rapport) "
                "VALUES ('IMPORT', 'JOURNALIER', %s, %s, %s, %s, 'APPLIQUE', now(), %s) "
                "RETURNING id",
                (rap.fichier, rap.empreinte, archive, auteur, json.dumps(rap.en_dict())),
            ).fetchone()[0]
            _ecrire_lignes(conn, donnees, id_lot)
            _ecrire_couvertures(conn, donnees, id_lot, auteur if attester_absences else None)
            _incrementer_versions(conn, donnees)
            impact = allocation_services.impact_donnees(conn, donnees.dates, id_lot)
            conn.commit()
            rap.id_lot = id_lot
            if impact["runs"]:
                rap.ajouter(r.INFORMATION, "CALCULS_A_RECALCULER",
                            f"calcul(s) {impact['runs']} : propositions annulées (données "
                            "modifiées), recalcul nécessaire")
            if impact["a_revoir"]:
                rap.ajouter(r.AVERTISSEMENT, "REMPLACEMENTS_A_REVOIR",
                            f"remplacement(s) confirmé(s) {impact['a_revoir']} à revoir : "
                            "non annulés, décision humaine requise")
    except psycopg.Error as exc:
        rap.couvertures = []
        rap.ajouter(r.BLOQUANTE, "ERREUR_ECRITURE",
                    f"écriture annulée en totalité : {exc.__class__.__name__}: {exc}")
        rap.id_lot = None
        _tracer_rejet(url, rap, auteur, archive, "JOURNALIER")
    return rap


def _couvertures_courantes(conn, donnees) -> dict:
    courantes = {}
    for c in donnees.couvertures:
        ligne = conn.execute(
            "SELECT id_lot FROM batch_coverage WHERE date = %s AND id_chaine = %s "
            "AND type_donnee = %s AND source = 'IMPORT' AND statut = 'COURANT'",
            (c.date, c.id_chaine, c.type_donnee)).fetchone()
        if ligne:
            courantes[(c.date, c.id_chaine, c.type_donnee)] = ligne[0]
    return courantes


def _ecrire_lignes(conn, donnees, id_lot: int) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO daily_assignment (id_lot, date, id_ouvrier, id_chaine, code_poste, "
            "heure_debut, heure_fin, statut_presence, statut_source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(id_lot, a.date, a.id_ouvrier, a.id_chaine, a.code_poste, a.heure_debut,
              a.heure_fin, a.statut_presence, a.statut_source) for a in donnees.affectations])
        cur.executemany(
            "INSERT INTO absence (id_lot, id_ouvrier, date_debut, duree_jours, id_chaine, "
            "code_poste, statut_source, motif) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(id_lot, a.id_ouvrier, a.date_debut, a.duree, a.id_chaine, a.code_poste,
              a.statut_source, a.motif) for a in donnees.absences])


def _ecrire_couvertures(conn, donnees, id_lot: int, attestant: int | None) -> None:
    with conn.cursor() as cur:
        for c in donnees.couvertures:
            cur.execute(
                "UPDATE batch_coverage SET statut = 'REMPLACE', fin_courant = now(), "
                "remplace_par_lot = %s WHERE date = %s AND id_chaine = %s AND type_donnee = %s "
                "AND source = 'IMPORT' AND statut = 'COURANT'",
                (id_lot, c.date, c.id_chaine, c.type_donnee))
            absences = c.type_donnee == "ABSENCES"
            cur.execute(
                "INSERT INTO batch_coverage (id_lot, date, id_chaine, type_donnee, etat, "
                "mode_completude, atteste_par, source, statut, debut_courant) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'IMPORT', 'COURANT', now())",
                (id_lot, c.date, c.id_chaine, c.type_donnee, c.etat,
                 "DECLAREE" if absences else "CALCULEE",
                 attestant if absences and c.etat == "COMPLET" else None))


def _incrementer_versions(conn, donnees) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO data_version (date, version) VALUES (%s, 1) "
            "ON CONFLICT (date) DO UPDATE SET version = data_version.version + 1, "
            "mise_a_jour = now()",
            [(jour,) for jour in donnees.dates])
