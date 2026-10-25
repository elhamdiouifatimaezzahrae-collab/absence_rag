"""Règles de disponibilité d'un ouvrier pour une date (Phase 4.2 point 6 ; A1 ; D18, D19).

Fonctions pures : aucune base de données. `Ouvriers.Statut` n'est jamais utilisé (R6).

Entrées (faits établis à partir des données courantes) :
- présence : valeur de l'affectation journalière courante (PRESENT, ABSENT) ou None (inconnue) ;
- absence certaine : une absence couvre la date sur sa période calendaire certaine (A1) ;
- absence possible : la date suit la période certaine d'une absence de plus d'un jour
  (lecture « jours de production » possible tant que D19 n'est pas tranchée) ;
- absences complètes : la couverture des absences de la chaîne pour la date est COMPLÈTE
  (attestée, D18).

Sorties : état, cause, et si un besoin de remplacement peut être créé (A1 : affectation ABSENT
ET absence certaine, les deux conditions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DISPONIBLE = "DISPONIBLE"
ABSENT = "ABSENT"
INDETERMINE = "INDETERMINE"
INCONNU = "INCONNU"

PRESENT, ABSENT_AFFECTATION = "PRESENT", "ABSENT"


@dataclass(frozen=True)
class Faits:
    presence: str | None
    absence_certaine: bool
    absence_possible: bool
    absences_completes: bool


@dataclass(frozen=True)
class Resultat:
    etat: str
    cause: str
    besoin_creable: bool = False


def evaluer(f: Faits) -> Resultat:
    if f.presence == PRESENT:
        if f.absence_certaine:
            return Resultat(INDETERMINE, "CONTRADICTION_PRESENT_ET_ABSENCE")
        if f.absence_possible:
            return Resultat(INDETERMINE, "ABSENCE_POSSIBLE_D19")
        if f.absences_completes:
            return Resultat(DISPONIBLE, "PRESENT_SANS_ABSENCE")
        return Resultat(INCONNU, "ABSENCES_NON_COMPLETES")

    if f.presence == ABSENT_AFFECTATION:
        if f.absence_certaine:
            return Resultat(ABSENT, "ABSENCE_CONFIRMEE", besoin_creable=True)
        if f.absence_possible:
            return Resultat(INDETERMINE, "ABSENCE_POSSIBLE_D19")
        return Resultat(INDETERMINE, "CONTRADICTION_ABSENT_SANS_ABSENCE")

    if f.presence is None:
        if f.absence_certaine:
            return Resultat(ABSENT, "ABSENCE_SANS_AFFECTATION")
        return Resultat(INCONNU, "AFFECTATION_INCONNUE")

    raise ValueError(f"présence inconnue : {f.presence!r}")


def couvre_certainement(debut: date, duree: int, jour: date) -> bool:
    """Période calendaire certaine : [début, début + durée − 1] (A1)."""
    return debut <= jour <= debut + timedelta(days=duree - 1)


def couvre_possiblement(debut: date, duree: int, jour: date) -> bool:
    """Fenêtre d'incertitude D19 (choix provisoire TEST, non validé) : pour une durée N > 1, les
    N − 1 jours qui suivent la période certaine. Sans effet pour N = 1."""
    if duree <= 1:
        return False
    fin_certaine = debut + timedelta(days=duree - 1)
    return fin_certaine < jour <= fin_certaine + timedelta(days=duree - 1)
