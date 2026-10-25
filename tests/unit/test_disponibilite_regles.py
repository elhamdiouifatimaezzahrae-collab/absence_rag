"""Table de décision de la disponibilité (Phase 4.2 point 6) — un cas par ligne."""

from datetime import date

import pytest

from agent_tag.domain import disponibilite as d
from agent_tag.domain.disponibilite import Faits

P, A, X = "PRESENT", "ABSENT", None


@pytest.mark.parametrize("presence, certaine, possible, completes, etat, cause, besoin", [
    (P, False, False, True,  d.DISPONIBLE,  "PRESENT_SANS_ABSENCE", False),
    (P, False, False, False, d.INCONNU,     "ABSENCES_NON_COMPLETES", False),
    (P, True,  False, True,  d.INDETERMINE, "CONTRADICTION_PRESENT_ET_ABSENCE", False),
    (P, False, True,  True,  d.INDETERMINE, "ABSENCE_POSSIBLE_D19", False),
    (A, True,  False, True,  d.ABSENT,      "ABSENCE_CONFIRMEE", True),
    (A, True,  False, False, d.ABSENT,      "ABSENCE_CONFIRMEE", True),
    (A, False, False, True,  d.INDETERMINE, "CONTRADICTION_ABSENT_SANS_ABSENCE", False),
    (A, False, False, False, d.INDETERMINE, "CONTRADICTION_ABSENT_SANS_ABSENCE", False),
    (A, False, True,  True,  d.INDETERMINE, "ABSENCE_POSSIBLE_D19", False),
    (X, True,  False, True,  d.ABSENT,      "ABSENCE_SANS_AFFECTATION", False),
    (X, False, False, True,  d.INCONNU,     "AFFECTATION_INCONNUE", False),
    (X, False, True,  False, d.INCONNU,     "AFFECTATION_INCONNUE", False),
])
def test_table_de_decision(presence, certaine, possible, completes, etat, cause, besoin):
    res = d.evaluer(Faits(presence, certaine, possible, completes))
    assert (res.etat, res.cause, res.besoin_creable) == (etat, cause, besoin)


def test_une_donnee_manquante_n_est_jamais_une_presence_confirmee():
    for certaine in (False, True):
        for possible in (False, True):
            for completes in (False, True):
                res = d.evaluer(Faits(None, certaine, possible, completes))
                assert res.etat != d.DISPONIBLE


def test_besoin_uniquement_si_affectation_absent_et_absence_certaine():
    for presence in (P, A, X):
        for certaine in (False, True):
            for possible in (False, True):
                for completes in (False, True):
                    res = d.evaluer(Faits(presence, certaine, possible, completes))
                    assert res.besoin_creable == (presence == A and certaine)


def test_presence_invalide_refusee():
    with pytest.raises(ValueError):
        d.evaluer(Faits("PEUT-ETRE", False, False, True))


J = date(2026, 3, 2)


@pytest.mark.parametrize("duree, jour, certaine, possible", [
    (1, date(2026, 3, 1), False, False),
    (1, J, True, False),
    (1, date(2026, 3, 3), False, False),     # durée 1 : aucune incertitude
    (3, date(2026, 3, 4), True, False),      # dernier jour certain
    (3, date(2026, 3, 5), False, True),      # fenêtre D19 : 2 jours
    (3, date(2026, 3, 6), False, True),
    (3, date(2026, 3, 7), False, False),
])
def test_periodes_d_absence(duree, jour, certaine, possible):
    assert d.couvre_certainement(J, duree, jour) is certaine
    assert d.couvre_possiblement(J, duree, jour) is possible
