"""Fixtures communes.

Les tests de base de données créent une base jetable (agent_tag_pytest_<aléa>) à partir
de AGENT_TAG_OWNER_URL, puis la suppriment. La base agent_tag_test n'est jamais modifiée.
Le rôle propriétaire doit avoir le droit CREATEDB (environnement TEST uniquement).
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path

import psycopg
import pytest
from psycopg import conninfo, sql

from agent_tag.config import settings
from agent_tag.persistence import migrations

RACINE = Path(__file__).resolve().parents[1]


def _conf() -> settings.Settings:
    try:
        conf = settings.charger(fichier_env=RACINE / ".env")
    except settings.ConfigurationInvalide as exc:
        pytest.skip(f"configuration absente : {exc}")
    if not conf.owner_url:
        pytest.skip("AGENT_TAG_OWNER_URL absent")
    return conf


class BaseJetable:
    def __init__(self, conf: settings.Settings, nom: str):
        self.nom = nom
        self.owner_url = conninfo.make_conninfo(conf.owner_url, dbname=nom)
        self.app_url = conninfo.make_conninfo(conf.database_url, dbname=nom)

    def owner(self, **kw) -> psycopg.Connection:
        return psycopg.connect(self.owner_url, **kw)

    def app(self, **kw) -> psycopg.Connection:
        return psycopg.connect(self.app_url, **kw)


def _creer_base(conf: settings.Settings) -> BaseJetable:
    nom = f"agent_tag_pytest_{secrets.token_hex(4)}"
    with psycopg.connect(conf.owner_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nom)))
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(nom))
        )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO agent_tag_app").format(sql.Identifier(nom))
        )
    return BaseJetable(conf, nom)


def _supprimer_base(conf: settings.Settings, base: BaseJetable) -> None:
    """Supprime la base jetable.

    Une connexion fermée côté client peut encore être en cours de fermeture côté serveur. Le rôle
    propriétaire ne peut pas interrompre une session d'un autre rôle (agent_tag_app) : on attend
    donc la fin des sessions (jusqu'à 10 s) avant de recourir à FORCE."""
    instruction = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(base.nom))
    with psycopg.connect(conf.owner_url, autocommit=True) as admin:
        for _ in range(100):
            try:
                admin.execute(instruction)
                return
            except psycopg.errors.ObjectInUse:
                time.sleep(0.1)
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(base.nom)))


@pytest.fixture
def base_vierge():
    """Base jetable sans aucune migration."""
    conf = _conf()
    base = _creer_base(conf)
    try:
        yield base
    finally:
        _supprimer_base(conf, base)


@pytest.fixture
def base_migree(base_vierge):
    """Base jetable avec toutes les migrations du dépôt appliquées."""
    migrations.migrer(base_vierge.owner_url)
    return base_vierge


@pytest.fixture
def usage_declare() -> str:
    return _conf().usage
