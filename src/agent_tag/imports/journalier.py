"""Contrôle des feuilles Absences et Affectations, sans écriture.

Les identifiants sont rapprochés du référentiel déjà importé en base. Aucune donnée n'est
complétée ni générée : seules les dates présentes dans les feuilles sont prises en compte.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from agent_tag.domain import disponibilite as dispo
from agent_tag.imports import rapport as r
from agent_tag.imports.classeur import Feuille
from agent_tag.imports.referentiel import _Lecteur

STATUTS_AFFECTATION = {"Présent": "PRESENT", "Absent": "ABSENT"}
STATUTS_ABSENCE = ("Absent",)   # seule valeur observée ; toute autre est refusée (sens inconnu)
_HORAIRE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


@dataclass(frozen=True)
class ContexteReferentiel:
    ouvriers: dict[str, tuple[str, str, str]]   # id -> (nom, chaîne d'origine, code poste principal)
    chaines: dict[str, str]                     # id -> produit
    postes: dict[str, str]                      # libellé -> code

    def effectif(self, id_chaine: str) -> set[str]:
        return {i for i, (_, ch, _) in self.ouvriers.items() if ch == id_chaine}


@dataclass
class Affectation:
    date: date
    id_ouvrier: str
    id_chaine: str
    code_poste: str
    heure_debut: time
    heure_fin: time
    statut_presence: str
    statut_source: str


@dataclass
class Absence:
    date_debut: date
    duree: int
    id_ouvrier: str
    id_chaine: str
    code_poste: str
    statut_source: str
    motif: str | None


@dataclass
class Couverture:
    date: date
    id_chaine: str
    type_donnee: str
    etat: str


@dataclass
class DonneesJournalieres:
    affectations: list[Affectation] = field(default_factory=list)
    absences: list[Absence] = field(default_factory=list)
    couvertures: list[Couverture] = field(default_factory=list)

    @property
    def dates(self) -> list[date]:
        """Toutes les dates dont l'état peut changer avec ce lot : dates d'affectation et jours
        couverts (certainement ou possiblement, D19) par les absences."""
        jours = {c.date for c in self.couvertures} | {a.date for a in self.affectations}
        for a in self.absences:
            etendue = a.duree if a.duree == 1 else 2 * a.duree - 1
            jours.update(a.date_debut + timedelta(days=k) for k in range(etendue))
        return sorted(jours)


def _date(lec: _Lecteur, ligne, col) -> date | None:
    v = ligne.valeurs.get(col)
    if v is None or (isinstance(v, str) and not v.strip()):
        lec.rapport.ajouter(r.BLOQUANTE, "VALEUR_OBLIGATOIRE",
                            "date absente (ou formule sans valeur calculée)",
                            lec.feuille, ligne.numero, col)
        return None
    if isinstance(v, datetime):
        if v.time() != time(0, 0):
            lec.bloquer("DATE_INVALIDE", f"date avec heure non nulle : {v.isoformat()}", ligne, col)
            return None
        return v.date()
    if isinstance(v, date):
        return v
    lec.bloquer("DATE_INVALIDE",
                f"date Excel attendue, valeur {v!r} ({type(v).__name__}) refusée", ligne, col)
    return None


def _horaire(lec: _Lecteur, ligne, col):
    texte = lec.texte(ligne, col)
    if texte is None:
        return None
    m = _HORAIRE.match(texte)
    try:
        if not m:
            raise ValueError
        debut, fin = time(int(m[1]), int(m[2])), time(int(m[3]), int(m[4]))
        if fin <= debut:
            raise ValueError
        return debut, fin
    except ValueError:
        lec.bloquer("VALEUR_INVALIDE", f"horaire invalide : {texte!r} (HH:MM-HH:MM)", ligne, col)
        return None


def _identite(lec, ctx: ContexteReferentiel, ligne, id_o, nom, id_ch, produit, poste,
              col_chaine, col_poste):
    """Contrôles communs : ouvrier, nom, chaîne, produit, poste. Retourne le code poste ou None."""
    ok = True
    if id_o is not None and id_o not in ctx.ouvriers:
        lec.bloquer("REFERENCE_ORPHELINE", f"ouvrier {id_o} absent du référentiel", ligne,
                    "ID_Ouvrier")
        ok = False
    elif id_o is not None and nom is not None and ctx.ouvriers[id_o][0] != nom:
        lec.bloquer("INCOHERENCE",
                    f"nom {nom!r} différent de celui de {id_o} ({ctx.ouvriers[id_o][0]!r})",
                    ligne, "Nom")
        ok = False
    if id_ch is not None and id_ch not in ctx.chaines:
        lec.bloquer("REFERENCE_ORPHELINE", f"chaîne {id_ch} absente du référentiel", ligne,
                    col_chaine)
        ok = False
    elif id_ch is not None and produit is not None and ctx.chaines[id_ch] != produit:
        lec.bloquer("INCOHERENCE", f"produit {produit} différent de celui de {id_ch}", ligne,
                    "Produit")
        ok = False
    code_poste = None
    if poste is not None:
        code_poste = ctx.postes.get(poste)
        if code_poste is None:
            lec.bloquer("REFERENCE_ORPHELINE", f"poste {poste!r} absent du référentiel", ligne,
                        col_poste)
            ok = False
    return code_poste if ok else None


def controler(feuilles: dict[str, Feuille], ctx: ContexteReferentiel, rapport: r.Rapport,
              absences_attestees: bool) -> DonneesJournalieres:
    donnees = DonneesJournalieres()
    if "Affectations" not in feuilles or "Absences" not in feuilles:
        return donnees  # structure déjà signalée comme bloquante

    _affectations(feuilles["Affectations"], ctx, rapport, donnees)
    _absences(feuilles["Absences"], ctx, rapport, donnees)
    if rapport.bloquantes:
        return donnees
    _couvertures(ctx, rapport, donnees, absences_attestees)
    _contradictions(rapport, donnees)
    return donnees


def _affectations(f: Feuille, ctx, rapport, donnees: DonneesJournalieres) -> None:
    lec = _Lecteur(rapport, f.nom)
    vues: set[tuple[date, str]] = set()
    for ligne in f.lignes:
        jour = _date(lec, ligne, "Date")
        id_o = lec.texte(ligne, "ID_Ouvrier")
        nom = lec.texte(ligne, "Nom")
        id_ch = lec.texte(ligne, "Chaîne")
        produit = lec.texte(ligne, "Produit")
        poste = lec.texte(ligne, "Poste")
        horaire = _horaire(lec, ligne, "Horaire")
        statut = lec.texte(ligne, "Statut_affectation")
        ok = None not in (jour, id_o, nom, id_ch, produit, poste, horaire, statut)
        code_poste = _identite(lec, ctx, ligne, id_o, nom, id_ch, produit, poste, "Chaîne", "Poste")
        ok = ok and code_poste is not None
        if statut is not None and statut not in STATUTS_AFFECTATION:
            lec.bloquer("VALEUR_INVALIDE",
                        f"statut {statut!r} (attendu : {', '.join(STATUTS_AFFECTATION)})",
                        ligne, "Statut_affectation")
            ok = False
        if ok and (jour, id_o) in vues:
            lec.bloquer("IDENTIFIANT_DUPLIQUE",
                        f"affectation de {id_o} le {jour.isoformat()} déjà déclarée", ligne,
                        "ID_Ouvrier")
            ok = False
        if not ok:
            continue
        vues.add((jour, id_o))
        origine = ctx.ouvriers[id_o][1]
        if id_ch != origine:
            rapport.ajouter(r.AVERTISSEMENT, "AFFECTATION_HORS_CHAINE",
                            f"{id_o} affecté à {id_ch} le {jour.isoformat()} (chaîne d'origine "
                            f"{origine}) ; la couverture est calculée sur la chaîne d'origine",
                            f.nom, ligne.numero)
        donnees.affectations.append(Affectation(jour, id_o, id_ch, code_poste, horaire[0],
                                                horaire[1], STATUTS_AFFECTATION[statut], statut))


def _absences(f: Feuille, ctx, rapport, donnees: DonneesJournalieres) -> None:
    lec = _Lecteur(rapport, f.nom)
    par_ouvrier: dict[str, list[tuple[date, int, int]]] = defaultdict(list)
    for ligne in f.lignes:
        debut = _date(lec, ligne, "Date")
        id_o = lec.texte(ligne, "ID_Ouvrier")
        nom = lec.texte(ligne, "Nom")
        id_ch = lec.texte(ligne, "Chaîne")
        poste = lec.texte(ligne, "Poste_principal")
        statut = lec.texte(ligne, "Statut_absence")
        motif = lec.texte(ligne, "Motif", obligatoire=False)
        duree = lec.entier(ligne, "Durée_jours", minimum=1)
        ok = None not in (debut, id_o, nom, id_ch, poste, statut, duree)
        code_poste = _identite(lec, ctx, ligne, id_o, nom, id_ch, None, poste, "Chaîne",
                               "Poste_principal")
        ok = ok and code_poste is not None
        if statut is not None and statut not in STATUTS_ABSENCE:
            lec.bloquer("VALEUR_INVALIDE",
                        f"statut d'absence {statut!r} non reconnu (valeur connue : Absent)",
                        ligne, "Statut_absence")
            ok = False
        if not ok:
            continue
        for autre_debut, autre_duree, autre_ligne in par_ouvrier[id_o]:
            if debut < autre_debut + _jours(autre_duree) and autre_debut < debut + _jours(duree):
                lec.bloquer("ABSENCES_CHEVAUCHANTES",
                            f"absence de {id_o} chevauchant celle de la ligne {autre_ligne}",
                            ligne, "Date")
                ok = False
                break
        if not ok:
            continue
        par_ouvrier[id_o].append((debut, duree, ligne.numero))
        nom_ref, origine, poste_ref = ctx.ouvriers[id_o]
        if id_ch != origine or code_poste != poste_ref:
            rapport.ajouter(r.AVERTISSEMENT, "ABSENCE_HORS_REFERENTIEL",
                            f"{id_o} : chaîne/poste de l'absence ({id_ch}, {poste}) différents du "
                            "référentiel ; valeurs de l'absence conservées", f.nom, ligne.numero)
        if duree > 1:
            rapport.ajouter(r.DECISION, "DUREE_A_INTERPRETER",
                            f"{id_o} : absence de {duree} jours à partir du {debut.isoformat()} ; "
                            "seule la période calendaire est certaine (D19 ouverte)",
                            f.nom, ligne.numero, "Durée_jours")
        donnees.absences.append(Absence(debut, duree, id_o, id_ch, code_poste, statut, motif))


def _jours(n: int) -> timedelta:
    return timedelta(days=n)


def _couvertures(ctx, rapport, donnees: DonneesJournalieres, absences_attestees: bool) -> None:
    """Affectations : couverture calculée par (date, chaîne d'origine), uniquement pour les couples
    où le fichier contient au moins une affectation. Absences : même périmètre, état déclaré."""
    par_couple: dict[tuple[date, str], set[str]] = defaultdict(set)
    for a in donnees.affectations:
        par_couple[(a.date, ctx.ouvriers[a.id_ouvrier][1])].add(a.id_ouvrier)
    for (jour, id_ch), presents in sorted(par_couple.items()):
        effectif = ctx.effectif(id_ch)
        manquants = sorted(effectif - presents)
        etat = "COMPLET" if not manquants else "PARTIEL"
        donnees.couvertures.append(Couverture(jour, id_ch, "AFFECTATIONS", etat))
        donnees.couvertures.append(Couverture(
            jour, id_ch, "ABSENCES", "COMPLET" if absences_attestees else "PARTIEL"))
        if manquants:
            rapport.ajouter(r.AVERTISSEMENT, "OUVRIERS_SANS_AFFECTATION",
                            f"{jour.isoformat()} {id_ch} : {len(manquants)} ouvrier(s) sans "
                            f"affectation ({', '.join(manquants[:10])}"
                            f"{'…' if len(manquants) > 10 else ''}) — disponibilité INCONNUE",
                            "Affectations")
    if par_couple and not absences_attestees:
        rapport.ajouter(r.AVERTISSEMENT, "ABSENCES_NON_ATTESTEES",
                        "complétude des absences non attestée : les ouvriers présents resteront "
                        "INCONNU, jamais DISPONIBLE (D18)", "Absences")
    hors_perimetre = sorted({a.date_debut for a in donnees.absences
                             if not any(c.date == a.date_debut for c in donnees.couvertures)})
    if hors_perimetre:
        rapport.ajouter(r.INFORMATION, "ABSENCES_HORS_PERIMETRE",
                        "absences débutant à des dates sans affectation dans ce fichier : "
                        f"{', '.join(d.isoformat() for d in hors_perimetre)} ; enregistrées, "
                        "sans couverture déclarée pour ces dates", "Absences")


def _contradictions(rapport, donnees: DonneesJournalieres) -> None:
    """Contradictions internes au fichier, signalées pour décision. La règle de résolution
    (état INDETERMINE) s'applique au calcul de disponibilité."""
    absences = defaultdict(list)
    for a in donnees.absences:
        absences[a.id_ouvrier].append(a)
    for aff in donnees.affectations:
        liste = absences.get(aff.id_ouvrier, [])
        certaine = any(dispo.couvre_certainement(a.date_debut, a.duree, aff.date) for a in liste)
        possible = any(dispo.couvre_possiblement(a.date_debut, a.duree, aff.date) for a in liste)
        if aff.statut_presence == "PRESENT" and certaine:
            rapport.ajouter(r.DECISION, "CONTRADICTION",
                            f"{aff.id_ouvrier} le {aff.date.isoformat()} : affecté Présent mais une "
                            "absence couvre la date → INDETERMINE", "Affectations")
        elif aff.statut_presence == "ABSENT" and not certaine:
            rapport.ajouter(r.DECISION, "CONTRADICTION",
                            f"{aff.id_ouvrier} le {aff.date.isoformat()} : affecté Absent sans "
                            "absence enregistrée → INDETERMINE, aucun besoin créé", "Affectations")
        elif possible and not certaine:
            rapport.ajouter(r.DECISION, "ABSENCE_POSSIBLE_D19",
                            f"{aff.id_ouvrier} le {aff.date.isoformat()} : date suivant une absence "
                            "de plusieurs jours → INDETERMINE tant que D19 est ouverte",
                            "Affectations")
