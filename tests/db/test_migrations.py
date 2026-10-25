"""Exécuteur de migrations versionnées."""

import shutil
import threading

import pytest

from agent_tag.persistence import migrations

pytestmark = pytest.mark.db


def test_toutes_les_migrations_appliquees_et_tracees(base_vierge):
    faites = migrations.migrer(base_vierge.owner_url)
    attendues = migrations.lister()
    assert [m.version for m in faites] == [m.version for m in attendues]
    with base_vierge.owner() as conn:
        assert migrations.appliquees(conn) == {m.version: m.empreinte for m in attendues}
        assert migrations.en_attente(conn) == []


def test_relance_idempotente(base_migree):
    assert migrations.migrer(base_migree.owner_url) == []


def test_migration_modifiee_apres_application_refusee(base_vierge, tmp_path):
    dossier = tmp_path / "migrations"
    shutil.copytree(migrations.DOSSIER_PAR_DEFAUT, dossier)
    migrations.migrer(base_vierge.owner_url, dossier)

    premier = sorted(dossier.glob("*.sql"))[0]
    premier.write_text(premier.read_text(encoding="utf-8") + "\n-- modif\n", encoding="utf-8")
    with pytest.raises(migrations.ErreurMigration, match="modifiée après application"):
        migrations.migrer(base_vierge.owner_url, dossier)


def test_migration_en_echec_annulee_entierement(base_vierge, tmp_path):
    dossier = tmp_path / "migrations"
    shutil.copytree(migrations.DOSSIER_PAR_DEFAUT, dossier)
    (dossier / "9999_defectueuse.sql").write_text(
        "CREATE TABLE partielle (x int);\nSELECT 1/0;\n", encoding="utf-8"
    )
    with pytest.raises(migrations.ErreurMigration, match="9999_defectueuse"):
        migrations.migrer(base_vierge.owner_url, dossier)

    with base_vierge.owner() as conn:
        assert 9999 not in migrations.appliquees(conn)
        assert conn.execute("SELECT to_regclass('partielle')").fetchone()[0] is None
        # Les migrations précédentes restent appliquées.
        assert 1 in migrations.appliquees(conn)


def test_nom_de_fichier_invalide_refuse(tmp_path):
    (tmp_path / "1_mauvais.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(migrations.ErreurMigration, match="Nom de migration invalide"):
        migrations.lister(tmp_path)


def test_migrer_attend_le_verrou_tenu_par_une_autre_session(base_vierge):
    """Deux sessions réelles : migrer() reste bloqué tant qu'une autre session tient le verrou."""
    resultat = {}

    def lancer():
        resultat["faites"] = migrations.migrer(base_vierge.owner_url)

    with base_vierge.owner(autocommit=True) as tiers:
        tiers.execute("SELECT pg_advisory_lock(900, 1)")
        fil = threading.Thread(target=lancer)
        fil.start()
        fil.join(timeout=1.0)
        bloque_pendant_le_verrou = fil.is_alive()
        tiers.execute("SELECT pg_advisory_unlock(900, 1)")
    fil.join(timeout=10)

    assert bloque_pendant_le_verrou, "migrer() n'a pas attendu le verrou"
    assert not fil.is_alive()
    assert len(resultat["faites"]) == len(migrations.lister())
