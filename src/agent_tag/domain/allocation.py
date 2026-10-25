"""Moteur d'allocation des remplaçants — fonctions pures, sans base de données.

Règles appliquées (références du modèle validé) :
- besoins : R1 (un besoin par ouvrier ABSENT avec absence certaine, sur son poste du jour),
  R2/R3 (exigence lue dans le référentiel ; absente ou sans niveau minimum → BLOQUE) ;
- éligibilité : R4 compétence (principale ou secondaire), R5 niveau ≥ minimum, R6 DISPONIBLE,
  R7 hors chaîne cible (réaffectation interne hors V1, D1), R8 pas déjà retenu dans ce calcul,
  R9 horaire couvrant celui de l'absent ; exclusions S0 (engagé ailleurs) et R-CASCADE ;
- risque sur le poste QUITTÉ (R11, C1, C7, 3D.1 point 7) :
    restants = présents(chaîne, poste) − S0(chaîne, poste) − réservés(chaîne, poste) − 1
    BLOQUANT si restants < m_bloc (P1) ou transferts de la chaîne + 1 > p3 (P3) ;
    ELEVE si restants < m_alerte (P2) ou compétence du poste quitté critique pour la donneuse ;
- classement R14 (lexicographique, sans score) : risque, priorité de la donneuse (rang le plus
  bas d'abord), niveau le plus proche du minimum, principale avant secondaire, années (décroissant),
  identifiant ;
- allocation séquentielle (R17) : besoins critiques, puis moins de candidats, puis identifiant ;
- contrôle indépendant par flot maximal (Phase 3C, 3D.1 point 7) : mêmes prédicats stricts,
  mêmes besoins ; séquentiel ≤ maximum (I15).
Le résultat est une RECOMMANDATION : toute décision reste humaine (R16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

import networkx as nx

# --- Configuration -------------------------------------------------------------------------

RANGS_PRIORITE_PROVISOIRES = {"Moyenne": 1, "Élevée": 2, "Très élevée": 3}  # D4 ouverte


class ConfigurationInvalide(Exception):
    pass


@dataclass(frozen=True)
class Configuration:
    libelle: str
    m_bloc: int            # P1 : présents minimaux à conserver sur le poste quitté
    m_alerte: int          # P2 : en dessous, risque ELEVE
    p3: int                # P3 : transferts maximaux depuis une chaîne donneuse et par jour
    rangs_priorite: dict   # libellé de priorité → rang (le plus bas donne en premier)
    regle_cascade: bool = True    # D17
    validee: bool = False         # aucune valeur n'est validée à ce jour (D3, D4)

    def verifier(self, chaines: dict | None = None) -> None:
        for nom in ("m_bloc", "m_alerte", "p3"):
            v = getattr(self, nom)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ConfigurationInvalide(f"{nom} doit être un entier ≥ 0 (reçu {v!r})")
        if self.m_alerte < self.m_bloc:
            raise ConfigurationInvalide("m_alerte doit être ≥ m_bloc")
        rangs = list(self.rangs_priorite.values())
        if len(rangs) != len(set(rangs)):
            raise ConfigurationInvalide("deux libellés de priorité ont le même rang")
        if chaines:
            manquants = sorted({c.libelle_priorite for c in chaines.values()}
                               - set(self.rangs_priorite))
            if manquants:
                raise ConfigurationInvalide(f"priorités sans rang : {manquants}")


PROFILS_PROVISOIRES = {
    "A": Configuration("Profil A — prudent (TEST, valeurs arbitraires, NON VALIDÉ)",
                       m_bloc=1, m_alerte=2, p3=2, rangs_priorite=RANGS_PRIORITE_PROVISOIRES),
    "B": Configuration("Profil B — permissif (TEST, valeurs arbitraires, NON VALIDÉ)",
                       m_bloc=1, m_alerte=1, p3=10, rangs_priorite=RANGS_PRIORITE_PROVISOIRES),
}


# --- Instantané des données (lu une seule fois, cohérent) -----------------------------------

@dataclass(frozen=True)
class Ouvrier:
    id: str
    nom: str
    chaine_origine: str
    poste_principal: str


@dataclass(frozen=True)
class Jour:
    """État de l'ouvrier à la date (incrément 2) et son affectation du jour, si elle existe."""
    etat: str
    cause: str
    besoin_creable: bool
    chaine: str | None = None
    poste: str | None = None
    heure_debut: time | None = None
    heure_fin: time | None = None
    id_affectation: int | None = None
    id_absence: int | None = None      # absence certaine justifiant le besoin, le cas échéant


