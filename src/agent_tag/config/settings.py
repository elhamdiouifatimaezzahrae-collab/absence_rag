"""Lecture de la configuration de déploiement.

Sources, par ordre de priorité : variables d'environnement, puis fichier .env.
Aucune valeur par défaut n'est supposée pour l'usage ni pour les connexions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

USAGES_VALIDES = ("TEST", "EXPLOITATION")


class ConfigurationInvalide(Exception):
    """La configuration de déploiement est absente ou incorrecte."""


@dataclass(frozen=True)
class Settings:
    usage: str
    database_url: str
    owner_url: str | None
    dossier_archives: Path = Path("archives")


def lire_fichier_env(chemin: Path) -> dict[str, str]:
    """Lit un fichier .env simple : lignes CLE=VALEUR, commentaires '#'."""
    valeurs: dict[str, str] = {}
    if not chemin.is_file():
        return valeurs
    for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if "=" not in ligne:
            raise ConfigurationInvalide(f"{chemin}:{numero} : ligne sans '='")
        cle, valeur = ligne.split("=", 1)
        valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    return valeurs


def charger(env: dict[str, str] | None = None, fichier_env: Path | None = None) -> Settings:
    """Construit la configuration. `env` remplace os.environ (utile pour les tests)."""
    source = dict(lire_fichier_env(fichier_env or Path(".env")))
    source.update(os.environ if env is None else env)

    usage = source.get("AGENT_TAG_USAGE", "").strip()
    if not usage:
        raise ConfigurationInvalide("AGENT_TAG_USAGE n'est pas défini")
    if usage not in USAGES_VALIDES:
        raise ConfigurationInvalide(
            f"AGENT_TAG_USAGE invalide : {usage!r} (attendu : {', '.join(USAGES_VALIDES)})"
        )

    database_url = source.get("AGENT_TAG_DATABASE_URL", "").strip()
    if not database_url:
        raise ConfigurationInvalide("AGENT_TAG_DATABASE_URL n'est pas défini")

    owner_url = source.get("AGENT_TAG_OWNER_URL", "").strip() or None
    archives = Path(source.get("AGENT_TAG_ARCHIVES", "").strip() or "archives")
    return Settings(usage=usage, database_url=database_url, owner_url=owner_url,
                    dossier_archives=archives)
