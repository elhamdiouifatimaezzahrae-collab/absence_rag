"""Import du classeur de RÉFÉRENCE dans une base jetable (lecture seule du fichier)."""

import hashlib
from pathlib import Path

import pytest
from fabrique import compter

from agent_tag.imports import rapport as r

pytestmark = pytest.mark.db

CLASSEUR = (Path(__file__).resolve().parents[2] / "donnees" / "reference"
            / "Base_Allocation_Production_150_Ouvriers_v2.xlsx")


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def classeur_reference():
    if not CLASSEUR.is_file():
        pytest.skip(f"classeur de référence absent : {CLASSEUR}")
    return CLASSEUR


def test_import_du_classeur_de_reference(importer, base_import, classeur_reference):
    avant = _sha(classeur_reference)
    rap = importer(classeur_reference)
    assert _sha(classeur_reference) == avant, "le classeur de référence a été modifié"

    assert rap.statut == r.APPLIQUE, rap.en_texte()
    assert {t: compter(base_import, t) for t in
            ("worker", "worker_skill", "production_line", "position_requirement",
             "skill", "position", "line_critical_skill")} == {
        "worker": 150, "worker_skill": 487, "production_line": 5, "position_requirement": 31,
        "skill": 8, "position": 8, "line_critical_skill": 15}

    # Constats de l'audit (Phase 1) retrouvés comme décisions, non corrigés.
    absentes = sorted(a.message.split(" :")[0] for a in rap.anomalies
                      if a.code == "EXIGENCE_ABSENTE")
    assert absentes == sorted([
        "(L1, Coupeur/Coupeuse)", "(L2, Coupeur/Coupeuse)", "(L3, Coupeur/Coupeuse)",
        "(L4, Coupeur/Coupeuse)", "(L5, Coupeur/Coupeuse)",
        "(L2, Repasseur/Repasseuse)", "(L4, Repasseur/Repasseuse)",
        "(L3, Agent d'emballage)", "(L5, Agent d'emballage)"])
    assert rap.codes(r.DECISION).count("CORRESPONDANCE_DEDUITE") == 1
    assert rap.codes(r.INFORMATION).count("HOMONYMES") == 3

    with base_import.owner() as c:
        # Homonymes conservés comme ouvriers distincts.
        assert c.execute("SELECT count(*) FROM worker WHERE nom = 'Nabil Benali'").fetchone()[0] == 2
        # Exemple du scénario : O001 piqueur, aussi Surjeteuse en secondaire.
        assert c.execute(
            "SELECT type_competence, code_niveau FROM worker_skill "
            "WHERE id_ouvrier = 'O001' AND code_competence = 'SURJETEUSE'").fetchone() == (
            "SECONDAIRE", "DEBUTANT")
        # Ouvriers.Statut conservé tel quel mais non interprété.
        assert c.execute("SELECT DISTINCT statut_source FROM worker").fetchall() == [("Disponible",)]


def test_import_journalier_du_classeur_de_reference(importer, base_import, classeur_reference,
                                                     tmp_path):
    """Scénario du 12/10/2026 : 150 affectations, 16 absences, 10 absents sur L1."""
    import psycopg

    from agent_tag.imports import import_journalier
    from agent_tag.persistence import disponibilite

    avant = _sha(classeur_reference)
    assert importer(classeur_reference).statut == r.APPLIQUE
    rap = import_journalier.importer(base_import.app_url, classeur_reference, "testeur",
                                     tmp_path / "archives", attester_absences=True)
    assert _sha(classeur_reference) == avant
    assert rap.statut == r.APPLIQUE, rap.en_texte()
    assert rap.bloquantes == []
    assert "CONTRADICTION" not in rap.codes()
    assert compter(base_import, "daily_assignment") == 150
    assert compter(base_import, "absence") == 16
    assert {(c["type_donnee"], c["etat"]) for c in rap.couvertures} == {
        ("AFFECTATIONS", "COMPLET"), ("ABSENCES", "COMPLET")}
    assert len(rap.couvertures) == 10   # 5 chaînes × 2 types, une seule date

    import datetime as dt
    with psycopg.connect(base_import.app_url, autocommit=True) as c:
        res = disponibilite.consulter(c, dt.date(2026, 10, 12))
    par_etat = {}
    for x in res:
        par_etat.setdefault(x.etat, []).append(x)
    assert {e: len(v) for e, v in par_etat.items()} == {"DISPONIBLE": 134, "ABSENT": 16}
    absents_l1 = sorted(x.id_ouvrier for x in par_etat["ABSENT"] if x.id_chaine == "L1")
    assert absents_l1 == [f"O{i:03d}" for i in range(1, 11)]
    assert all(x.besoin_creable for x in par_etat["ABSENT"])