@dataclass(frozen=True)
class Detenue:
    type_competence: str   # PRINCIPALE / SECONDAIRE
    code_niveau: str
    rang_niveau: int
    annees: int
    certification: bool    # affichée seulement (R10)


@dataclass(frozen=True)
class Exigence:
    competence: str
    code_niveau_min: str | None
    rang_min: int | None


@dataclass(frozen=True)
class Poste:
    code: str
    libelle: str
    competence: str | None
    source: str | None
    validee: bool


@dataclass(frozen=True)
class Chaine:
    id: str
    libelle_priorite: str
    critiques: frozenset


@dataclass
class Instantane:
    date: date
    ouvriers: dict          # id → Ouvrier
    jour: dict              # id → Jour
    competences: dict       # (id, code compétence) → Detenue
    exigences: dict         # (chaîne, code poste) → Exigence
    postes: dict            # code → Poste
    chaines: dict           # id → Chaine
    libelles_competence: dict = field(default_factory=dict)
    niveaux: dict = field(default_factory=dict)          # code → libellé
    engages: frozenset = frozenset()          # S0 : ouvriers déjà engagés ou réservés ailleurs
    chaines_interdites: frozenset = frozenset()  # R-CASCADE : cibles d'autres runs ouverts
    lecture: str | None = None               # instant de lecture (traçabilité)
    exclusions: dict = field(default_factory=dict)  # absent → ouvriers refusés pour ce besoin (D8)
    besoins_exclus: frozenset = frozenset()  # absents dont le besoin est déjà tranché


# --- Résultats -----------------------------------------------------------------------------

OK, ECHEC, NON_EVALUE = "OK", "ECHEC", "NON_EVALUE"
FAIBLE, ELEVE, BLOQUANT = "FAIBLE", "ELEVE", "BLOQUANT"
ORDRE_CONTROLES = ("R4", "R5", "R6", "R7", "R9", "EXCLU", "R8", "S0", "CASCADE", "P3", "P1")

LIBELLE_CONTROLE = {
    "R4": "compétence requise non détenue",
    "R5": "niveau inférieur au minimum requis",
    "R6": "non disponible à la date",
    "R7": "appartient à la chaîne cible (réaffectation interne hors V1, D1)",
    "R9": "horaire incompatible",
    "EXCLU": "refusé par le responsable pour ce besoin (D8)",
    "R8": "déjà proposé pour un autre besoin dans ce calcul",
    "S0": "déjà engagé ou réservé ailleurs",
    "CASCADE": "travaille sur une chaîne cible d'un autre calcul ouvert (R-CASCADE)",
    "P3": "plafond de transferts de la chaîne donneuse atteint (P3)",
    "P1": "le poste quitté passerait sous le minimum à conserver (P1)",
}


@dataclass
class Evaluation:
    id_ouvrier: str
    nom: str
    chaine_donneuse: str | None
    poste_quitte: str | None
    type_competence: str | None
    code_niveau: str | None
    annees: int | None
    certification: bool | None
    disponibilite: str
    controles: dict
    eligible: bool = False
    premier_echec: str | None = None
    presents_poste: int | None = None
    s0_poste: int | None = None
    reserves_poste: int | None = None
    restants: int | None = None
    transferts_chaine: int | None = None
    risque: str | None = None
    causes_risque: list = field(default_factory=list)
    correspondance_deduite: bool = False
    rang: int | None = None
    ex_aequo: bool = False
    explication: str = ""


