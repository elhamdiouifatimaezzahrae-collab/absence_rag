"""Import des données journalières — classeurs ARTIFICIELS (voir fabrique.journalier)."""

import threading
from datetime import datetime

import psycopg
import pytest
from fabrique import (J1, J2, Classeur, absence, affectation, compter, instantane_journalier,
                      journalier, journalier_vide, lots)

from agent_tag.imports import import_journalier
from agent_tag.imports import rapport as r

pytestmark = pytest.mark.db


def _couvertures(base, statut=None):
    with base.owner() as c:
        sql = ("SELECT date::text, id_chaine, type_donnee, etat, statut, id_lot "
               "FROM batch_coverage")
        if statut:
            sql += f" WHERE statut = '{statut}'"
        return sorted(c.execute(sql + " ORDER BY 1, 2, 3, 6").fetchall())


# --- Import valide --------------------------------------------------------------------

def test_import_valide_affectations_et_absences(importer_jour, base_referentiel):
    rap = importer_jour(journalier())
    assert rap.statut == r.APPLIQUE, rap.en_texte()
    assert compter(base_referentiel, "daily_assignment") == 4
    assert compter(base_referentiel, "absence") == 1
    assert _couvertures(base_referentiel) == [
        ("2026-03-02", "LA", "ABSENCES", "COMPLET", "COURANT", rap.id_lot),
        ("2026-03-02", "LA", "AFFECTATIONS", "COMPLET", "COURANT", rap.id_lot),
        ("2026-03-02", "LB", "ABSENCES", "COMPLET", "COURANT", rap.id_lot),
        ("2026-03-02", "LB", "AFFECTATIONS", "COMPLET", "COURANT", rap.id_lot),
    ]
    stats = {n: (s.lues, s.importees, s.rejetees) for n, s in rap.feuilles.items()}
    assert stats == {"Affectations": (4, 4, 0), "Absences": (1, 1, 0)}
    with base_referentiel.owner() as c:
        assert c.execute("SELECT version FROM data_version WHERE date = '2026-03-02'"
                         ).fetchone()[0] == 1
        perimetre, statut, attestant = c.execute(
            "SELECT b.perimetre, b.statut, cov.atteste_par FROM import_batch b JOIN batch_coverage "
            "cov ON cov.id_lot = b.id WHERE b.id = %s AND cov.type_donnee = 'ABSENCES' LIMIT 1",
            (rap.id_lot,)).fetchone()
    assert (perimetre, statut) == ("JOURNALIER", "APPLIQUE")
    assert attestant is not None


def test_absences_non_attestees_couverture_partielle(importer_jour, base_referentiel):
    rap = importer_jour(journalier(), attester=False)
    assert rap.statut == r.APPLIQUE
    assert "ABSENCES_NON_ATTESTEES" in rap.codes(r.AVERTISSEMENT)
    etats = {(ch, t): e for _, ch, t, e, _, _ in _couvertures(base_referentiel)}
    assert etats[("LA", "ABSENCES")] == "PARTIEL"
    assert etats[("LA", "AFFECTATIONS")] == "COMPLET"


def test_referentiel_requis(importer, base_import, tmp_path):
    with pytest.raises(import_journalier.ImportImpossible, match="aucun référentiel"):
        import_journalier.importer(base_import.app_url,
                                   journalier().ecrire(tmp_path / "j.xlsx"), "testeur",
                                   tmp_path / "a")


def test_feuilles_du_referentiel_ignorees(importer_jour, base_referentiel, tmp_path):
    """Un classeur complet (référentiel + journalier) : seules les feuilles journalières sont lues."""
    c = Classeur()
    c.vider("Affectations").vider("Absences")
    c.ajouter_ligne("Affectations", affectation(J1, "T01"))
    rap = importer_jour(c.ecrire(tmp_path / "complet.xlsx"))
    assert rap.statut == r.APPLIQUE
    assert {a.feuille for a in rap.anomalies if a.code == "FEUILLE_NON_IMPORTEE"} >= {
        "Ouvriers", "Competences", "Chaines", "Besoins_Postes"}


# --- Structure ------------------------------------------------------------------------

@pytest.mark.parametrize("feuille", ["Affectations", "Absences"])
def test_feuille_obligatoire_manquante(importer_jour, base_referentiel, feuille):
    rap = importer_jour(journalier().supprimer_feuille(feuille))
    assert rap.statut == r.REJETE
    assert any(a.code == "FEUILLE_MANQUANTE" and a.feuille == feuille for a in rap.bloquantes)
    assert journalier_vide(base_referentiel)


