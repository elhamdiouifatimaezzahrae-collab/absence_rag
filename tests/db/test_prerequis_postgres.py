"""Prérequis techniques X1–X6 (Phase 5, section 3).

Ces tests vérifient que le serveur PostgreSQL fournit réellement les mécanismes sur
lesquels reposeront les garanties du modèle. Ils utilisent des tables de sonde
volontairement minimales, sans rapport avec le schéma métier (créé à l'incrément 1+).
"""

import threading

import psycopg
import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def owner(base_vierge):
    with base_vierge.owner() as conn:
        yield conn


def test_X1_fk_composite_match_full(owner):
    owner.execute("CREATE TABLE cible (a int, b int, UNIQUE (a, b))")
    owner.execute(
        "CREATE TABLE source (a int, b int, FOREIGN KEY (a, b) REFERENCES cible (a, b) MATCH FULL)"
    )
    owner.execute("INSERT INTO cible VALUES (1, 1)")
    owner.execute("INSERT INTO source VALUES (1, 1)")      # référence complète valide
    owner.execute("INSERT INTO source VALUES (NULL, NULL)")  # référence entièrement vide admise
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        owner.execute("INSERT INTO source VALUES (1, NULL)")  # partiellement vide : refusé


def test_X2_unicite_restreinte_a_un_statut(owner):
    owner.execute("CREATE TABLE creneau (jour date, ouvrier text, statut text)")
    owner.execute(
        "CREATE UNIQUE INDEX un_courant ON creneau (jour, ouvrier) WHERE statut = 'COURANT'"
    )
    owner.execute("INSERT INTO creneau VALUES ('2026-10-12', 'O011', 'FERME')")
    owner.execute("INSERT INTO creneau VALUES ('2026-10-12', 'O011', 'FERME')")
    owner.execute("INSERT INTO creneau VALUES ('2026-10-12', 'O011', 'COURANT')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        owner.execute("INSERT INTO creneau VALUES ('2026-10-12', 'O011', 'COURANT')")


def test_X3_verrou_consultatif_sur_cle_logique_libere_au_commit(base_vierge):
    """Verrou (espace de noms, clé) pris dans une transaction : une autre session ne peut pas
    l'obtenir avant le COMMIT, même si aucune ligne n'existe pour cette clé."""
    with base_vierge.owner() as a, base_vierge.owner() as b:
        a.execute("SELECT pg_advisory_xact_lock(3, 42)")
        assert b.execute("SELECT pg_try_advisory_xact_lock(3, 42)").fetchone()[0] is False
        assert b.execute("SELECT pg_try_advisory_xact_lock(3, 43)").fetchone()[0] is True
        b.rollback()
        a.commit()
        assert b.execute("SELECT pg_try_advisory_xact_lock(3, 42)").fetchone()[0] is True
        b.rollback()


def test_X3_attente_bloquante_puis_reprise(base_vierge):
    """La seconde session attend réellement, puis obtient le verrou après le COMMIT."""
    obtenu = threading.Event()

    def attendre():
        with base_vierge.owner() as b:
            b.execute("SELECT pg_advisory_xact_lock(3, 7)")
            obtenu.set()
            b.rollback()

    with base_vierge.owner() as a:
        a.execute("SELECT pg_advisory_xact_lock(3, 7)")
        fil = threading.Thread(target=attendre)
        fil.start()
        assert not obtenu.wait(0.8), "le verrou n'a pas bloqué la seconde session"
        a.commit()
    assert obtenu.wait(5), "la seconde session n'a pas obtenu le verrou après le COMMIT"
    fil.join(5)


def test_X4_instantane_coherent_repeatable_read(base_vierge):
    with base_vierge.owner() as setup:
        setup.execute("CREATE TABLE donnee (x int)")
        setup.execute("INSERT INTO donnee VALUES (1)")
        setup.commit()

    with base_vierge.owner() as lecteur, base_vierge.owner(autocommit=True) as ecrivain:
        lecteur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert lecteur.execute("SELECT count(*) FROM donnee").fetchone()[0] == 1
        ecrivain.execute("INSERT INTO donnee VALUES (2)")  # validé après le début de la lecture
        assert lecteur.execute("SELECT count(*) FROM donnee").fetchone()[0] == 1
        lecteur.commit()
        assert lecteur.execute("SELECT count(*) FROM donnee").fetchone()[0] == 2


def test_X5_controle_differe_en_fin_de_transaction(owner):
    owner.execute("CREATE TABLE paire (id int PRIMARY KEY, partenaire int)")
    owner.execute(
        """
        CREATE FUNCTION paire_complete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM paire WHERE id = NEW.partenaire) THEN
                RAISE EXCEPTION 'partenaire % absent', NEW.partenaire
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$;
        """
    )
    owner.execute(
        "CREATE CONSTRAINT TRIGGER paire_ctrl AFTER INSERT ON paire "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION paire_complete()"
    )
    owner.commit()

    # Les deux lignes arrivent l'une après l'autre : contrôle satisfait au COMMIT.
    owner.execute("INSERT INTO paire VALUES (1, 2)")
    owner.execute("INSERT INTO paire VALUES (2, 1)")
    owner.commit()

    # Ligne orpheline : acceptée au moment de l'instruction, refusée au COMMIT.
    owner.execute("INSERT INTO paire VALUES (3, 99)")
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.commit()


def test_X6_non_chevauchement_d_intervalles(owner):
    owner.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    owner.execute(
        "CREATE TABLE absence_sonde (ouvrier text, periode daterange, "
        "EXCLUDE USING gist (ouvrier WITH =, periode WITH &&))"
    )
    owner.execute("INSERT INTO absence_sonde VALUES ('O001', '[2026-10-12,2026-10-14]')")
    owner.execute("INSERT INTO absence_sonde VALUES ('O002', '[2026-10-12,2026-10-14]')")
    owner.execute("INSERT INTO absence_sonde VALUES ('O001', '[2026-10-15,2026-10-15]')")
    with pytest.raises(psycopg.errors.ExclusionViolation):
        owner.execute("INSERT INTO absence_sonde VALUES ('O001', '[2026-10-14,2026-10-16]')")