PROPOSITION, AUCUN_CANDIDAT, BLOQUE = "PROPOSITION", "AUCUN_CANDIDAT", "BLOQUE"
DEJA_TRAITE = "DEJA_TRAITE"   # besoin déjà tranché par une décision : non recalculé


@dataclass
class Besoin:
    id_ouvrier_absent: str
    nom_absent: str
    chaine: str
    poste: str
    competence: str | None
    code_niveau_min: str | None
    rang_min: int | None
    critique: bool
    statut: str | None = None
    cause: str = ""
    qualite: str | None = None             # RISQUE_FAIBLE / AVEC_ALERTE pour une proposition
    rang_traitement: int | None = None
    nb_eligibles_initial: int | None = None
    proposition: Evaluation | None = None
    evaluations: list = field(default_factory=list)


@dataclass
class Ecart:
    """Ouvrier de la chaîne cible absent ou au statut incertain, sans besoin créé."""
    id_ouvrier: str
    etat: str
    cause: str


@dataclass
class Resultat:
    date: date
    chaine_cible: str
    configuration: Configuration
    besoins: list
    ecarts: list
    couverture_sequentielle: int
    couverture_maximale: int
    besoins_consideres: int
    combinaison_maximale: dict      # id absent → id ouvrier (une combinaison parmi d'autres)
    alerte_combinaison: bool
    lecture: str | None = None

    @property
    def utilisable_en_production(self) -> bool:
        """Faux tant que les paramètres (D3, D4) ne sont pas validés."""
        return self.configuration.validee


# --- Besoins -------------------------------------------------------------------------------

def creer_besoins(inst: Instantane, cible: str) -> tuple[list, list]:
    if cible not in inst.chaines:
        raise ValueError(f"chaîne cible inconnue : {cible}")
    critiques = inst.chaines[cible].critiques
    besoins, ecarts = [], []
    for id_o in sorted(inst.ouvriers):
        j = inst.jour.get(id_o)
        o = inst.ouvriers[id_o]
        chaine_jour = j.chaine if j and j.chaine else o.chaine_origine
        if chaine_jour != cible:
            continue
        if j is None or not j.besoin_creable:
            if j is not None and j.etat in ("ABSENT", "INDETERMINE", "INCONNU"):
                ecarts.append(Ecart(id_o, j.etat, j.cause))
            continue
        exigence = inst.exigences.get((cible, j.poste))
        b = Besoin(id_o, o.nom, cible, j.poste,
                   exigence.competence if exigence else None,
                   exigence.code_niveau_min if exigence else None,
                   exigence.rang_min if exigence else None,
                   critique=bool(exigence and exigence.competence in critiques))
        if exigence is None:
            b.statut, b.cause = BLOQUE, "EXIGENCE_ABSENTE (R3) : aucune exigence pour ce poste"
        elif exigence.code_niveau_min is None:
            b.statut, b.cause = BLOQUE, "NIVEAU_MIN_ABSENT (R3) : niveau minimum non défini"
        besoins.append(b)
    return besoins, ecarts


# --- Évaluation d'un candidat ---------------------------------------------------------------

def _comptages(inst: Instantane, reserves: dict):
    presents, s0_poste, s0_chaine, res_poste, res_chaine = {}, {}, {}, {}, {}
    for id_o, j in inst.jour.items():
        if j.etat == "DISPONIBLE" and j.chaine and j.poste:
            cle = (j.chaine, j.poste)
            presents[cle] = presents.get(cle, 0) + 1
            if id_o in inst.engages:
                s0_poste[cle] = s0_poste.get(cle, 0) + 1
                s0_chaine[j.chaine] = s0_chaine.get(j.chaine, 0) + 1
    for id_o in reserves:
        j = inst.jour[id_o]
        res_poste[(j.chaine, j.poste)] = res_poste.get((j.chaine, j.poste), 0) + 1
        res_chaine[j.chaine] = res_chaine.get(j.chaine, 0) + 1
    return presents, s0_poste, s0_chaine, res_poste, res_chaine


