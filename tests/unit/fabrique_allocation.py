"""Instantanés ARTIFICIELS pour tester le moteur d'allocation sans base de données."""

from __future__ import annotations

from datetime import date, time

from agent_tag.domain import allocation as a

NIVEAUX = {"DEBUTANT": 1, "INTERMEDIAIRE": 2, "EXPERT": 3}
JOUR = date(2026, 3, 2)


def config(m_bloc=1, m_alerte=1, p3=10, **kw):
    return a.Configuration("TEST unitaire (non validé)", m_bloc, m_alerte, p3,
                           {"Moyenne": 1, "Élevée": 2, "Très élevée": 3}, **kw)


class Fabrique:
    """Construit un instantané pas à pas.

    postes : code → compétence associée (même code en minuscule pour la lisibilité).
    """

    def __init__(self):
        self.ouvriers, self.jour, self.competences = {}, {}, {}
        self.exigences, self.chaines = {}, {}
        self.postes = {}
        self.engages, self.chaines_interdites = set(), set()

    def chaine(self, id_ch, priorite="Moyenne", critiques=()):
        self.chaines[id_ch] = a.Chaine(id_ch, priorite, frozenset(critiques))
        return self

    def poste(self, code, competence, source="BESOINS_POSTES"):
        self.postes[code] = a.Poste(code, code.title(), competence, source,
                                    source == "BESOINS_POSTES")
        return self

    def exigence(self, chaine, poste, competence, niveau_min="INTERMEDIAIRE"):
        self.exigences[(chaine, poste)] = a.Exigence(
            competence, niveau_min, NIVEAUX[niveau_min] if niveau_min else None)
        return self

    def ouvrier(self, id_o, chaine, poste, etat="DISPONIBLE", competences=(),
                horaire=(time(8), time(16)), besoin=None, cause=None):
        """competences : (code, type, niveau, années)."""
        self.ouvriers[id_o] = a.Ouvrier(id_o, f"Nom {id_o}", chaine, poste)
        if besoin is None:
            besoin = etat == "ABSENT"
        affecte = etat != "INCONNU"   # INCONNU : aucune affectation du jour
        self.jour[id_o] = a.Jour(
            etat, cause or {"DISPONIBLE": "PRESENT_SANS_ABSENCE",
                            "ABSENT": "ABSENCE_CONFIRMEE"}.get(etat, "TEST"),
            besoin,
            chaine if affecte else None, poste if affecte else None,
            horaire[0] if affecte else None, horaire[1] if affecte else None)
        for comp, typ, niv, ans in competences:
            self.competences[(id_o, comp)] = a.Detenue(typ, niv, NIVEAUX[niv], ans, False)
        return self

    def instantane(self) -> a.Instantane:
        return a.Instantane(JOUR, dict(self.ouvriers), dict(self.jour), dict(self.competences),
                            dict(self.exigences), dict(self.postes), dict(self.chaines),
                            {c: c.title() for _, c in self.competences},
                            {k: k.title() for k in NIVEAUX},
                            frozenset(self.engages), frozenset(self.chaines_interdites))


def P(niveau="INTERMEDIAIRE", ans=3, comp="piq"):
    return (comp, "PRINCIPALE", niveau, ans)


def S(niveau="INTERMEDIAIRE", ans=3, comp="piq"):
    return (comp, "SECONDAIRE", niveau, ans)


def base():
    """Cible LC (absent C1, poste PIQ, compétence piq Intermédiaire) ; donneuses LD, LE.
    Les postes ont deux titulaires de plus que nécessaire pour éviter les blocages par défaut."""
    f = (Fabrique()
         .chaine("LC", "Très élevée", critiques=("piq",))
         .chaine("LD", "Moyenne").chaine("LE", "Élevée")
         .poste("PIQ", "piq").poste("FIN", "fin").poste("SUR", "sur")
         .exigence("LC", "PIQ", "piq", "INTERMEDIAIRE"))
    f.ouvrier("C1", "LC", "PIQ", "ABSENT", [P()])
    return f
