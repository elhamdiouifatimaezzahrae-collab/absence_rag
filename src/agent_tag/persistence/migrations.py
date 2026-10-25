"""Exécuteur de migrations SQL versionnées.

- Fichiers `migrations/NNNN_nom.sql`, appliqués dans l'ordre des numéros.
- Chaque migration est appliquée dans sa propre transaction : tout ou rien.
- L'empreinte SHA-256 de chaque fichier appliqué est enregistrée. Un fichier déjà
  appliqué puis modifié est refusé : on ajoute une nouvelle migration à la place.
- Un verrou consultatif empêche deux exécutions simultanées.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

DOSSIER_PAR_DEFAUT = Path(__file__).resolve().parents[3] / "migrations"
_MOTIF = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_VERROU_MIGRATIONS = (900, 1)  # (espace de noms, clé) réservé aux migrations

_TABLE_SUIVI = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     integer     PRIMARY KEY,
    nom         text        NOT NULL,
    empreinte   char(64)    NOT NULL,
    appliquee_a timestamptz NOT NULL DEFAULT now()
)
"""


class ErreurMigration(Exception):
    """Migration incohérente ou en échec."""


@dataclass(frozen=True)
class Migration:
    version: int
    nom: str
    chemin: Path

    @property
    def sql(self) -> str:
        return self.chemin.read_text(encoding="utf-8")

    @property
    def empreinte(self) -> str:
        return hashlib.sha256(self.chemin.read_bytes()).hexdigest()


def lister(dossier: Path = DOSSIER_PAR_DEFAUT) -> list[Migration]:
    migrations = []
    for chemin in sorted(dossier.glob("*.sql")):
        m = _MOTIF.match(chemin.name)
        if not m:
            raise ErreurMigration(f"Nom de migration invalide : {chemin.name}")
        migrations.append(Migration(int(m.group(1)), m.group(2), chemin))
    versions = [m.version for m in migrations]
    if len(versions) != len(set(versions)):
        raise ErreurMigration("Deux migrations portent le même numéro")
    return migrations


def appliquees(conn: psycopg.Connection) -> dict[int, str]:
    """Versions appliquées et leur empreinte (vide si la table de suivi n'existe pas)."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migration') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {}
        cur.execute("SELECT version, empreinte FROM schema_migration")
        return dict(cur.fetchall())


def en_attente(conn: psycopg.Connection, dossier: Path = DOSSIER_PAR_DEFAUT) -> list[Migration]:
    """Migrations non appliquées. Lève une erreur si un fichier appliqué a changé."""
    deja = appliquees(conn)
    restantes = []
    for m in lister(dossier):
        if m.version in deja:
            if deja[m.version] != m.empreinte:
                raise ErreurMigration(
                    f"La migration {m.version:04d}_{m.nom} a été modifiée après application"
                )
        else:
            restantes.append(m)
    return restantes


def migrer(url_proprietaire: str, dossier: Path = DOSSIER_PAR_DEFAUT) -> list[Migration]:
    """Applique les migrations en attente. Retourne la liste des migrations appliquées."""
    faites: list[Migration] = []
    with psycopg.connect(url_proprietaire, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(_TABLE_SUIVI)
            cur.execute("GRANT SELECT ON schema_migration TO agent_tag_app")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s, %s)", _VERROU_MIGRATIONS)
        try:
            for m in en_attente(conn, dossier):
                try:
                    with conn.cursor() as cur:
                        cur.execute(m.sql)
                        cur.execute(
                            "INSERT INTO schema_migration (version, nom, empreinte) "
                            "VALUES (%s, %s, %s)",
                            (m.version, m.nom, m.empreinte),
                        )
                    conn.commit()
                except psycopg.Error as exc:
                    conn.rollback()
                    raise ErreurMigration(
                        f"Échec de la migration {m.version:04d}_{m.nom} : {exc}"
                    ) from exc
                faites.append(m)
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s, %s)", _VERROU_MIGRATIONS)
            conn.commit()
    return faites