def evaluer_candidats(inst: Instantane, cfg: Configuration, besoin: Besoin,
                      reserves: dict | None = None) -> list[Evaluation]:
    """Évalue tous les détenteurs de la compétence requise (sauf l'absent).
    `reserves` : ouvrier → besoin pour lequel il est déjà proposé dans ce calcul."""
    reserves = reserves or {}
    presents, s0_poste, s0_chaine, res_poste, res_chaine = _comptages(inst, reserves)
    absent = inst.jour[besoin.id_ouvrier_absent]
    evaluations = []
    for (id_o, comp), det in sorted(inst.competences.items()):
        if comp != besoin.competence or id_o == besoin.id_ouvrier_absent:
            continue
        o = inst.ouvriers[id_o]
        j = inst.jour.get(id_o) or Jour("INCONNU", "AFFECTATION_INCONNUE", False)
        dispo = j.etat == "DISPONIBLE"
        chaine_jour = j.chaine or o.chaine_origine
        c = {
            "R4": OK,
            "R5": OK if det.rang_niveau >= besoin.rang_min else ECHEC,
            "R6": OK if dispo else ECHEC,
            "R7": ECHEC if chaine_jour == besoin.chaine else OK,
            "R9": NON_EVALUE,
            "EXCLU": ECHEC if id_o in inst.exclusions.get(besoin.id_ouvrier_absent, ())
            else OK,
            "R8": ECHEC if id_o in reserves else OK,
            "S0": ECHEC if id_o in inst.engages else OK,
            "CASCADE": ECHEC if (cfg.regle_cascade and chaine_jour in inst.chaines_interdites)
            else OK,
            "P3": NON_EVALUE,
            "P1": NON_EVALUE,
        }
        if dispo and j.heure_debut and absent.heure_debut:
            c["R9"] = OK if (j.heure_debut <= absent.heure_debut
                             and j.heure_fin >= absent.heure_fin) else ECHEC
        e = Evaluation(id_o, o.nom, j.chaine, j.poste, det.type_competence, det.code_niveau,
                       det.annees, det.certification, f"{j.etat} ({j.cause})", c)

        if dispo and j.chaine and j.poste:
            cle = (j.chaine, j.poste)
            e.presents_poste = presents.get(cle, 0)
            e.s0_poste = s0_poste.get(cle, 0)
            e.reserves_poste = res_poste.get(cle, 0)
            e.restants = e.presents_poste - e.s0_poste - e.reserves_poste - 1
            e.transferts_chaine = s0_chaine.get(j.chaine, 0) + res_chaine.get(j.chaine, 0)
            c["P1"] = ECHEC if e.restants < cfg.m_bloc else OK
            c["P3"] = ECHEC if e.transferts_chaine + 1 > cfg.p3 else OK
            causes = []
            if c["P1"] == ECHEC:
                causes.append("P1")
            if c["P3"] == ECHEC:
                causes.append("P3")
            if e.restants < cfg.m_alerte:
                causes.append("P2")
            poste_q = inst.postes.get(j.poste)
            comp_q = poste_q.competence if poste_q else None
            if comp_q is None:
                causes.append("CRITIQUE_INCONNUE")
            elif comp_q in inst.chaines[j.chaine].critiques:
                causes.append("CRITIQUE")
            e.correspondance_deduite = bool(poste_q and poste_q.source == "DEDUITE")
            e.causes_risque = causes
            e.risque = (BLOQUANT if {"P1", "P3"} & set(causes)
                        else ELEVE if causes else FAIBLE)

        echecs = [k for k in ORDRE_CONTROLES if c[k] == ECHEC]
        if c["R6"] == OK and c["R9"] == NON_EVALUE:
            echecs.append("R9")   # horaire inconnu : non confirmé, donc refusé
        e.premier_echec = echecs[0] if echecs else None
        e.eligible = not echecs
        evaluations.append(e)

    _classer(inst, cfg, besoin, evaluations)
    for e in evaluations:
        e.explication = _expliquer(inst, cfg, besoin, e)
    return evaluations


