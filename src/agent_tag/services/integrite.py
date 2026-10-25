"""Vérificateur d'invariants (Phase 4 B6). Détecte, ne corrige jamais.

Chaque requête retourne les lignes en violation ; une liste vide signifie que l'invariant tient.
"""

from __future__ import annotations

CONTROLES = {
    "I1 besoin EN_ATTENTE ⇔ une proposition ACTIVE": """
        SELECT r.id FROM replacement_request r
        LEFT JOIN proposal p ON p.id_besoin = r.id AND p.statut = 'ACTIVE'
        GROUP BY r.id, r.statut_cycle
        HAVING (r.statut_cycle = 'EN_ATTENTE') <> (count(p.id) = 1) OR count(p.id) > 1""",
    "I2 besoin POURVU ⇔ un remplacement ACTIF et aucune proposition ACTIVE": """
        SELECT r.id FROM replacement_request r
        WHERE (r.statut_cycle = 'POURVU') <> (
                  (SELECT count(*) FROM replacement_assignment a
                    WHERE a.id_besoin = r.id AND a.statut = 'ACTIF') = 1)
           OR (r.statut_cycle = 'POURVU' AND EXISTS (
                  SELECT 1 FROM proposal p WHERE p.id_besoin = r.id AND p.statut = 'ACTIVE'))""",
    "I3 besoin BLOQUE sans proposition ni remplacement actifs": """
        SELECT r.id FROM replacement_request r WHERE r.statut_cycle = 'BLOQUE' AND (
            EXISTS (SELECT 1 FROM proposal p WHERE p.id_besoin = r.id AND p.statut = 'ACTIVE')
            OR EXISTS (SELECT 1 FROM replacement_assignment a
                        WHERE a.id_besoin = r.id AND a.statut = 'ACTIF'))""",
    "I6 proposition ACTIVE ⇒ run OUVERT": """
        SELECT p.id FROM proposal p JOIN allocation_run r ON r.id = p.id_run
        WHERE p.statut = 'ACTIVE' AND r.statut <> 'OUVERT'""",
    "I13a proposition ACTIVE ⇔ créneau RESERVE courant": """
        SELECT p.id FROM proposal p
        FULL JOIN (SELECT * FROM worker_day_slot WHERE statut = 'COURANT' AND type = 'RESERVE') s
               ON s.id_proposal = p.id
        WHERE (p.statut = 'ACTIVE' AND s.id IS NULL)
           OR (s.id IS NOT NULL AND (p.id IS NULL OR p.statut <> 'ACTIVE'))""",
    "I13b remplacement ACTIF ⇔ créneau ENGAGE courant": """
        SELECT a.id FROM replacement_assignment a
        FULL JOIN (SELECT * FROM worker_day_slot WHERE statut = 'COURANT' AND type = 'ENGAGE') s
               ON s.id_remplacement = a.id
        WHERE (a.statut = 'ACTIF' AND s.id IS NULL)
           OR (s.id IS NOT NULL AND (a.id IS NULL OR a.statut <> 'ACTIF'))""",
    "I14 run OUVERT : propositions actives de la dernière itération": """
        SELECT p.id FROM proposal p JOIN allocation_run r ON r.id = p.id_run
        WHERE p.statut = 'ACTIVE' AND r.statut = 'OUVERT'
          AND p.numero <> (SELECT max(numero) FROM allocation_iteration i WHERE i.id_run = r.id)""",
    "I16 run CLOS sans réservation ni besoin vivant non pourvu": """
        SELECT r.id FROM allocation_run r WHERE r.statut = 'CLOS' AND (
            EXISTS (SELECT 1 FROM proposal p WHERE p.id_run = r.id AND p.statut = 'ACTIVE')
            OR EXISTS (SELECT 1 FROM replacement_request b WHERE b.id_run = r.id
                        AND b.statut_cycle IN ('BLOQUE', 'A_TRAITER', 'EN_ATTENTE')))""",
    "I21 remplacement ANNULE ⇔ une décision d'annulation": """
        SELECT a.id FROM replacement_assignment a
        WHERE (a.statut = 'ANNULE') <> EXISTS (
            SELECT 1 FROM allocation_decision d
             WHERE d.id_remplacement = a.id AND d.type = 'ANNULER_REMPLACEMENT')""",
    "I23 run A_RECALCULER sans proposition active ni besoin EN_ATTENTE": """
        SELECT r.id FROM allocation_run r WHERE r.statut = 'A_RECALCULER' AND (
            EXISTS (SELECT 1 FROM proposal p WHERE p.id_run = r.id AND p.statut = 'ACTIVE')
            OR EXISTS (SELECT 1 FROM replacement_request b WHERE b.id_run = r.id
                        AND b.statut_cycle = 'EN_ATTENTE'))""",
    "CHOISIR_AUTRE : un remplacement créé et la proposition substituée annulée": """
        SELECT d.id FROM allocation_decision d
        WHERE d.type = 'CHOISIR_AUTRE' AND (
            (SELECT count(*) FROM replacement_assignment a WHERE a.id_decision_creation = d.id) <> 1
            OR NOT EXISTS (SELECT 1 FROM proposal p WHERE p.id = d.id_proposal_substituee
                           AND p.statut = 'ANNULEE' AND p.motif_annulation = 'SUBSTITUTION'))""",
    "Unicité : un ouvrier engagé ou réservé au plus une fois par jour": """
        SELECT date || ' ' || id_ouvrier FROM worker_day_slot WHERE statut = 'COURANT'
        GROUP BY date, id_ouvrier HAVING count(*) > 1""",
    "Remplacement : ouvrier jamais engagé deux fois le même jour": """
        SELECT date || ' ' || id_ouvrier FROM replacement_assignment WHERE statut = 'ACTIF'
        GROUP BY date, id_ouvrier HAVING count(*) > 1""",
}


def verifier(conn) -> dict[str, list]:
    """Retourne {invariant: lignes en violation} pour les seuls invariants violés."""
    violations = {}
    for nom, sql in CONTROLES.items():
        lignes = [r[0] for r in conn.execute(sql).fetchall()]
        if lignes:
            violations[nom] = lignes
    return violations
