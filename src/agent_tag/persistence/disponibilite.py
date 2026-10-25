"""Consultation de la disponibilité des ouvriers pour une date, à un instant donné.

Faits lus en base :
- couverture COURANTE à l'instant demandé (périodes debut_courant / fin_courant), par
  (date, chaîne d'origine de l'ouvrier, type de donnée) — l'historique permet de relire le passé ;
- présence : ligne d'affectation du lot dont la couverture AFFECTATIONS est courante ;
- absences : si une couverture ABSENCES est courante pour (date, chaîne), seules les absences de ce
  lot comptent ; sinon, celles de tous les lots appliqués à l'instant demandé.
Le calcul de l'état est fait par agent_tag.domain.disponibilite.evaluer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from agent_tag.domain import disponibilite as regle


@dataclass
class Disponibilite:
    id_ouvrier: str
    nom: str
    id_chaine: str
    etat: str
    cause: str
    besoin_creable: bool
    presence: str | None
    id_affectation: int | None
    lot_affectations: int | None
    couverture_affectations: str | None
    lot_absences: int | None
    couverture_absences: str | None
    absences_certaines: list[int] = field(default_factory=list)
    absences_possibles: list[int] = field(default_factory=list)


def consulter(conn, jour: date, instant: datetime | None = None,
              ouvriers: list[str] | None = None, chaine: str | None = None) -> list[Disponibilite]:
    """Ouvre une transaction en lecture seule (connexion autocommit attendue) et lit les faits."""
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return lire(conn, jour, instant, ouvriers, chaine)


def lire(conn, jour: date, instant: datetime | None = None,
         ouvriers: list[str] | None = None, chaine: str | None = None) -> list[Disponibilite]:
    """Lit les faits dans la transaction déjà ouverte par l'appelant (instantané partagé)."""
    t = conn.execute("SELECT coalesce(%s::timestamptz, now())", (instant,)).fetchone()[0]

    couvertures = {}
    for id_lot, id_ch, type_d, etat in conn.execute(
            "SELECT id_lot, id_chaine, type_donnee, etat FROM batch_coverage "
            "WHERE date = %s AND source = 'IMPORT' AND debut_courant <= %s "
            "AND (fin_courant IS NULL OR fin_courant > %s)", (jour, t, t)):
        couvertures[(id_ch, type_d)] = (id_lot, etat)

    filtre, params = "", []
    if ouvriers:
        filtre += " AND id_ouvrier = ANY(%s)"
        params.append(list(ouvriers))
    if chaine:
        filtre += " AND id_chaine_origine = %s"
        params.append(chaine)
    effectif = conn.execute(
        "SELECT id_ouvrier, nom, id_chaine_origine FROM worker WHERE true" + filtre
        + " ORDER BY id_ouvrier", params).fetchall()

    lots_aff = [v[0] for (ch, ty), v in couvertures.items() if ty == "AFFECTATIONS"]
    affectations = {}
    if lots_aff:
        for id_aff, id_o, statut, id_lot in conn.execute(
                "SELECT id, id_ouvrier, statut_presence, id_lot FROM daily_assignment "
                "WHERE date = %s AND id_lot = ANY(%s) AND statut_ligne = 'ACTIVE'",
                (jour, lots_aff)):
            affectations[(id_o, id_lot)] = (id_aff, statut)

    absences = {}
    for id_abs, id_o, id_lot, debut, duree in conn.execute(
            "SELECT a.id, a.id_ouvrier, a.id_lot, a.date_debut, a.duree_jours "
            "FROM absence a JOIN import_batch b ON b.id = a.id_lot "
            "WHERE b.statut = 'APPLIQUE' AND b.date_application <= %s "
            "AND a.statut_ligne = 'ACTIVE' AND a.date_debut <= %s "
            "AND a.date_debut + (2 * a.duree_jours - 1) > %s",
            (t, jour, jour)):
        absences.setdefault(id_o, []).append((id_abs, id_lot, debut, duree))

    resultats = []
    for id_o, nom, id_ch in effectif:
        lot_aff, etat_aff = couvertures.get((id_ch, "AFFECTATIONS"), (None, None))
        lot_abs, etat_abs = couvertures.get((id_ch, "ABSENCES"), (None, None))
        id_aff, presence = affectations.get((id_o, lot_aff), (None, None))
        pertinentes = [a for a in absences.get(id_o, []) if lot_abs is None or a[1] == lot_abs]
        certaines = [a[0] for a in pertinentes if regle.couvre_certainement(a[2], a[3], jour)]
        possibles = [a[0] for a in pertinentes if regle.couvre_possiblement(a[2], a[3], jour)]
        res = regle.evaluer(regle.Faits(
            presence=presence,
            absence_certaine=bool(certaines),
            absence_possible=bool(possibles),
            absences_completes=(etat_abs == "COMPLET"),
        ))
        resultats.append(Disponibilite(
            id_o, nom, id_ch, res.etat, res.cause, res.besoin_creable, presence, id_aff,
            lot_aff, etat_aff, lot_abs, etat_abs, certaines, possibles))
    return resultats
