"""Lecture de l'instantané utilisé par le moteur d'allocation.

Toutes les lectures ont lieu dans UNE transaction REPEATABLE READ READ ONLY (exigence R-SNAP) :
les données sont cohérentes entre elles et la base refuse toute écriture pendant le calcul.
À l'incrément 3 il n'existe ni run ni réservation persistés : S0 et les chaînes interdites
(R-CASCADE) sont vides.
"""

from __future__ import annotations

from datetime import date, datetime

from agent_tag.domain import allocation as a
from agent_tag.persistence import disponibilite


def lire(conn, jour: date, instant: datetime | None = None) -> a.Instantane:
    """`conn` doit être en autocommit (la transaction de lecture est ouverte ici)."""
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return lire_dans_transaction(conn, jour, instant)


def lire_dans_transaction(conn, jour: date, instant: datetime | None = None) -> a.Instantane:
    """Même lecture, dans une transaction déjà ouverte par l'appelant (instantané partagé)."""
    lecture = conn.execute("SELECT coalesce(%s::timestamptz, now())",
                           (instant,)).fetchone()[0]
    etats = disponibilite.lire(conn, jour, lecture)

    ouvriers = {i: a.Ouvrier(i, n, ch, p) for i, n, ch, p in conn.execute(
        "SELECT id_ouvrier, nom, id_chaine_origine, code_poste_principal FROM worker")}

    ids_aff = [d.id_affectation for d in etats if d.id_affectation is not None]
    affectations = {}
    if ids_aff:
        for id_aff, ch, poste, hd, hf in conn.execute(
                "SELECT id, id_chaine, code_poste, heure_debut, heure_fin "
                "FROM daily_assignment WHERE id = ANY(%s)", (ids_aff,)):
            affectations[id_aff] = (ch, poste, hd, hf)
    jour_par_ouvrier = {}
    for d in etats:
        ch, poste, hd, hf = affectations.get(d.id_affectation, (None, None, None, None))
        jour_par_ouvrier[d.id_ouvrier] = a.Jour(
            d.etat, d.cause, d.besoin_creable, ch, poste, hd, hf, d.id_affectation,
            d.absences_certaines[0] if d.absences_certaines else None)

    niveaux = {code: (lib, rang) for code, lib, rang in conn.execute(
        "SELECT code_niveau, libelle, rang FROM skill_level")}
    competences = {
        (i, c): a.Detenue(t, n, niveaux[n][1], an, cert)
        for i, c, t, n, an, cert in conn.execute(
            "SELECT id_ouvrier, code_competence, type_competence, code_niveau, "
            "annees_experience, certification FROM worker_skill")}
    exigences = {
        (ch, p): a.Exigence(c, n, niveaux[n][1] if n else None)
        for ch, p, c, n in conn.execute(
            "SELECT id_chaine, code_poste, code_competence_requise, code_niveau_min "
            "FROM position_requirement WHERE statut = 'ACTIVE'")}
    postes = {c: a.Poste(c, lib, comp, src, val) for c, lib, comp, src, val in conn.execute(
        "SELECT code_poste, libelle, code_competence_associee, source_correspondance, "
        "correspondance_validee FROM position")}
    critiques = {}
    for ch, c in conn.execute("SELECT id_chaine, code_competence FROM line_critical_skill"):
        critiques.setdefault(ch, set()).add(c)
    chaines = {i: a.Chaine(i, prio, frozenset(critiques.get(i, ()))) for i, prio in
               conn.execute("SELECT id_chaine, libelle_priorite FROM production_line")}
    libelles = dict(conn.execute("SELECT code_competence, libelle FROM skill"))

    return a.Instantane(
        date=jour, ouvriers=ouvriers, jour=jour_par_ouvrier, competences=competences,
        exigences=exigences, postes=postes, chaines=chaines, libelles_competence=libelles,
        niveaux={c: lib for c, (lib, _) in niveaux.items()}, lecture=lecture.isoformat())
