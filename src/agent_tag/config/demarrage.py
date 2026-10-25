"""Contrôles de démarrage (Phase 4.2 point 3, exigence T8 ; test T94).

L'application refuse de démarrer si :
- le schéma n'est pas à jour (migrations en attente ou modifiées) ;
- l'environnement de la base n'est pas initialisé ;
- l'usage enregistré en base diffère de l'usage déclaré par le déploiement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg

from agent_tag.persistence import migrations


class DemarrageRefuse(Exception):
    """L'application ne doit pas démarrer avec cette base."""


@dataclass(frozen=True)
class EtatEnvironnement:
    id_environnement: str
    usage: str
    libelle: str
    fuseau_horaire: str | None


def verifier(
    conn: psycopg.Connection,
    usage_declare: str,
    dossier_migrations: Path = migrations.DOSSIER_PAR_DEFAUT,
) -> EtatEnvironnement:
    try:
        restantes = migrations.en_attente(conn, dossier_migrations)
    except migrations.ErreurMigration as exc:
        raise DemarrageRefuse(str(exc)) from exc
    if restantes:
        noms = ", ".join(f"{m.version:04d}_{m.nom}" for m in restantes)
        raise DemarrageRefuse(f"Schéma non à jour, migrations en attente : {noms}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id_environnement::text, usage, libelle, fuseau_horaire FROM environment"
        )
        lignes = cur.fetchall()
    if not lignes:
        raise DemarrageRefuse("Environnement non initialisé dans la base")

    etat = EtatEnvironnement(*lignes[0])
    if etat.usage != usage_declare:
        raise DemarrageRefuse(
            f"Usage déclaré par le déploiement ({usage_declare}) différent de l'usage "
            f"de la base ({etat.usage})"
        )
    return etat