def cle_classement(inst: Instantane, cfg: Configuration, besoin: Besoin, e: Evaluation):
    """Critères R14 dans l'ordre : risque, priorité donneuse, adéquation du niveau, type,
    années (décroissant), identifiant."""
    det = inst.competences[(e.id_ouvrier, besoin.competence)]
    return (
        0 if e.risque == FAIBLE else 1,
        cfg.rangs_priorite[inst.chaines[e.chaine_donneuse].libelle_priorite],
        det.rang_niveau - besoin.rang_min,
        0 if det.type_competence == "PRINCIPALE" else 1,
        -det.annees,
        e.id_ouvrier,
    )


def _classer(inst, cfg, besoin, evaluations) -> None:
    eligibles = sorted((e for e in evaluations if e.eligible),
                       key=lambda e: cle_classement(inst, cfg, besoin, e))
    cles = [cle_classement(inst, cfg, besoin, e)[:5] for e in eligibles]
    for i, e in enumerate(eligibles, 1):
        e.rang = i
        e.ex_aequo = cles.count(cles[i - 1]) > 1
    evaluations.sort(key=lambda e: (e.rang is None, e.rang or 0, e.id_ouvrier))


def _expliquer(inst, cfg, besoin, e: Evaluation) -> str:
    lib = inst.libelles_competence.get(besoin.competence, besoin.competence)
    niveau = inst.niveaux.get(e.code_niveau, e.code_niveau)
    niveau_min = inst.niveaux.get(besoin.code_niveau_min, besoin.code_niveau_min)
    if not e.eligible:
        detail = LIBELLE_CONTROLE[e.premier_echec]
        if e.premier_echec == "R5":
            detail += f" ({niveau} < {niveau_min})"
        elif e.premier_echec == "R6":
            detail += f" : {e.disponibilite}"
        elif e.premier_echec == "P1":
            detail += f" ({e.restants} restant(s) < {cfg.m_bloc})"
        elif e.premier_echec == "P3":
            detail += f" ({e.transferts_chaine} transfert(s) déjà retenu(s), plafond {cfg.p3})"
        return f"rejeté — {e.premier_echec} : {detail}"
    prio = inst.chaines[e.chaine_donneuse].libelle_priorite
    ecart = inst.competences[(e.id_ouvrier, besoin.competence)].rang_niveau - besoin.rang_min
    adequation = "= minimum requis" if ecart == 0 else f"au-dessus du minimum ({niveau_min})"
    texte = (f"rang {e.rang}{' (ex æquo jusqu’au critère 5)' if e.ex_aequo else ''} — "
             f"{lib} ({e.type_competence.lower()}), {niveau} {adequation}, {e.annees} an(s) ; "
             f"donneuse {e.chaine_donneuse} (priorité {prio}) ; quitte "
             f"{inst.postes[e.poste_quitte].libelle if e.poste_quitte in inst.postes else e.poste_quitte} : "
             f"{e.restants} restant(s), risque {e.risque}")
    if e.causes_risque:
        texte += f" [{', '.join(e.causes_risque)}]"
    if e.correspondance_deduite:
        texte += " ; criticité du poste quitté fondée sur une correspondance déduite (D7)"
    return texte


# --- Allocation séquentielle et contrôle par flot maximal -----------------------------------

