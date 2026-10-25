"""Moteur d'allocation sur données importées : scénario artificiel, classeur de référence,
lecture seule de la base."""

import datetime as dt
from pathlib import Path

import psycopg
import pytest
from fabrique import J1, absence, affectation, journalier

from agent_tag.domain import allocation as a
from agent_tag.persistence import instantane

pytestmark = pytest.mark.db

CLASSEUR = (Path(__file__).resolve().parents[2] / "donnees" / "reference"
            / "Base_Allocation_Production_150_Ouvriers_v2.xlsx")
TOUTES_LES_TABLES = ("environment", "schema_migration", "app_user", "import_batch",
                     "skill_level", "skill", "position", "production_line", "line_critical_skill",
                     "worker", "worker_skill", "position_requirement", "daily_assignment",
                     "absence", "batch_coverage", "data_version")


def _instantane(base, jour):
    with psycopg.connect(base.app_url, autocommit=True) as c:
        return instantane.lire(c, jour)


def _contenu_complet(base):
    with base.owner() as c:
        return {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                for t in TOUTES_LES_TABLES}


# --- Scénario ARTIFICIEL (référentiel de fabrique.Classeur) ---------------------------------
# LA : T01 piqueur, T02 surjeteur ; LB : T03 piqueur (sait surjeter, Intermédiaire), T04 coupeur.
# J1 : T02 absent. Exigence (LA, Surjeteur) : Surjeteuse ≥ Débutant.

def test_scenario_artificiel_candidat_bloque_par_P1_puis_admis_avec_m_bloc_0(
        importer_jour, base_referentiel):
    importer_jour(journalier())
    inst = _instantane(base_referentiel, J1.date())
    res = a.allouer(inst, a.PROFILS_PROVISOIRES["A"], "LA")
    [b] = res.besoins
    assert (b.id_ouvrier_absent, b.poste, b.statut) == ("T02", "SURJETEUR_SURJETEUSE",
                                                        a.AUCUN_CANDIDAT)
    ev = {e.id_ouvrier: e for e in b.evaluations}
    assert ev["T01"].premier_echec == "R7"      # même chaîne cible
    assert ev["T03"].premier_echec == "P1"      # seul piqueur de LB
    assert (res.couverture_sequentielle, res.couverture_maximale) == (0, 0)

    cfg = a.Configuration("TEST m_bloc 0 (non validé)", 0, 1, 2, a.RANGS_PRIORITE_PROVISOIRES)
    res0 = a.allouer(inst, cfg, "LA")
    p = res0.besoins[0].proposition
    assert (p.id_ouvrier, p.risque, p.causes_risque) == ("T03", a.ELEVE, ["P2", "CRITIQUE"])
    assert res0.besoins[0].qualite == "AVEC_ALERTE"


def test_candidat_absent_ou_inconnu_jamais_propose(importer_jour, base_referentiel):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"),
            affectation(J1, "T03", "Absent"), affectation(J1, "T04")]
    importer_jour(journalier(affectations=affs,
                             absences=[absence(J1, "T02"), absence(J1, "T03")]))
    inst = _instantane(base_referentiel, J1.date())
    cfg = a.Configuration("TEST m_bloc 0 (non validé)", 0, 0, 5, a.RANGS_PRIORITE_PROVISOIRES)
    b = next(x for x in a.allouer(inst, cfg, "LA").besoins if x.id_ouvrier_absent == "T02")
    ev = {e.id_ouvrier: e for e in b.evaluations}
    assert ev["T03"].premier_echec == "R6" and b.proposition is None


def test_date_sans_donnees_aucun_besoin(importer_jour, base_referentiel):
    importer_jour(journalier())
    res = a.allouer(_instantane(base_referentiel, dt.date(2026, 3, 9)),
                    a.PROFILS_PROVISOIRES["A"], "LA")
    assert res.besoins == []
    assert {e.etat for e in res.ecarts} == {"INCONNU"}


