"""Import du référentiel depuis le classeur : orchestration et écriture transactionnelle.

Déroulement :
1. empreinte SHA-256 du fichier ; auteur existant et actif ;
2. même fichier déjà appliqué → DEJA_IMPORTE (rien n'est écrit) ;
   autre référentiel déjà appliqué → rejet (D15 : import unique en V1) ;
3. lecture et contrôle complets, sans écriture ;
4. archivage du fichier source sous son empreinte (T7) ;
5. anomalie bloquante → lot REJETE (avec rapport), aucune donnée de référentiel écrite ;
   sinon une transaction unique : lot APPLIQUE + toutes les tables du référentiel.
   Toute erreur pendant l'écriture annule la transaction entière ; le rejet est alors tracé.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import psycopg

from agent_tag.imports import classeur, referentiel
from agent_tag.imports import rapport as r

_VERROU_IMPORT_REFERENTIEL = (100, 1)  # (espace de noms, clé) : sérialise les imports du référentiel


class ImportImpossible(Exception):
    """L'import ne peut pas commencer (fichier absent, auteur inconnu…). Rien n'est tracé en base."""


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 16), b""):
            h.update(bloc)
    return h.hexdigest()


def _auteur(conn, identifiant: str) -> int:
    ligne = conn.execute("SELECT id, actif FROM app_user WHERE identifiant = %s",
                         (identifiant,)).fetchone()
    if ligne is None:
        raise ImportImpossible(f"utilisateur inconnu : {identifiant}")
    if not ligne[1]:
        raise ImportImpossible(f"utilisateur inactif : {identifiant}")
    return ligne[0]


def _referentiel_applique(conn) -> tuple[int, str] | None:
    return conn.execute(
        "SELECT id, empreinte_fichier FROM import_batch "
        "WHERE perimetre = 'REFERENTIEL' AND statut = 'APPLIQUE'"
    ).fetchone()


def _niveaux(conn) -> dict[str, str]:
    return dict(conn.execute("SELECT libelle, code_niveau FROM skill_level ORDER BY rang"))


def _archiver(chemin: Path, hachage: str, dossier: Path) -> str:
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"{hachage}{chemin.suffix.lower()}"
    if not cible.exists():
        shutil.copy2(chemin, cible)
    return str(cible)


def _tracer_rejet(url: str, rap: r.Rapport, auteur: int, archive: str | None,
                  perimetre: str = "REFERENTIEL") -> None:
    rap.statut = r.REJETE
    rap.finaliser_compteurs(applique=False, feuilles_importees=())
    with psycopg.connect(url) as conn:
        rap.id_lot = conn.execute(
            "INSERT INTO import_batch (type, perimetre, fichier_source, empreinte_fichier, "
            "reference_archive, auteur, statut, date_rejet, rapport) "
            "VALUES ('IMPORT', %s, %s, %s, %s, %s, 'REJETE', now(), %s) RETURNING id",
            (perimetre, rap.fichier, rap.empreinte, archive, auteur, json.dumps(rap.en_dict())),
        ).fetchone()[0]
        conn.commit()


def importer(url: str, chemin: Path, auteur_identifiant: str, dossier_archives: Path) -> r.Rapport:
    """Importe le référentiel. Retourne le rapport (statut APPLIQUE, REJETE ou DEJA_IMPORTE)."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ImportImpossible(f"fichier introuvable : {chemin}")
    rap = r.Rapport(fichier=chemin.name, empreinte=empreinte(chemin))

    with psycopg.connect(url) as conn:
        auteur = _auteur(conn, auteur_identifiant)
        existant = _referentiel_applique(conn)
        niveaux = _niveaux(conn)

    if existant and existant[1] == rap.empreinte:
        rap.statut, rap.id_lot = r.DEJA_IMPORTE, existant[0]
        rap.ajouter(r.INFORMATION, "DEJA_IMPORTE",
                    f"ce fichier a déjà été importé (lot {existant[0]}) ; aucune donnée écrite")
        return rap

    archive = _archiver(chemin, rap.empreinte, dossier_archives)

    if existant:
        rap.ajouter(r.BLOQUANTE, "REFERENTIEL_DEJA_PRESENT",
                    f"un référentiel est déjà appliqué (lot {existant[0]}) ; "
                    "le réimport du référentiel est hors V1 (D15)")
        _tracer_rejet(url, rap, auteur, archive)
        return rap

    try:
        feuilles = classeur.lire(chemin, rap)
    except classeur.ClasseurIllisible as exc:
        rap.ajouter(r.BLOQUANTE, "FICHIER_ILLISIBLE", str(exc))
        _tracer_rejet(url, rap, auteur, archive)
        return rap

    ref = referentiel.controler(feuilles, niveaux, rap)
    if rap.bloquantes:
        _tracer_rejet(url, rap, auteur, archive)
        return rap

    rap.statut = r.APPLIQUE
    rap.finaliser_compteurs(applique=True, feuilles_importees=classeur.FEUILLES_REFERENTIEL)
    try:
        with psycopg.connect(url) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", _VERROU_IMPORT_REFERENTIEL)
            concurrent = _referentiel_applique(conn)
            if concurrent:
                raise _Conflit(concurrent[0])
            id_lot = conn.execute(
                "INSERT INTO import_batch (type, perimetre, fichier_source, empreinte_fichier, "
                "reference_archive, auteur, statut, date_application, rapport) "
                "VALUES ('IMPORT', 'REFERENTIEL', %s, %s, %s, %s, 'APPLIQUE', now(), %s) "
                "RETURNING id",
                (rap.fichier, rap.empreinte, archive, auteur, json.dumps(rap.en_dict())),
            ).fetchone()[0]
            _ecrire(conn, ref, id_lot)
            conn.commit()  # les contrôles différés (une principale par ouvrier…) s'exécutent ici
            rap.id_lot = id_lot
    except _Conflit as exc:
        rap.ajouter(r.BLOQUANTE, "REFERENTIEL_DEJA_PRESENT",
                    f"un référentiel a été appliqué pendant l'import (lot {exc.id_lot}) (D15)")
        rap.id_lot = None
        _tracer_rejet(url, rap, auteur, archive)
    except psycopg.Error as exc:
        rap.ajouter(r.BLOQUANTE, "ERREUR_ECRITURE",
                    f"écriture annulée en totalité : {exc.__class__.__name__}: {exc}")
        rap.id_lot = None
        _tracer_rejet(url, rap, auteur, archive)
    return rap