@pytest.mark.parametrize("feuille, colonne", [
    ("Affectations", "Date"), ("Affectations", "Statut_affectation"),
    ("Absences", "Durée_jours"), ("Absences", "ID_Ouvrier"),
])
def test_colonne_manquante(importer_jour, base_referentiel, feuille, colonne):
    rap = importer_jour(journalier().supprimer_colonne(feuille, colonne))
    assert rap.statut == r.REJETE
    assert any(a.code == "COLONNE_MANQUANTE" and a.colonne == colonne for a in rap.bloquantes)
    assert journalier_vide(base_referentiel)


# --- Dates et durées ------------------------------------------------------------------

@pytest.mark.parametrize("feuille, valeur, code", [
    ("Affectations", "2026-03-02", "DATE_INVALIDE"),          # texte : format non deviné
    ("Affectations", "02/03/2026", "DATE_INVALIDE"),
    ("Affectations", 46083, "DATE_INVALIDE"),                  # nombre brut
    ("Affectations", datetime(2026, 3, 2, 9, 30), "DATE_INVALIDE"),
    ("Affectations", None, "VALEUR_OBLIGATOIRE"),
    ("Absences", "demain", "DATE_INVALIDE"),
    ("Absences", None, "VALEUR_OBLIGATOIRE"),
])
def test_date_invalide(importer_jour, base_referentiel, feuille, valeur, code):
    rap = importer_jour(journalier().modifier(feuille, 0, "Date", valeur))
    assert rap.statut == r.REJETE
    assert any(a.code == code and a.colonne == "Date" for a in rap.bloquantes)
    assert journalier_vide(base_referentiel)


def test_date_par_formule_sans_valeur_calculee(importer_jour, base_referentiel):
    """Une formule enregistrée sans valeur calculée (ex. fichier produit par un script) n'est pas
    évaluée : la date est considérée absente."""
    rap = importer_jour(journalier().modifier("Affectations", 0, "Date", "=DATE(2026,3,2)"))
    assert rap.statut == r.REJETE
    assert any("formule" in a.message for a in rap.bloquantes)


@pytest.mark.parametrize("valeur, code", [
    (0, "VALEUR_INVALIDE"), (-2, "VALEUR_INVALIDE"), (1.5, "VALEUR_INVALIDE"),
    ("deux", "VALEUR_INVALIDE"), (None, "VALEUR_OBLIGATOIRE"),
])
def test_duree_invalide(importer_jour, base_referentiel, valeur, code):
    rap = importer_jour(journalier().modifier("Absences", 0, "Durée_jours", valeur))
    assert rap.statut == r.REJETE
    assert any(a.code == code and a.colonne == "Durée_jours" for a in rap.bloquantes)
    assert journalier_vide(base_referentiel)


def test_duree_superieure_a_un_jour_signalee_D19(importer_jour):
    rap = importer_jour(journalier(absences=[absence(J1, "T02", duree=3)]))
    assert rap.statut == r.APPLIQUE
    assert "DUREE_A_INTERPRETER" in rap.codes(r.DECISION)


# --- Identifiants, références, doublons -----------------------------------------------

@pytest.mark.parametrize("feuille, colonne, valeur", [
    ("Affectations", "ID_Ouvrier", "T99"),
    ("Absences", "ID_Ouvrier", "T99"),
    ("Affectations", "Chaîne", "LZ"),
    ("Absences", "Chaîne", "LZ"),
    ("Affectations", "Poste", "Brodeur"),
    ("Absences", "Poste_principal", "Brodeur"),
])
def test_identifiants_inconnus(importer_jour, base_referentiel, feuille, colonne, valeur):
    rap = importer_jour(journalier().modifier(feuille, 0, colonne, valeur))
    assert rap.statut == r.REJETE
    assert any(a.code == "REFERENCE_ORPHELINE" and a.colonne == colonne for a in rap.bloquantes)
    assert journalier_vide(base_referentiel)