def test_lecture_dans_une_transaction_en_lecture_seule(importer_jour, base_referentiel,
                                                        monkeypatch):
    """Toute tentative d'écriture pendant la lecture de l'instantané est refusée par la base."""
    importer_jour(journalier())
    from agent_tag.persistence import disponibilite

    original = disponibilite.lire

    def lire_puis_ecrire(conn, *args, **kw):
        conn.execute("INSERT INTO data_version (date, version) VALUES ('2030-01-01', 1)")
        return original(conn, *args, **kw)

    monkeypatch.setattr(disponibilite, "lire", lire_puis_ecrire)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        _instantane(base_referentiel, J1.date())


# --- Classeur de RÉFÉRENCE (scénario du 12/10/2026, profils PROVISOIRES) --------------------

@pytest.fixture
def base_reference(importer, base_import, tmp_path):
    if not CLASSEUR.is_file():
        pytest.skip("classeur de référence absent")
    from agent_tag.imports import import_journalier
    assert importer(CLASSEUR).statut == "APPLIQUE"
    rap = import_journalier.importer(base_import.app_url, CLASSEUR, "testeur",
                                     tmp_path / "archives", attester_absences=True)
    assert rap.statut == "APPLIQUE"
    return base_import


def test_scenario_reference_L1(base_reference):
    inst = _instantane(base_reference, dt.date(2026, 10, 12))
    avant = _contenu_complet(base_reference)
    resultats = {p: a.allouer(inst, a.PROFILS_PROVISOIRES[p], "L1") for p in "AB"}
    assert _contenu_complet(base_reference) == avant      # simple calcul : aucune écriture

    for profil, res in resultats.items():
        assert len(res.besoins) == 10
        coupeur = next(b for b in res.besoins if b.id_ouvrier_absent == "O004")
        assert coupeur.statut == a.BLOQUE and "EXIGENCE_ABSENTE" in coupeur.cause
        proposes = [b.proposition for b in res.besoins if b.proposition]
        assert len({p.id_ouvrier for p in proposes}) == len(proposes)        # unicité
        for b in res.besoins:
            if b.proposition:
                p = b.proposition
                det = inst.competences[(p.id_ouvrier, b.competence)]
                assert p.chaine_donneuse != "L1"
                assert inst.jour[p.id_ouvrier].etat == "DISPONIBLE"
                assert det.rang_niveau >= b.rang_min
                assert p.risque in (a.FAIBLE, a.ELEVE)
        assert res.couverture_sequentielle <= res.couverture_maximale
        assert not res.utilisable_en_production

    a_ = resultats["A"]
    assert (a_.couverture_sequentielle, a_.couverture_maximale, a_.besoins_consideres) == (8, 8, 9)
    repasseur = next(b for b in a_.besoins if b.id_ouvrier_absent == "O005")
    assert repasseur.statut == a.AUCUN_CANDIDAT and "P3" in repasseur.cause
    b_ = resultats["B"]
    assert (b_.couverture_sequentielle, b_.couverture_maximale) == (9, 9)
    # Ordre de traitement : besoins critiques (Piqueuse, Surjeteuse, Contrôle qualité) d'abord.
    ordre = [b.id_ouvrier_absent for b in sorted(a_.besoins, key=lambda b: b.rang_traitement or 99)]
    assert ordre[:5] == ["O002", "O010", "O001", "O009", "O007"]


def test_commande_allouer_en_lecture_seule(base_reference, monkeypatch, capsys):
    from agent_tag import cli
    monkeypatch.setenv("AGENT_TAG_DATABASE_URL", base_reference.app_url)
    monkeypatch.setenv("AGENT_TAG_USAGE", "TEST")   # base jetable initialisée en TEST
    avant = _contenu_complet(base_reference)
    assert cli.main(["allouer", "--date", "2026-10-12", "--chaine", "L1", "--profil", "A"]) == 0
    sortie = capsys.readouterr().out
    assert "PARAMÈTRES PROVISOIRES DE TEST — NON VALIDÉS" in sortie
    assert "séquentielle 8 / maximale 8" in sortie
    assert _contenu_complet(base_reference) == avant


def test_commande_allouer_refusee_hors_TEST(monkeypatch):
    from agent_tag import cli
    from agent_tag.config import settings
    conf = settings.Settings("EXPLOITATION", "postgresql://x@localhost/x", None)
    with pytest.raises(settings.ConfigurationInvalide, match="usage TEST"):
        cli.cmd_allouer(conf, None)
