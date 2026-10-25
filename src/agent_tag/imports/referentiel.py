"""Contrôle du référentiel lu dans le classeur, sans accès à la base.

Principes :
- l'identité d'un ouvrier est son ID_Ouvrier, jamais son nom ;
- aucune valeur manquante n'est complétée ; les manques métier sont signalés (DECISION) ;
- une seule anomalie BLOQUANTE suffit à rejeter tout l'import (tout ou rien).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import time

from agent_tag.imports import rapport as r
from agent_tag.imports.classeur import Feuille

TYPES_COMPETENCE = {"Principale": "PRINCIPALE", "Secondaire": "SECONDAIRE"}
CERTIFICATION = {"Oui": True, "Non": False}
_HORAIRE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def code_technique(libelle: str) -> str:
    """Code stable en ASCII majuscule (choix technique T1), ex. 'Contrôle qualité' → CONTROLE_QUALITE."""
    sans_accent = unicodedata.normalize("NFKD", libelle).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", sans_accent.upper()).strip("_")


# --- Données validées -----------------------------------------------------------------

@dataclass
class Chaine:
    id_chaine: str
    produit: str
    effectif_necessaire: int
    effectif_planifie: int
    libelle_priorite: str
    capacite_journaliere: int


@dataclass
class Poste:
    code: str
    libelle: str
    code_competence: str | None = None
    source: str | None = None
    validee: bool = False


@dataclass
class Ouvrier:
    id_ouvrier: str
    nom: str
    id_chaine: str
    poste_libelle: str
    heure_debut: time
    heure_fin: time
    statut_source: str | None
    experience_poste: int


@dataclass
class CompetenceDetenue:
    id_ouvrier: str
    code_competence: str
    type_competence: str
    annees: int
    code_niveau: str
    certification: bool


@dataclass
class Exigence:
    id_chaine: str
    poste_libelle: str
    code_competence: str
    code_niveau_min: str | None
    nombre_requis: int | None


@dataclass
class Referentiel:
    competences: dict[str, str] = field(default_factory=dict)       # code -> libellé
    postes: dict[str, Poste] = field(default_factory=dict)          # libellé -> Poste
    chaines: dict[str, Chaine] = field(default_factory=dict)
    critiques: list[tuple[str, str]] = field(default_factory=list)  # (chaîne, code compétence)
    ouvriers: dict[str, Ouvrier] = field(default_factory=dict)
    detenues: list[CompetenceDetenue] = field(default_factory=list)
    exigences: list[Exigence] = field(default_factory=list)


# --- Lecture de valeurs ---------------------------------------------------------------

class _Lecteur:
    def __init__(self, rapport: r.Rapport, feuille: str):
        self.rapport, self.feuille = rapport, feuille

    def texte(self, ligne, col, obligatoire=True) -> str | None:
        v = ligne.valeurs.get(col)
        if v is None or (isinstance(v, str) and not v.strip()):
            if obligatoire:
                self.rapport.ajouter(r.BLOQUANTE, "VALEUR_OBLIGATOIRE", "valeur absente",
                                     self.feuille, ligne.numero, col)
            return None
        return unicodedata.normalize("NFC", str(v).strip())

    def entier(self, ligne, col, minimum=0, obligatoire=True) -> int | None:
        v = ligne.valeurs.get(col)
        if v is None or (isinstance(v, str) and not v.strip()):
            if obligatoire:
                self.rapport.ajouter(r.BLOQUANTE, "VALEUR_OBLIGATOIRE", "valeur absente",
                                     self.feuille, ligne.numero, col)
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) != int(v):
            self.rapport.ajouter(r.BLOQUANTE, "VALEUR_INVALIDE", f"entier attendu : {v!r}",
                                 self.feuille, ligne.numero, col)
            return None
        if int(v) < minimum:
            self.rapport.ajouter(r.BLOQUANTE, "VALEUR_INVALIDE",
                                 f"valeur {int(v)} inférieure au minimum {minimum}",
                                 self.feuille, ligne.numero, col)
            return None
        return int(v)

    def bloquer(self, code, message, ligne, col=None):
        self.rapport.ajouter(r.BLOQUANTE, code, message, self.feuille, ligne.numero, col)


# --- Contrôle -------------------------------------------------------------------------

def controler(feuilles: dict[str, Feuille], niveaux: dict[str, str],
              rapport: r.Rapport) -> Referentiel:
    """`niveaux` : libellé validé -> code (lu dans skill_level)."""
    ref = Referentiel()
    if any(n not in feuilles for n in ("Chaines", "Ouvriers", "Competences", "Besoins_Postes")):
        return ref  # structure déjà signalée comme bloquante

    _chaines(feuilles["Chaines"], ref, rapport)
    _catalogue_competences(feuilles, ref, rapport)
    _ouvriers(feuilles["Ouvriers"], ref, rapport)
    _competences_detenues(feuilles["Competences"], ref, niveaux, rapport)
    _exigences(feuilles["Besoins_Postes"], ref, niveaux, rapport)
    _critiques(feuilles["Chaines"], ref, rapport)
    _postes(ref, rapport)
    _coherences(ref, rapport)
    return ref


def _chaines(f: Feuille, ref: Referentiel, rapport: r.Rapport) -> None:
    lec = _Lecteur(rapport, f.nom)
    produits: dict[str, str] = {}
    for ligne in f.lignes:
        id_ch = lec.texte(ligne, "ID_Chaîne")
        produit = lec.texte(ligne, "Produit")
        nec = lec.entier(ligne, "Effectif_nécessaire")
        plan = lec.entier(ligne, "Effectif_planifié")
        prio = lec.texte(ligne, "Priorité")
        cap = lec.entier(ligne, "Capacité_journalière_unités")
        if id_ch is None:
            continue
        if id_ch in ref.chaines:
            lec.bloquer("IDENTIFIANT_DUPLIQUE", f"chaîne {id_ch} déjà déclarée", ligne, "ID_Chaîne")
            continue
        if produit is not None and produit in produits:
            lec.bloquer("IDENTIFIANT_DUPLIQUE",
                        f"produit {produit} déjà porté par {produits[produit]}", ligne, "Produit")
            continue
        if None in (produit, nec, plan, prio, cap):
            continue
        produits[produit] = id_ch
        ref.chaines[id_ch] = Chaine(id_ch, produit, nec, plan, prio, cap)


def _catalogue_competences(feuilles, ref: Referentiel, rapport: r.Rapport) -> None:
    """Compétences = celles détenues (Competences) ∪ celles requises (Besoins_Postes)."""
    libelles = set()
    for f, col in ((feuilles["Competences"], "Compétence"),
                   (feuilles["Besoins_Postes"], "Compétence_requise")):
        for ligne in f.lignes:
            v = ligne.valeurs.get(col)
            if isinstance(v, str) and v.strip():
                libelles.add(unicodedata.normalize("NFC", v.strip()))
    par_code = defaultdict(list)
    for lib in sorted(libelles):
        par_code[code_technique(lib)].append(lib)
    for code, libs in par_code.items():
        if not code or len(libs) > 1:
            rapport.ajouter(r.BLOQUANTE, "CODE_EN_COLLISION",
                            f"libellés de compétence indiscernables : {libs}", "Competences")
            continue
        ref.competences[code] = libs[0]


def _code_competence(ref: Referentiel, libelle: str) -> str | None:
    code = code_technique(libelle)
    return code if ref.competences.get(code) == libelle else None


def _ouvriers(f: Feuille, ref: Referentiel, rapport: r.Rapport) -> None:
    lec = _Lecteur(rapport, f.nom)
    for ligne in f.lignes:
        id_o = lec.texte(ligne, "ID_Ouvrier")
        nom = lec.texte(ligne, "Nom")
        id_ch = lec.texte(ligne, "Chaîne_actuelle")
        produit = lec.texte(ligne, "Produit")
        poste = lec.texte(ligne, "Poste_principal")
        statut = lec.texte(ligne, "Statut", obligatoire=False)
        exp = lec.entier(ligne, "Expérience_poste_ans")
        horaire = lec.texte(ligne, "Horaire")
        if id_o is None:
            continue
        if id_o in ref.ouvriers:
            lec.bloquer("IDENTIFIANT_DUPLIQUE", f"ouvrier {id_o} déjà déclaré", ligne, "ID_Ouvrier")
            continue
        ok = None not in (nom, id_ch, produit, poste, exp, horaire)
        if id_ch is not None and id_ch not in ref.chaines:
            lec.bloquer("REFERENCE_ORPHELINE", f"chaîne {id_ch} inconnue", ligne, "Chaîne_actuelle")
            ok = False
        elif id_ch is not None and produit is not None and ref.chaines[id_ch].produit != produit:
            lec.bloquer("INCOHERENCE",
                        f"produit {produit} différent de celui de {id_ch} "
                        f"({ref.chaines[id_ch].produit})", ligne, "Produit")
            ok = False
        debut = fin = None
        if horaire is not None:
            m = _HORAIRE.match(horaire)
            try:
                if not m:
                    raise ValueError
                debut = time(int(m.group(1)), int(m.group(2)))
                fin = time(int(m.group(3)), int(m.group(4)))
                if fin <= debut:
                    raise ValueError
            except ValueError:
                lec.bloquer("VALEUR_INVALIDE", f"horaire invalide : {horaire!r} (HH:MM-HH:MM)",
                            ligne, "Horaire")
                ok = False
        if ok:
            ref.ouvriers[id_o] = Ouvrier(id_o, nom, id_ch, poste, debut, fin, statut, exp)


def _competences_detenues(f: Feuille, ref: Referentiel, niveaux, rapport: r.Rapport) -> None:
    lec = _Lecteur(rapport, f.nom)
    vues: set[tuple[str, str]] = set()
    ids_feuille_ouvriers = {i for i in ref.ouvriers}
    for ligne in f.lignes:
        id_o = lec.texte(ligne, "ID_Ouvrier")
        nom = lec.texte(ligne, "Nom")
        lib = lec.texte(ligne, "Compétence")
        typ = lec.texte(ligne, "Type_compétence")
        annees = lec.entier(ligne, "Années_expérience", minimum=1)
        niveau = lec.texte(ligne, "Niveau")
        certif = lec.texte(ligne, "Certification")
        ok = None not in (id_o, nom, lib, typ, annees, niveau, certif)

        if id_o is not None and id_o not in ids_feuille_ouvriers:
            lec.bloquer("REFERENCE_ORPHELINE", f"ouvrier {id_o} inconnu ou rejeté", ligne,
                        "ID_Ouvrier")
            ok = False
        elif id_o is not None and nom is not None and ref.ouvriers[id_o].nom != nom:
            lec.bloquer("INCOHERENCE",
                        f"nom {nom!r} différent de celui de {id_o} ({ref.ouvriers[id_o].nom!r})",
                        ligne, "Nom")
            ok = False
        if typ is not None and typ not in TYPES_COMPETENCE:
            lec.bloquer("VALEUR_INVALIDE", f"type {typ!r} (attendu : Principale, Secondaire)",
                        ligne, "Type_compétence")
            ok = False
        if niveau is not None and niveau not in niveaux:
            lec.bloquer("NIVEAU_INVALIDE",
                        f"niveau {niveau!r} hors nomenclature ({', '.join(niveaux)})",
                        ligne, "Niveau")
            ok = False
        if certif is not None and certif not in CERTIFICATION:
            lec.bloquer("VALEUR_INVALIDE", f"certification {certif!r} (attendu : Oui, Non)",
                        ligne, "Certification")
            ok = False
        code = _code_competence(ref, lib) if lib is not None else None
        if lib is not None and code is None:
            ok = False  # collision déjà signalée
        if ok and (id_o, code) in vues:
            lec.bloquer("IDENTIFIANT_DUPLIQUE", f"compétence {lib} déjà déclarée pour {id_o}",
                        ligne, "Compétence")
            ok = False
        if ok:
            vues.add((id_o, code))
            ref.detenues.append(CompetenceDetenue(
                id_o, code, TYPES_COMPETENCE[typ], annees, niveaux[niveau], CERTIFICATION[certif]))

    principales = Counter(d.id_ouvrier for d in ref.detenues if d.type_competence == "PRINCIPALE")
    for id_o in ref.ouvriers:
        if principales[id_o] != 1:
            rapport.ajouter(r.BLOQUANTE, "NB_PRINCIPALES",
                            f"ouvrier {id_o} : {principales[id_o]} compétence(s) principale(s), "
                            "exactement 1 attendue", "Competences")


def _exigences(f: Feuille, ref: Referentiel, niveaux, rapport: r.Rapport) -> None:
    lec = _Lecteur(rapport, f.nom)
    vues = set()
    for ligne in f.lignes:
        id_ch = lec.texte(ligne, "Chaîne")
        produit = lec.texte(ligne, "Produit")
        poste = lec.texte(ligne, "Poste")
        nombre = lec.entier(ligne, "Nombre_requis", obligatoire=False)
        lib = lec.texte(ligne, "Compétence_requise")
        niveau = lec.texte(ligne, "Niveau_minimum", obligatoire=False)
        ok = None not in (id_ch, produit, poste, lib)
        if id_ch is not None and id_ch not in ref.chaines:
            lec.bloquer("REFERENCE_ORPHELINE", f"chaîne {id_ch} inconnue", ligne, "Chaîne")
            ok = False
        elif id_ch is not None and produit is not None and ref.chaines[id_ch].produit != produit:
            lec.bloquer("INCOHERENCE", f"produit {produit} différent de celui de {id_ch}",
                        ligne, "Produit")
            ok = False
        if niveau is not None and niveau not in niveaux:
            lec.bloquer("NIVEAU_INVALIDE",
                        f"niveau minimum {niveau!r} hors nomenclature ({', '.join(niveaux)})",
                        ligne, "Niveau_minimum")
            ok = False
        code = _code_competence(ref, lib) if lib is not None else None
        if lib is not None and code is None:
            ok = False
        if ok and (id_ch, poste) in vues:
            lec.bloquer("IDENTIFIANT_DUPLIQUE", f"exigence ({id_ch}, {poste}) déjà déclarée",
                        ligne, "Poste")
            ok = False
        if not ok:
            continue
        vues.add((id_ch, poste))
        if niveau is None:
            rapport.ajouter(r.DECISION, "NIVEAU_MIN_ABSENT",
                            f"({id_ch}, {poste}) : niveau minimum non défini — besoins Bloqués (R3)",
                            f.nom, ligne.numero, "Niveau_minimum")
        if nombre is None:
            rapport.ajouter(r.INFORMATION, "NOMBRE_REQUIS_ABSENT",
                            f"({id_ch}, {poste}) : nombre requis non renseigné (informatif)",
                            f.nom, ligne.numero, "Nombre_requis")
        ref.exigences.append(Exigence(id_ch, poste, code,
                                      niveaux[niveau] if niveau else None, nombre))


def _critiques(f: Feuille, ref: Referentiel, rapport: r.Rapport) -> None:
    for ligne in f.lignes:
        id_ch = ligne.valeurs.get("ID_Chaîne")
        id_ch = str(id_ch).strip() if id_ch is not None else None
        if id_ch not in ref.chaines:
            continue
        brut = ligne.valeurs.get("Compétences_critiques")
        if brut is None or not str(brut).strip():
            rapport.ajouter(r.AVERTISSEMENT, "CRITIQUES_ABSENTES",
                            f"{id_ch} : aucune compétence critique déclarée", f.nom, ligne.numero,
                            "Compétences_critiques")
            continue
        vues = set()
        for lib in (unicodedata.normalize("NFC", x.strip()) for x in str(brut).split(";")):
            if not lib:
                continue
            code = _code_competence(ref, lib)
            if code is None:
                rapport.ajouter(r.BLOQUANTE, "REFERENCE_ORPHELINE",
                                f"compétence critique {lib!r} inconnue", f.nom, ligne.numero,
                                "Compétences_critiques")
            elif code in vues:
                rapport.ajouter(r.AVERTISSEMENT, "CRITIQUE_REPETEE",
                                f"{id_ch} : {lib} citée plusieurs fois", f.nom, ligne.numero)
            else:
                vues.add(code)
                ref.critiques.append((id_ch, code))


def _postes(ref: Referentiel, rapport: r.Rapport) -> None:
    """Postes et correspondance poste → compétence. Aucune correspondance n'est inventée."""
    libelles = {o.poste_libelle for o in ref.ouvriers.values()} | {e.poste_libelle
                                                                    for e in ref.exigences}
    par_code = defaultdict(list)
    for lib in sorted(libelles):
        par_code[code_technique(lib)].append(lib)
    for code, libs in par_code.items():
        if not code or len(libs) > 1:
            rapport.ajouter(r.BLOQUANTE, "CODE_EN_COLLISION",
                            f"libellés de poste indiscernables : {libs}")
            continue
        ref.postes[libs[0]] = Poste(code, libs[0])

    principale = {d.id_ouvrier: d.code_competence for d in ref.detenues
                  if d.type_competence == "PRINCIPALE"}
    for lib, poste in ref.postes.items():
        requises = {e.code_competence for e in ref.exigences if e.poste_libelle == lib}
        if len(requises) == 1:
            poste.code_competence, poste.source, poste.validee = requises.pop(), "BESOINS_POSTES", True
            continue
        if len(requises) > 1:
            rapport.ajouter(r.DECISION, "CORRESPONDANCE_INCOHERENTE",
                            f"poste {lib} : compétences requises différentes selon les chaînes "
                            f"({sorted(requises)}) — correspondance laissée vide")
            continue
        observees = {principale.get(o.id_ouvrier) for o in ref.ouvriers.values()
                     if o.poste_libelle == lib}
        observees.discard(None)
        if len(observees) == 1:
            code = observees.pop()
            poste.code_competence, poste.source, poste.validee = code, "DEDUITE", False
            rapport.ajouter(r.DECISION, "CORRESPONDANCE_DEDUITE",
                            f"poste {lib} absent de Besoins_Postes : compétence "
                            f"{ref.competences[code]!r} déduite des compétences principales "
                            "de ses titulaires, non validée (D7)")
        else:
            rapport.ajouter(r.DECISION, "CORRESPONDANCE_INCONNUE",
                            f"poste {lib} : aucune compétence associée déterminable")


