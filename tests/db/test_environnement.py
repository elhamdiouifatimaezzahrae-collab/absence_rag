"""Table environment : ligne unique, usage immuable (T67), fuseau jamais deviné."""

import psycopg
import pytest

pytestmark = pytest.mark.db


def _inserer(conn, usage="TEST", libelle="Base de test", fuseau=None):
    return conn.execute(
        "INSERT INTO environment (usage, libelle, fuseau_horaire) VALUES (%s, %s, %s) "
        "RETURNING id_environnement",
        (usage, libelle, fuseau),
    ).fetchone()[0]


def test_creation_genere_un_identifiant(base_migree):
    with base_migree.owner() as conn:
        assert _inserer(conn) is not None


def test_une_seule_ligne(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn)
        with pytest.raises(psycopg.errors.UniqueViolation):
            _inserer(conn, libelle="Seconde")


def test_usage_invalide_refuse(base_migree):
    with base_migree.owner() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            _inserer(conn, usage="PROD")


def test_T67_usage_immuable(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn)
        conn.commit()
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("UPDATE environment SET usage = 'EXPLOITATION'")


def test_identifiant_immuable(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn)
        conn.commit()
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("UPDATE environment SET id_environnement = gen_random_uuid()")


def test_suppression_interdite(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn)
        conn.commit()
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("DELETE FROM environment")


def test_libelle_et_fuseau_modifiables(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn)
        conn.execute("UPDATE environment SET libelle = 'Renommée', fuseau_horaire = 'UTC'")
        assert conn.execute("SELECT libelle, fuseau_horaire FROM environment").fetchone() == (
            "Renommée",
            "UTC",
        )


def test_fuseau_facultatif_mais_valide_si_renseigne(base_migree):
    with base_migree.owner() as conn:
        _inserer(conn, fuseau=None)
        with pytest.raises(psycopg.errors.CheckViolation, match="fuseau horaire inconnu"):
            conn.execute("UPDATE environment SET fuseau_horaire = 'Mars/Olympus'")
