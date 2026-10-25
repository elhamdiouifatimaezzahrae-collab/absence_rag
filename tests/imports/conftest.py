import pytest

from agent_tag.imports import import_referentiel


@pytest.fixture
def base_import(base_migree):
    """Base migrée + environnement TEST + utilisateur 'testeur'."""
    with base_migree.owner() as conn:
        conn.execute("INSERT INTO environment (usage, libelle) VALUES ('TEST', 'pytest')")
        conn.execute("INSERT INTO app_user (identifiant, nom, role) "
                     "VALUES ('testeur', 'Utilisateur de test', 'TEST_TOUS_DROITS')")
    return base_migree


@pytest.fixture
def importer(base_import, tmp_path):
    archives = tmp_path / "archives"

    def _importer(chemin, auteur="testeur"):
        return import_referentiel.importer(base_import.app_url, chemin, auteur, archives)

    _importer.archives = archives
    return _importer


@pytest.fixture
def base_referentiel(base_import, importer, tmp_path):
    """Base avec le référentiel ARTIFICIEL de fabrique.Classeur() appliqué."""
    from fabrique import Classeur

    from agent_tag.imports import rapport as r

    rap = importer(Classeur().ecrire(tmp_path / "referentiel.xlsx"))
    assert rap.statut == r.APPLIQUE, rap.en_texte()
    return base_import


@pytest.fixture
def importer_jour(base_referentiel, tmp_path):
    from agent_tag.imports import import_journalier

    compteur = iter(range(1, 1000))

    def _importer(classeur_ou_chemin, attester=True, auteur="testeur"):
        chemin = classeur_ou_chemin
        if not hasattr(chemin, "is_file"):
            chemin = classeur_ou_chemin.ecrire(tmp_path / f"jour_{next(compteur)}.xlsx")
        return import_journalier.importer(base_referentiel.app_url, chemin, auteur,
                                          tmp_path / "archives", attester)

    return _importer


@pytest.fixture
def dispo(base_referentiel):
    """dispo(jour, instant=None) -> {id_ouvrier: Disponibilite}"""
    import psycopg

    from agent_tag.persistence import disponibilite

    def _dispo(jour, instant=None, **filtres):
        with psycopg.connect(base_referentiel.app_url, autocommit=True) as conn:
            return {d.id_ouvrier: d for d in disponibilite.consulter(
                conn, jour.date() if hasattr(jour, "date") else jour, instant, **filtres)}

    return _dispo