def _coherences(ref: Referentiel, rapport: r.Rapport) -> None:
    principale = {d.id_ouvrier: d for d in ref.detenues if d.type_competence == "PRINCIPALE"}
    for o in ref.ouvriers.values():
        poste = ref.postes.get(o.poste_libelle)
        p = principale.get(o.id_ouvrier)
        if poste and poste.code_competence and p and p.code_competence != poste.code_competence:
            rapport.ajouter(r.BLOQUANTE, "INCOHERENCE",
                            f"ouvrier {o.id_ouvrier} : compétence principale "
                            f"{ref.competences[p.code_competence]!r} différente de celle du poste "
                            f"{o.poste_libelle} ({ref.competences[poste.code_competence]!r})",
                            "Competences")
        if p and p.annees != o.experience_poste:
            rapport.ajouter(r.AVERTISSEMENT, "EXPERIENCE_POSTE_DIVERGENTE",
                            f"ouvrier {o.id_ouvrier} : Expérience_poste_ans {o.experience_poste} "
                            f"≠ années de la compétence principale {p.annees} "
                            "(seule la seconde est conservée)", "Ouvriers")

    exigees = {(e.id_chaine, e.poste_libelle) for e in ref.exigences}
    tenus = sorted({(o.id_chaine, o.poste_libelle) for o in ref.ouvriers.values()})
    for id_ch, poste in tenus:
        if (id_ch, poste) not in exigees:
            rapport.ajouter(r.DECISION, "EXIGENCE_ABSENTE",
                            f"({id_ch}, {poste}) : aucune exigence dans Besoins_Postes — "
                            "les besoins de ce poste seront Bloqués (R3)", "Besoins_Postes")

    noms = Counter(o.nom for o in ref.ouvriers.values())
    for nom, n in sorted(noms.items()):
        if n > 1:
            ids = sorted(o.id_ouvrier for o in ref.ouvriers.values() if o.nom == nom)
            rapport.ajouter(r.INFORMATION, "HOMONYMES",
                            f"{nom!r} porté par {', '.join(ids)} — identification par ID uniquement",
                            "Ouvriers")
