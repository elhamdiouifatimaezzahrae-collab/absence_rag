-- 0005 — Décisions CHOISIR_AUTRE et ROUVRIR (Phase 4 B4, 3D.2 point 2, A2).
-- CHOISIR_AUTRE : le responsable retient un autre candidat ÉLIGIBLE de la dernière itération ;
-- la proposition courante est annulée (SUBSTITUTION) et référencée par la décision ; le
-- remplacement créé référence la décision (id_decision_creation) et la nouvelle proposition.
-- ROUVRIR : un besoin NON_POURVU d'un calcul ouvert redevient À TRAITER.

ALTER TABLE allocation_decision DROP CONSTRAINT allocation_decision_type_check;
ALTER TABLE allocation_decision ADD CONSTRAINT decision_type CHECK (type IN (
    'ACCEPTER', 'CHOISIR_AUTRE', 'REFUSER', 'LAISSER_NON_POURVU', 'ROUVRIR',
    'ANNULER_REMPLACEMENT', 'CONFIRMER_APRES_REIMPORT'));

ALTER TABLE allocation_decision ADD COLUMN id_proposal_substituee bigint NULL;
ALTER TABLE allocation_decision ADD FOREIGN KEY (id_proposal_substituee, id_besoin)
    REFERENCES proposal (id, id_besoin);
ALTER TABLE allocation_decision ADD CONSTRAINT decision_substitution
    CHECK ((type = 'CHOISIR_AUTRE') = (id_proposal_substituee IS NOT NULL));
