"""Connexion et séparation des rôles."""

import psycopg
import pytest

pytestmark = pytest.mark.db


def test_connexion_role_applicatif_et_version(base_migree):
    with base_migree.app() as conn:
        version = conn.execute("SHOW server_version_num").fetchone()[0]
        role = conn.execute("SELECT current_user").fetchone()[0]
    assert int(version) >= 160000, "PostgreSQL 16 ou plus attendu"
    assert role == "agent_tag_app"


def test_role_applicatif_ne_peut_pas_modifier_le_schema(base_migree):
    with base_migree.app() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE intrusion (x int)")


def test_role_applicatif_ne_peut_pas_ecrire_l_environnement(base_migree):
    with base_migree.app() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO environment (usage, libelle) VALUES ('TEST', 'x')")