@pytest.mark.parametrize("feuille, colonne, valeur, code", [
    ("Affectations", "Nom", "Autre Nom", "INCOHERENCE"),
    ("Affectations", "Produit", "ProduitB", "INCOHERENCE"),
    ("Absences", "Nom", "Autre Nom", "INCOHERENCE"),
    ("Affectations", "Statut_affectation", "Malade", "VALEUR_INVALIDE"),
    ("Absences", "Statut_absence", "Congé", "VALEUR_INVALIDE"),
    ("Affectations", "Horaire", "8h-16h", "VALEUR_INVALIDE"),
])
def test_valeurs_incoherentes(importer_jour, base_referentiel, feuille, colonne, valeur, code):
    rap = importer_jour(journalier().modifier(feuille, 0, colonne, valeur))
    assert rap.statut == r.REJETE
    assert code in rap.codes(r.BLOQUANTE)
    assert journalier_vide(base_referentiel)


def test_doublon_d_affectation(importer_jour, base_referentiel):
    rap = importer_jour(journalier().ajouter_ligne("Affectations", affectation(J1, "T01")))
    assert rap.statut == r.REJETE
    assert "IDENTIFIANT_DUPLIQUE" in rap.codes(r.BLOQUANTE)
    assert journalier_vide(base_referentiel)


@pytest.mark.parametrize("seconde", [absence(J1, "T02"), absence(J2, "T02"),
                                     absence(datetime(2026, 2, 28), "T02", duree=3)])
def test_absences_chevauchantes(importer_jour, base_referentiel, seconde):
    rap = importer_jour(journalier(absences=[absence(J1, "T02", duree=2), seconde]))
    assert rap.statut == r.REJETE
    assert "ABSENCES_CHEVAUCHANTES" in rap.codes(r.BLOQUANTE)
    assert journalier_vide(base_referentiel)


def test_absences_successives_acceptees(importer_jour):
    rap = importer_jour(journalier(absences=[absence(J1, "T02"), absence(J2, "T02")]))
    assert rap.statut == r.APPLIQUE


# --- Couverture et contradictions -----------------------------------------------------

def test_ouvrier_sans_affectation_couverture_partielle(importer_jour, base_referentiel):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"), affectation(J1, "T03")]
    rap = importer_jour(journalier(affectations=affs))
    assert rap.statut == r.APPLIQUE
    assert "OUVRIERS_SANS_AFFECTATION" in rap.codes(r.AVERTISSEMENT)
    etats = {(ch, t): e for _, ch, t, e, _, _ in _couvertures(base_referentiel)}
    assert etats[("LB", "AFFECTATIONS")] == "PARTIEL"
    assert etats[("LA", "AFFECTATIONS")] == "COMPLET"


def test_contradictions_signalees_et_import_applique(importer_jour):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"),
            affectation(J1, "T03", "Absent"), affectation(J1, "T04")]
    abs_ = [absence(J1, "T01"), absence(J1, "T02")]
    rap = importer_jour(journalier(affectations=affs, absences=abs_))
    assert rap.statut == r.APPLIQUE
    contradictions = [a.message for a in rap.anomalies if a.code == "CONTRADICTION"]
    assert len(contradictions) == 2
    assert any(m.startswith("T01") and "Présent" in m for m in contradictions)
    assert any(m.startswith("T03") and "Absent sans absence" in m for m in contradictions)


# --- Réimport, historique, atomicité --------------------------------------------------

def test_reimport_du_meme_fichier_sans_doublon(importer_jour, base_referentiel, tmp_path):
    chemin = journalier().ecrire(tmp_path / "jour.xlsx")
    premier = importer_jour(chemin)
    avant = instantane_journalier(base_referentiel)
    second = importer_jour(chemin)
    assert second.statut == r.DEJA_IMPORTE and second.id_lot == premier.id_lot
    assert instantane_journalier(base_referentiel) == avant


def test_nouveau_fichier_remplace_la_couverture_et_conserve_l_historique(
        importer_jour, base_referentiel):
    premier = importer_jour(journalier())
    affs = [affectation(J1, "T01"), affectation(J1, "T02"), affectation(J1, "T03"),
            affectation(J1, "T04")]
    second = importer_jour(journalier(affectations=affs, absences=[]))
    assert second.statut == r.APPLIQUE
    assert "COUVERTURE_REMPLACEE" in second.codes(r.INFORMATION)

    # Historique : toutes les lignes des deux lots sont conservées.
    assert compter(base_referentiel, "daily_assignment") == 8
    assert compter(base_referentiel, "absence") == 1
    courantes = {(ch, t): lot for _, ch, t, _, _, lot in _couvertures(base_referentiel, "COURANT")}
    assert set(courantes.values()) == {second.id_lot}
    with base_referentiel.owner() as c:
        remplacees = c.execute(
            "SELECT count(*) FROM batch_coverage WHERE statut = 'REMPLACE' AND id_lot = %s "
            "AND remplace_par_lot = %s AND fin_courant IS NOT NULL",
            (premier.id_lot, second.id_lot)).fetchone()[0]
        version = c.execute("SELECT version FROM data_version WHERE date = '2026-03-02'"
                            ).fetchone()[0]
    assert remplacees == 4
    assert version == 2


