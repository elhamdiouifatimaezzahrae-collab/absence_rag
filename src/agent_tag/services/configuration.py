"""Configuration d'allocation versionnée (Phase 4.1, correction 5).

Aucune valeur n'est validée à ce jour (D3, D4, D12, D17). En TEST, un profil PROVISOIRE peut être
installé : tous les indicateurs « validé » restent à faux. Hors TEST, la base refuse l'activation
tant que tous les paramètres ne sont pas validés.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from agent_tag.domain import allocation as a


@dataclass(frozen=True)
class ConfigurationEnBase:
    version: int
    statut: str
    domaine: a.Configuration
    indicateurs: dict          # paramètre → validé (bool)

    @property
    def validee(self) -> bool:
        return all(self.indicateurs.values())


def charger(conn, version: int) -> ConfigurationEnBase:
    ligne = conn.execute(
        "SELECT version, statut, libelle, m_bloc, m_alerte, p3, regle_cascade, m_bloc_valide, "
        "m_alerte_valide, p3_valide, priorites_valide, mode_expiration_valide, "
        "regle_cascade_valide FROM allocation_configuration WHERE version = %s",
        (version,)).fetchone()
    if ligne is None:
        raise LookupError(f"configuration {version} inconnue")
    (v, statut, lib, m_bloc, m_alerte, p3, cascade, vb, va, vp, vprio, vexp, vcasc) = ligne
    rangs = dict(conn.execute(
        "SELECT libelle_priorite, rang FROM config_priority_rank WHERE version = %s", (v,)))
    indicateurs = {"m_bloc (P1)": vb, "m_alerte (P2)": va, "p3 (P3)": vp,
                   "priorités (D4)": vprio, "expiration (D12)": vexp, "R-CASCADE (D17)": vcasc}
    domaine = a.Configuration(lib, m_bloc, m_alerte, p3, rangs, cascade,
                              validee=all(indicateurs.values()))
    return ConfigurationEnBase(v, statut, domaine, indicateurs)


def active(conn) -> ConfigurationEnBase | None:
    ligne = conn.execute(
        "SELECT version FROM allocation_configuration WHERE statut = 'ACTIVE'").fetchone()
    return charger(conn, ligne[0]) if ligne else None


def installer_profil_provisoire(url_proprietaire: str, profil: str, auteur: str) -> int:
    """Crée un brouillon à partir d'un profil PROVISOIRE de TEST, puis l'active (l'ancienne
    version active est archivée dans la même transaction). Réservé au rôle propriétaire."""
    cfg = a.PROFILS_PROVISOIRES[profil]
    with psycopg.connect(url_proprietaire) as conn:
        usage = conn.execute("SELECT usage FROM environment").fetchone()
        if not usage or usage[0] != "TEST":
            raise a.ConfigurationInvalide("un profil provisoire ne s'installe qu'en usage TEST")
        id_auteur = conn.execute("SELECT id FROM app_user WHERE identifiant = %s AND actif",
                                 (auteur,)).fetchone()
        if not id_auteur:
            raise a.ConfigurationInvalide(f"utilisateur inconnu ou inactif : {auteur}")
        conn.execute("SELECT pg_advisory_xact_lock(50, 1)")   # S4 : activation sérialisée
        version = conn.execute(
            "INSERT INTO allocation_configuration (libelle, m_bloc, m_alerte, p3, "
            "mode_expiration, regle_cascade, auteur) VALUES (%s, %s, %s, %s, 'MANUELLE', %s, %s) "
            "RETURNING version",
            (cfg.libelle, cfg.m_bloc, cfg.m_alerte, cfg.p3, cfg.regle_cascade, id_auteur[0]),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO config_priority_rank (version, libelle_priorite, rang) "
                "VALUES (%s, %s, %s)", [(version, lib, r) for lib, r in cfg.rangs_priorite.items()])
        conn.execute("UPDATE allocation_configuration SET statut = 'ARCHIVEE' "
                     "WHERE statut = 'ACTIVE'")
        conn.execute("UPDATE allocation_configuration SET statut = 'ACTIVE', active_par = %s, "
                     "date_activation = now() WHERE version = %s", (id_auteur[0], version))
        conn.commit()
    return version
