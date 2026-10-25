"""Contrôles de démarrage (T94) et commande `verifier`."""

import pytest

from agent_tag.config import demarrage

pytestmark = pytest.mark.db


def _init_env(base, usage):
    with base.owner() as conn:
        conn.execute("INSERT INTO environment (usage, libelle) VALUES (%s, 'test')", (usage,))


def test_demarrage_accepte_si_usage_identique(base_migree):
    _init_env(base_migree, "TEST")
    with base_migree.app() as conn:
        etat = demarrage.verifier(conn, "TEST")
    assert etat.usage == "TEST"
    assert etat.fuseau_horaire is None


def test_T94_demarrage_refuse_si_usage_different(base_migree):
    _init_env(base_migree, "EXPLOITATION")
    with base_migree.app() as conn:
        with pytest.raises(demarrage.DemarrageRefuse, match="différent"):
            demarrage.verifier(conn, "TEST")


def test_demarrage_refuse_sans_environnement(base_migree):
    with base_migree.app() as conn:
        with pytest.raises(demarrage.DemarrageRefuse, match="non initialisé"):
            demarrage.verifier(conn, "TEST")


def test_demarrage_refuse_si_schema_non_migre(base_vierge):
    with base_vierge.app() as conn:
        with pytest.raises(demarrage.DemarrageRefuse, match="migrations en attente"):
            demarrage.verifier(conn, "TEST")


def test_demarrage_refuse_si_migration_en_attente(base_migree, tmp_path):
    import shutil

    from agent_tag.persistence import migrations

    dossier = tmp_path / "migrations"
    shutil.copytree(migrations.DOSSIER_PAR_DEFAUT, dossier)
    (dossier / "9998_nouvelle.sql").write_text("SELECT 1;", encoding="utf-8")
    _init_env(base_migree, "TEST")
    with base_migree.app() as conn:
        with pytest.raises(demarrage.DemarrageRefuse, match="9998_nouvelle"):
            demarrage.verifier(conn, "TEST", dossier)
