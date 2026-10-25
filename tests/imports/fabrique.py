"""Classeurs ARTIFICIELS pour les tests (données fictives, sans lien avec le classeur de référence).

Jeu minimal valide :
- 2 chaînes (LA, LB), 4 ouvriers (T01–T04), 3 compétences, 3 postes ;
- l'exigence (LB, Coupeur/Coupeuse) est volontairement absente → anomalie DECISION attendue.
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from agent_tag.imports.classeur import COLONNES

BASE = {
    "Ouvriers": [
        ["T01", "Alpha Test", "LA", "ProduitA", "Piqueur/Piqueuse", "Disponible", 3, "08:00-16:00"],
        ["T02", "Beta Test", "LA", "ProduitA", "Surjeteur/Surjeteuse", "Disponible", 2, "08:00-16:00"],
        ["T03", "Gamma Test", "LB", "ProduitB", "Piqueur/Piqueuse", "Disponible", 5, "08:00-16:00"],
        ["T04", "Delta Test", "LB", "ProduitB", "Coupeur/Coupeuse", "Disponible", 4, "08:00-16:00"],
    ],
    "Competences": [
        ["T01", "Alpha Test", "Piqueuse", "Principale", 3, "Intermédiaire", "Oui"],
        ["T01", "Alpha Test", "Surjeteuse", "Secondaire", 1, "Débutant", "Non"],
        ["T02", "Beta Test", "Surjeteuse", "Principale", 2, "Débutant", "Oui"],
        ["T03", "Gamma Test", "Piqueuse", "Principale", 5, "Expert", "Oui"],
        ["T03", "Gamma Test", "Surjeteuse", "Secondaire", 3, "Intermédiaire", "Non"],
        ["T04", "Delta Test", "Coupe", "Principale", 4, "Intermédiaire", "Oui"],
    ],
    "Chaines": [
        ["LA", "ProduitA", 2, 2, "Élevée", "Piqueuse;Surjeteuse", 100],
        ["LB", "ProduitB", 2, 2, "Moyenne", "Piqueuse", 80],
    ],
    "Besoins_Postes": [
        ["LA", "ProduitA", "Piqueur/Piqueuse", 1, "Piqueuse", "Intermédiaire"],
        ["LA", "ProduitA", "Surjeteur/Surjeteuse", 1, "Surjeteuse", "Débutant"],
        ["LB", "ProduitB", "Piqueur/Piqueuse", 1, "Piqueuse", "Intermédiaire"],
    ],
    "Absences": [],
    "Affectations": [],
}


TABLES_REFERENTIEL = ("skill", "position", "production_line", "line_critical_skill", "worker",
                      "worker_skill", "position_requirement")


def compter(base, table):
    with base.owner() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def instantane(base):
    """Contenu complet des tables du référentiel, pour comparer avant/après."""
    with base.owner() as conn:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
                for t in TABLES_REFERENTIEL}


def referentiel_vide(base):
    return all(compter(base, t) == 0 for t in TABLES_REFERENTIEL)


def lots(base):
    with base.owner() as conn:
        return conn.execute(
            "SELECT id, statut, empreinte_fichier FROM import_batch ORDER BY id").fetchall()


TABLES_JOURNALIERES = ("daily_assignment", "absence", "batch_coverage", "data_version")


def journalier_vide(base):
    return all(compter(base, t) == 0 for t in TABLES_JOURNALIERES)


def instantane_journalier(base):
    with base.owner() as conn:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
                for t in TABLES_JOURNALIERES}


class Classeur:
    """Description modifiable d'un classeur, écrite sur disque par `ecrire`."""

    def __init__(self):
        self.feuilles = {nom: [list(COLONNES[nom])] + copy.deepcopy(lignes)
                         for nom, lignes in BASE.items()}
        self.feuilles["Scenario_Test"] = [["Élément", "Valeur"], ["Note", "jeu artificiel"]]
        self.feuilles["README"] = [["Élément", "Description"], ["Objet", "jeu artificiel"]]

    def supprimer_feuille(self, nom):
        del self.feuilles[nom]
        return self

    def supprimer_colonne(self, feuille, colonne):
        i = self.feuilles[feuille][0].index(colonne)
        for ligne in self.feuilles[feuille]:
            del ligne[i]
        return self

    def modifier(self, feuille, index_ligne, colonne, valeur):
        """index_ligne : 0 = première ligne de données."""
        i = self.feuilles[feuille][0].index(colonne)
        self.feuilles[feuille][index_ligne + 1][i] = valeur
        return self

    def ajouter_ligne(self, feuille, ligne):
        self.feuilles[feuille].append(list(ligne))
        return self

    def vider(self, feuille):
        del self.feuilles[feuille][1:]
        return self

    def ecrire(self, chemin: Path) -> Path:
        wb = Workbook()
        wb.remove(wb.active)
        for nom, lignes in self.feuilles.items():
            ws = wb.create_sheet(nom)
            for ligne in lignes:
                ws.append(ligne)
        wb.save(chemin)
        return chemin


# --- Données journalières ARTIFICIELLES ----------------------------------------------------
# Référentiel : celui de `Classeur()` (T01, T02 sur LA ; T03, T04 sur LB).
# Jour J1 : T01, T03, T04 présents ; T02 absent, avec une absence d'un jour.

J1 = datetime(2026, 3, 2)
J2 = datetime(2026, 3, 3)

_INFOS = {
    "T01": ("Alpha Test", "LA", "ProduitA", "Piqueur/Piqueuse"),
    "T02": ("Beta Test", "LA", "ProduitA", "Surjeteur/Surjeteuse"),
    "T03": ("Gamma Test", "LB", "ProduitB", "Piqueur/Piqueuse"),
    "T04": ("Delta Test", "LB", "ProduitB", "Coupeur/Coupeuse"),
}


def affectation(jour, id_o, statut="Présent"):
    nom, ch, prod, poste = _INFOS[id_o]
    return [jour, id_o, nom, ch, prod, poste, "08:00-16:00", statut]


def absence(jour, id_o, duree=1, motif="Absence imprévue"):
    nom, ch, _, poste = _INFOS[id_o]
    return [jour, id_o, nom, ch, poste, "Absent", motif, duree]


def journalier(affectations=None, absences=None) -> Classeur:
    """Classeur contenant seulement Affectations et Absences (plus les feuilles descriptives)."""
    c = Classeur()
    for nom in ("Ouvriers", "Competences", "Chaines", "Besoins_Postes"):
        c.supprimer_feuille(nom)
    c.vider("Affectations").vider("Absences")
    if affectations is None:
        affectations = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"),
                        affectation(J1, "T03"), affectation(J1, "T04")]
    if absences is None:
        absences = [absence(J1, "T02")]
    for ligne in affectations:
        c.ajouter_ligne("Affectations", ligne)
    for ligne in absences:
        c.ajouter_ligne("Absences", ligne)
    return c