def allouer(inst: Instantane, cfg: Configuration, cible: str) -> Resultat:
    cfg.verifier(inst.chaines)
    besoins, ecarts = creer_besoins(inst, cible)
    for b in besoins:
        if b.id_ouvrier_absent in inst.besoins_exclus:
            b.statut, b.cause = DEJA_TRAITE, "besoin déjà tranché par une décision"
    traitables = [b for b in besoins if b.statut not in (BLOQUE, DEJA_TRAITE)]

    for b in traitables:
        b.nb_eligibles_initial = sum(e.eligible for e in evaluer_candidats(inst, cfg, b))
    ordre = sorted(traitables, key=lambda b: (0 if b.critique else 1, b.nb_eligibles_initial,
                                              b.id_ouvrier_absent))
    reserves: dict[str, str] = {}
    for rang, b in enumerate(ordre, 1):
        b.rang_traitement = rang
        b.evaluations = evaluer_candidats(inst, cfg, b, reserves)
        retenus = [e for e in b.evaluations if e.eligible]
        if retenus:
            b.proposition = retenus[0]
            b.statut = PROPOSITION
            b.qualite = "RISQUE_FAIBLE" if retenus[0].risque == FAIBLE else "AVEC_ALERTE"
            reserves[retenus[0].id_ouvrier] = b.id_ouvrier_absent
        else:
            b.statut = AUCUN_CANDIDAT
            b.cause = _cause_sans_candidat(b)

    seq = sum(1 for b in traitables if b.statut == PROPOSITION)
    maximum, combinaison = couverture_maximale(inst, cfg, traitables)
    if seq > maximum:   # I15 : impossible si les prédicats sont identiques
        raise AssertionError(f"I15 violé : séquentiel {seq} > maximum {maximum}")
    return Resultat(inst.date, cible, cfg, besoins, ecarts, seq, maximum, len(traitables),
                    combinaison, seq < maximum, inst.lecture)


def _cause_sans_candidat(b: Besoin) -> str:
    if not b.evaluations:
        return "AUCUN_DETENTEUR : aucun autre ouvrier ne détient la compétence requise"
    compte = {}
    for e in b.evaluations:
        compte[e.premier_echec] = compte.get(e.premier_echec, 0) + 1
    detail = ", ".join(f"{k} ×{n}" for k, n in sorted(compte.items(),
                                                      key=lambda kv: ORDRE_CONTROLES.index(kv[0])))
    epuise = " ; vivier épuisé par les propositions précédentes" if "R8" in compte else ""
    return f"aucun candidat conforme ({len(b.evaluations)} détenteur(s) écarté(s) : {detail}){epuise}"


def couverture_maximale(inst: Instantane, cfg: Configuration, besoins: list) -> tuple[int, dict]:
    """Flot maximal sur le réseau : source → besoin (1) → ouvrier strictement éligible (hors R8)
    → ouvrier (1) → (chaîne, poste) [présents − S0 − m_bloc] → chaîne [p3 − S0] → puits."""
    g = nx.DiGraph()
    presents, s0_poste, s0_chaine, _, _ = _comptages(inst, {})
    stricts = ("R4", "R5", "R6", "R7", "R9", "EXCLU", "S0", "CASCADE")
    for b in besoins:
        g.add_edge("S", ("B", b.id_ouvrier_absent), capacity=1)
        for e in evaluer_candidats(inst, cfg, b):
            if all(e.controles[k] == OK for k in stricts):
                j = inst.jour[e.id_ouvrier]
                g.add_edge(("B", b.id_ouvrier_absent), ("W", e.id_ouvrier), capacity=1)
                g.add_edge(("W", e.id_ouvrier), ("P", j.chaine, j.poste), capacity=1)
                cap_p = max(0, presents.get((j.chaine, j.poste), 0)
                            - s0_poste.get((j.chaine, j.poste), 0) - cfg.m_bloc)
                g.add_edge(("P", j.chaine, j.poste), ("C", j.chaine), capacity=cap_p)
                g.add_edge(("C", j.chaine), "T",
                           capacity=max(0, cfg.p3 - s0_chaine.get(j.chaine, 0)))
    if "T" not in g:
        return 0, {}
    valeur, flot = nx.maximum_flow(g, "S", "T")
    combinaison = {}
    for b in besoins:
        for voisin, f in flot.get(("B", b.id_ouvrier_absent), {}).items():
            if f == 1:
                combinaison[b.id_ouvrier_absent] = voisin[1]
    return int(valeur), combinaison