def test_import_invalide_ne_modifie_pas_les_donnees_validees(importer_jour, base_referentiel):
    assert importer_jour(journalier()).statut == r.APPLIQUE
    avant = instantane_journalier(base_referentiel)
    rap = importer_jour(journalier().modifier("Absences", 0, "Durée_jours", 0))
    assert rap.statut == r.REJETE
    assert instantane_journalier(base_referentiel) == avant
    assert [s for _, s, _ in lots(base_referentiel)][-2:] == ["APPLIQUE", "REJETE"]


def test_retour_arriere_si_l_ecriture_echoue(importer_jour, base_referentiel, monkeypatch):
    """Premier lot valide, puis échec PostgreSQL réel après écriture des lignes du second lot :
    ni lignes, ni couvertures, ni version ne changent ; le premier lot reste courant."""
    premier = importer_jour(journalier())
    avant = instantane_journalier(base_referentiel)

    def versions_defectueuses(conn, donnees):
        conn.execute("INSERT INTO data_version (date, version) VALUES ('2026-03-02', 0)")

    monkeypatch.setattr(import_journalier, "_incrementer_versions", versions_defectueuses)
    rap = importer_jour(journalier(absences=[]))
    assert rap.statut == r.REJETE
    assert "ERREUR_ECRITURE" in rap.codes(r.BLOQUANTE)
    assert instantane_journalier(base_referentiel) == avant
    assert {lot for *_, lot in _couvertures(base_referentiel, "COURANT")} == {premier.id_lot}


def test_deux_imports_concurrents_pour_la_meme_date(base_referentiel, tmp_path):
    fichiers = [journalier().ecrire(tmp_path / "a.xlsx"),
                journalier(absences=[]).ecrire(tmp_path / "b.xlsx")]
    depart = threading.Barrier(2)
    resultats = []

    def lancer(f):
        depart.wait()
        resultats.append(import_journalier.importer(base_referentiel.app_url, f, "testeur",
                                                    tmp_path / "arch", True))

    fils = [threading.Thread(target=lancer, args=(f,)) for f in fichiers]
    for t in fils:
        t.start()
    for t in fils:
        t.join(30)
    assert [x.statut for x in resultats] == [r.APPLIQUE, r.APPLIQUE]
    courantes = _couvertures(base_referentiel, "COURANT")
    assert len(courantes) == 4 and len({lot for *_, lot in courantes}) == 1
    assert compter(base_referentiel, "batch_coverage") == 8


# --- Contraintes de la base -----------------------------------------------------------

def test_role_applicatif_ne_modifie_pas_les_lignes_importees(importer_jour, base_referentiel):
    importer_jour(journalier())
    with base_referentiel.app() as c:
        for sql in ("UPDATE daily_assignment SET statut_presence = 'ABSENT'",
                    "DELETE FROM absence", "DELETE FROM batch_coverage",
                    "UPDATE batch_coverage SET etat = 'PARTIEL'"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
            c.rollback()


def test_couverture_seule_transition_courant_vers_remplace(importer_jour, base_referentiel):
    importer_jour(journalier())
    with base_referentiel.owner() as c:
        with pytest.raises(psycopg.errors.RestrictViolation):
            c.execute("UPDATE batch_coverage SET etat = 'PARTIEL'")
        c.rollback()
        with pytest.raises(psycopg.errors.RestrictViolation):
            c.execute("DELETE FROM batch_coverage")


def test_base_refuse_absences_chevauchantes_dans_un_lot(importer_jour, base_referentiel):
    rap = importer_jour(journalier())
    with base_referentiel.owner() as c:
        with pytest.raises(psycopg.errors.ExclusionViolation):
            c.execute("INSERT INTO absence (id_lot, id_ouvrier, date_debut, duree_jours, "
                      "id_chaine, code_poste, statut_source) VALUES (%s, 'T02', '2026-03-01', 3, "
                      "'LA', 'SURJETEUR_SURJETEUSE', 'Absent')", (rap.id_lot,))