class _Conflit(Exception):
    def __init__(self, id_lot):
        self.id_lot = id_lot


def _ecrire(conn, ref: referentiel.Referentiel, id_lot: int) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO skill (code_competence, libelle, id_lot_import) VALUES (%s, %s, %s)",
            [(c, lib, id_lot) for c, lib in sorted(ref.competences.items())])
        cur.executemany(
            "INSERT INTO position (code_poste, libelle, code_competence_associee, "
            "source_correspondance, correspondance_validee, id_lot_import) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [(p.code, p.libelle, p.code_competence, p.source, p.validee, id_lot)
             for p in sorted(ref.postes.values(), key=lambda p: p.code)])
        cur.executemany(
            "INSERT INTO production_line (id_chaine, produit, effectif_necessaire, "
            "effectif_planifie, libelle_priorite, capacite_journaliere, id_lot_import) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(c.id_chaine, c.produit, c.effectif_necessaire, c.effectif_planifie,
              c.libelle_priorite, c.capacite_journaliere, id_lot)
             for c in ref.chaines.values()])
        cur.executemany(
            "INSERT INTO line_critical_skill (id_chaine, code_competence, id_lot_import) "
            "VALUES (%s, %s, %s)", [(ch, c, id_lot) for ch, c in ref.critiques])
        cur.executemany(
            "INSERT INTO worker (id_ouvrier, nom, id_chaine_origine, code_poste_principal, "
            "heure_debut, heure_fin, statut_source, id_lot_import) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(o.id_ouvrier, o.nom, o.id_chaine, ref.postes[o.poste_libelle].code,
              o.heure_debut, o.heure_fin, o.statut_source, id_lot)
             for o in ref.ouvriers.values()])
        cur.executemany(
            "INSERT INTO worker_skill (id_ouvrier, code_competence, type_competence, "
            "annees_experience, code_niveau, certification, id_lot_import) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(d.id_ouvrier, d.code_competence, d.type_competence, d.annees, d.code_niveau,
              d.certification, id_lot) for d in ref.detenues])
        _ecrire_exigences(cur, ref, id_lot)


def _ecrire_exigences(cur, ref: referentiel.Referentiel, id_lot: int) -> None:
    cur.executemany(
        "INSERT INTO position_requirement (id_chaine, code_poste, version, "
        "code_competence_requise, code_niveau_min, nombre_requis, origine, statut, "
        "id_lot_import) VALUES (%s, %s, 1, %s, %s, %s, 'EXCEL', 'ACTIVE', %s)",
        [(e.id_chaine, ref.postes[e.poste_libelle].code, e.code_competence, e.code_niveau_min,
          e.nombre_requis, id_lot) for e in ref.exigences])
