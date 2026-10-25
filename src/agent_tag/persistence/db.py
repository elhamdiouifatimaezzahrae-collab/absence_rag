"""Connexions PostgreSQL. SQL explicite, transactions explicites, pas d'ORM."""

from __future__ import annotations

import psycopg


def connecter(url: str, *, autocommit: bool = False) -> psycopg.Connection:
    """Ouvre une connexion. Le fuseau de session est fixé à UTC pour des horodatages stables."""
    conn = psycopg.connect(url, autocommit=autocommit, application_name="agent_tag")
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
    if not autocommit:
        conn.commit()
    return conn
