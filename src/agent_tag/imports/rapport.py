"""Rapport d'import : anomalies classées et compteurs par feuille."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Gravités
BLOQUANTE = "BLOQUANTE"          # l'import est rejeté en totalité
DECISION = "DECISION"            # importé tel quel ; une décision humaine est attendue
AVERTISSEMENT = "AVERTISSEMENT"  # importé ; point à surveiller
INFORMATION = "INFORMATION"

GRAVITES = (BLOQUANTE, DECISION, AVERTISSEMENT, INFORMATION)

# Statuts du résultat
APPLIQUE = "APPLIQUE"
REJETE = "REJETE"
DEJA_IMPORTE = "DEJA_IMPORTE"


@dataclass
class Anomalie:
    gravite: str
    code: str
    message: str
    feuille: str | None = None
    ligne: int | None = None
    colonne: str | None = None


@dataclass
class StatFeuille:
    lues: int = 0
    importees: int = 0
    rejetees: int = 0


@dataclass
class Rapport:
    fichier: str
    empreinte: str | None = None
    statut: str | None = None
    id_lot: int | None = None
    feuilles: dict[str, StatFeuille] = field(default_factory=dict)
    anomalies: list[Anomalie] = field(default_factory=list)
    lignes_en_erreur: dict[str, set[int]] = field(default_factory=dict)
    couvertures: list[dict] = field(default_factory=list)   # import journalier uniquement

    def ajouter(self, gravite, code, message, feuille=None, ligne=None, colonne=None):
        assert gravite in GRAVITES, gravite
        self.anomalies.append(Anomalie(gravite, code, message, feuille, ligne, colonne))
        if gravite == BLOQUANTE and feuille and ligne:
            self.lignes_en_erreur.setdefault(feuille, set()).add(ligne)

    def stat(self, feuille: str) -> StatFeuille:
        return self.feuilles.setdefault(feuille, StatFeuille())

    @property
    def bloquantes(self) -> list[Anomalie]:
        return [a for a in self.anomalies if a.gravite == BLOQUANTE]

    def codes(self, gravite: str | None = None) -> list[str]:
        return [a.code for a in self.anomalies if gravite is None or a.gravite == gravite]

    def finaliser_compteurs(self, applique: bool, feuilles_importees) -> None:
        """Lignes rejetées = lignes portant au moins une anomalie bloquante.
        Lignes importées = toutes les lignes lues des feuilles importées si le lot est appliqué
        (import tout ou rien), sinon 0. Les feuilles non importées restent à 0."""
        for nom, stat in self.feuilles.items():
            stat.rejetees = len(self.lignes_en_erreur.get(nom, ()))
            stat.importees = stat.lues if applique and nom in feuilles_importees else 0

    def en_dict(self) -> dict:
        return {
            "fichier": self.fichier,
            "empreinte": self.empreinte,
            "statut": self.statut,
            "id_lot": self.id_lot,
            "feuilles": {k: asdict(v) for k, v in self.feuilles.items()},
            "anomalies": [asdict(a) for a in self.anomalies],
            "synthese": {g: sum(a.gravite == g for a in self.anomalies) for g in GRAVITES},
            "couvertures": self.couvertures,
        }

    def en_texte(self) -> str:
        d = self.en_dict()
        lignes = [
            f"Fichier   : {self.fichier}",
            f"Empreinte : {self.empreinte or '-'}",
            f"Statut    : {self.statut}" + (f" (lot {self.id_lot})" if self.id_lot else ""),
            "",
            f"{'Feuille':<16}{'lues':>8}{'importées':>11}{'rejetées':>10}",
        ]
        for nom, s in self.feuilles.items():
            lignes.append(f"{nom:<16}{s.lues:>8}{s.importees:>11}{s.rejetees:>10}")
        if self.couvertures:
            lignes.append("")
            lignes.append(f"{'Date':<12}{'Chaîne':<8}{'Type':<14}{'État':<10}{'Remplace le lot':>16}")
            for c in self.couvertures:
                lignes.append(f"{c['date']:<12}{c['id_chaine']:<8}{c['type_donnee']:<14}"
                              f"{c['etat']:<10}{str(c.get('remplace_lot') or '-'):>16}")
        lignes.append("")
        lignes.append("Synthèse : " + ", ".join(f"{g} {n}" for g, n in d["synthese"].items()))
        for g in GRAVITES:
            liste = [a for a in self.anomalies if a.gravite == g]
            if not liste:
                continue
            lignes.append(f"\n[{g}]")
            for a in liste:
                lieu = ""
                if a.feuille:
                    lieu = f"{a.feuille}"
                    if a.ligne:
                        lieu += f" l.{a.ligne}"
                    if a.colonne:
                        lieu += f" [{a.colonne}]"
                    lieu += " : "
                lignes.append(f"  - {a.code} — {lieu}{a.message}")
        return "\n".join(lignes)
