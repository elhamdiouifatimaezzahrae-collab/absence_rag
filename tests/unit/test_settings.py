"""Configuration de déploiement — aucune valeur supposée."""

import pytest

from agent_tag.config import settings

URL = "postgresql://u:p@localhost:5433/db"


def test_configuration_complete(tmp_path):
    conf = settings.charger(
        env={"AGENT_TAG_USAGE": "TEST", "AGENT_TAG_DATABASE_URL": URL},
        fichier_env=tmp_path / "absent.env",
    )
    assert conf.usage == "TEST"
    assert conf.database_url == URL
    assert conf.owner_url is None


def test_usage_absent_refuse(tmp_path):
    with pytest.raises(settings.ConfigurationInvalide, match="AGENT_TAG_USAGE"):
        settings.charger(env={"AGENT_TAG_DATABASE_URL": URL}, fichier_env=tmp_path / "x")


def test_usage_invalide_refuse(tmp_path):
    with pytest.raises(settings.ConfigurationInvalide, match="invalide"):
        settings.charger(
            env={"AGENT_TAG_USAGE": "test", "AGENT_TAG_DATABASE_URL": URL},
            fichier_env=tmp_path / "x",
        )


def test_url_absente_refusee(tmp_path):
    with pytest.raises(settings.ConfigurationInvalide, match="DATABASE_URL"):
        settings.charger(env={"AGENT_TAG_USAGE": "TEST"}, fichier_env=tmp_path / "x")


def test_fichier_env_lu_et_variables_prioritaires(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# commentaire\nAGENT_TAG_USAGE=EXPLOITATION\nAGENT_TAG_DATABASE_URL='" + URL + "'\n",
        encoding="utf-8",
    )
    assert settings.charger(env={}, fichier_env=f).usage == "EXPLOITATION"
    assert settings.charger(env={"AGENT_TAG_USAGE": "TEST"}, fichier_env=f).usage == "TEST"


def test_ligne_mal_formee_refusee(tmp_path):
    f = tmp_path / ".env"
    f.write_text("AGENT_TAG_USAGE\n", encoding="utf-8")
    with pytest.raises(settings.ConfigurationInvalide, match="sans '='"):
        settings.charger(env={}, fichier_env=f)
