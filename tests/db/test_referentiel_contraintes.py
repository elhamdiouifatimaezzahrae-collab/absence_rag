"""Contraintes du référentiel garanties par la base elle-même (indépendamment du code d'import)."""

import psycopg
import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def base(base_migree):
    """Mini-référentiel inséré directement en SQL par le propriétaire."""
    with base_migree.owner() as c:
        c.execute("INSERT INTO app_user (identifiant, nom, role) VALUES ('u', 'U', 'TEST')")
        c.execute("INSERT INTO import_batch (type, perimetre, fichier_source, empreinte_fichier, "
                  "auteur, statut, date_application) VALUES ('IMPORT', 'REFERENTIEL', 'x.xlsx', "
                  "repeat('a', 64), 1, 'APPLIQUE', now())")
        c.execute("INSERT INTO skill VALUES ('PIQUEUSE', 'Piqueuse', 1), ('COUPE', 'Coupe', 1)")
        c.execute("INSERT INTO position VALUES ('PIQUEUR', 'Piqueur', 'PIQUEUSE', "
                  "'BESOINS_POSTES', true, 1)")
        c.execute("INSERT INTO production_line VALUES ('LA', 'A', 1, 1, 'Moyenne', 10, 1)")
    return base_migree


def _ouvrier(c, id_o="T1", principales=(("PIQUEUSE",),), secondaires=()):
    c.execute("INSERT INTO worker VALUES (%s, 'N', 'LA', 'PIQUEUR', '08:00', '16:00', NULL, 1)",
              (id_o,))
    for (comp,) in principales:
        c.execute("INSERT INTO worker_skill VALUES (%s, %s, 'PRINCIPALE', 1, 'DEBUTANT', false, 1)",
                  (id_o, comp))
    for (comp,) in secondaires:
        c.execute("INSERT INTO worker_skill VALUES (%s, %s, 'SECONDAIRE', 1, 'DEBUTANT', false, 1)",
                  (id_o, comp))


def test_ouvrier_valide(base):
    with base.owner() as c:
        _ouvrier(c, secondaires=(("COUPE",),))
        c.commit()


def test_ouvrier_sans_principale_refuse_au_commit(base):
    with base.owner() as c:
        _ouvrier(c, principales=())
        with pytest.raises(psycopg.errors.CheckViolation, match="0 compétence"):
            c.commit()


def test_deux_principales_refusees(base):
    with base.owner() as c:
        with pytest.raises(psycopg.errors.UniqueViolation):
            _ouvrier(c, principales=(("PIQUEUSE",), ("COUPE",)))


def test_principale_differente_du_poste_refusee(base):
    with base.owner() as c:
        _ouvrier(c, principales=(("COUPE",),))
        with pytest.raises(psycopg.errors.CheckViolation, match="différente de celle du poste"):
            c.commit()


def test_niveau_hors_nomenclature_refuse(base):
    with base.owner() as c:
        c.execute("INSERT INTO worker VALUES ('T1', 'N', 'LA', 'PIQUEUR', '08:00', '16:00', NULL, 1)")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("INSERT INTO worker_skill VALUES ('T1', 'PIQUEUSE', 'PRINCIPALE', 1, "
                      "'AVANCE', false, 1)")


def test_une_seule_exigence_active_par_chaine_et_poste(base):
    with base.owner() as c:
        sql = ("INSERT INTO position_requirement (id_chaine, code_poste, version, "
               "code_competence_requise, code_niveau_min, origine, statut, id_lot_import) "
               "VALUES ('LA', 'PIQUEUR', %s, 'PIQUEUSE', NULL, 'EXCEL', 'ACTIVE', 1)")
        c.execute(sql, (1,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(sql, (2,))


def test_exigence_saisie_exige_auteur_et_motif(base):
    with base.owner() as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("INSERT INTO position_requirement (id_chaine, code_poste, version, "
                      "code_competence_requise, origine, statut) "
                      "VALUES ('LA', 'PIQUEUR', 1, 'PIQUEUSE', 'SAISIE', 'ACTIVE')")


def test_un_seul_referentiel_applique_D15(base):
    with base.owner() as c:
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute("INSERT INTO import_batch (type, perimetre, fichier_source, "
                      "empreinte_fichier, auteur, statut, date_application) VALUES "
                      "('IMPORT', 'REFERENTIEL', 'y.xlsx', repeat('b', 64), 1, 'APPLIQUE', now())")


@pytest.mark.parametrize("instruction", [
    "UPDATE worker SET nom = 'X'",
    "DELETE FROM worker",
    "UPDATE skill SET libelle = 'X'",
    "UPDATE import_batch SET statut = 'REJETE'",
    "DELETE FROM import_batch",
    "INSERT INTO app_user (identifiant, nom, role) VALUES ('z', 'z', 'z')",
])
def test_role_applicatif_ne_modifie_pas_le_referentiel(base, instruction):
    with base.app() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(instruction)
