"""Import du référentiel — cas exigés par l'incrément 1 (classeurs artificiels)."""

import threading

import psycopg
import pytest
from fabrique import Classeur, compter, instantane, lots, referentiel_vide

from agent_tag.imports import import_referentiel
from agent_tag.imports import rapport as r

pytestmark = pytest.mark.db


# --- Import valide --------------------------------------------------------------------

def test_import_valide(importer, base_import, tmp_path):
    fichier = Classeur().ecrire(tmp_path / "valide.xlsx")
    rap = importer(fichier)

    assert rap.statut == r.APPLIQUE, rap.en_texte()
    assert rap.bloquantes == []
    attendus = {"skill": 3, "position": 3, "production_line": 2, "line_critical_skill": 3,
                "worker": 4, "worker_skill": 6, "position_requirement": 3}
    assert {t: compter(base_import, t) for t in attendus} == attendus

    stats = {n: (s.lues, s.importees, s.rejetees) for n, s in rap.feuilles.items()}
    assert stats["Ouvriers"] == (4, 4, 0)
    assert stats["Competences"] == (6, 6, 0)
    assert stats["Absences"] == (0, 0, 0)

    [(id_lot, statut, hachage)] = lots(base_import)
    assert (id_lot, statut, hachage) == (rap.id_lot, "APPLIQUE", rap.empreinte)
    assert (importer.archives / f"{rap.empreinte}.xlsx").is_file()

    with base_import.owner() as conn:
        stocke = conn.execute("SELECT rapport FROM import_batch").fetchone()[0]
        coupeur = conn.execute(
            "SELECT code_competence_associee, source_correspondance, correspondance_validee "
            "FROM position WHERE code_poste = 'COUPEUR_COUPEUSE'").fetchone()
        exigence_coupeur = conn.execute(
            "SELECT count(*) FROM position_requirement WHERE code_poste = 'COUPEUR_COUPEUSE'"
        ).fetchone()[0]
    assert stocke["statut"] == "APPLIQUE"
    assert stocke["synthese"]["BLOQUANTE"] == 0
    # Exigence manquante signalée, jamais complétée.
    assert "EXIGENCE_ABSENTE" in rap.codes(r.DECISION)
    assert exigence_coupeur == 0
    # Correspondance Coupeur → Coupe déduite mais non validée (D7).
    assert coupeur == ("COUPE", "DEDUITE", False)
    assert "CORRESPONDANCE_DEDUITE" in rap.codes(r.DECISION)


def test_niveau_minimum_absent_signale_et_non_complete(importer, base_import, tmp_path):
    fichier = Classeur().modifier("Besoins_Postes", 0, "Niveau_minimum", None).ecrire(
        tmp_path / "f.xlsx")
    rap = importer(fichier)
    assert rap.statut == r.APPLIQUE
    assert "NIVEAU_MIN_ABSENT" in rap.codes(r.DECISION)
    with base_import.owner() as conn:
        niveau = conn.execute(
            "SELECT code_niveau_min FROM position_requirement "
            "WHERE id_chaine = 'LA' AND code_poste = 'PIQUEUR_PIQUEUSE'").fetchone()[0]
    assert niveau is None


# --- Fichier et structure -------------------------------------------------------------

def test_fichier_introuvable(importer, base_import, tmp_path):
    with pytest.raises(import_referentiel.ImportImpossible, match="introuvable"):
        importer(tmp_path / "absent.xlsx")
    assert lots(base_import) == []


def test_fichier_non_excel(importer, base_import, tmp_path):
    faux = tmp_path / "faux.xlsx"
    faux.write_text("pas un classeur", encoding="utf-8")
    rap = importer(faux)
    assert rap.statut == r.REJETE
    assert "FICHIER_ILLISIBLE" in rap.codes(r.BLOQUANTE)
    assert [s for _, s, _ in lots(base_import)] == ["REJETE"]
    assert referentiel_vide(base_import)


def test_auteur_inconnu(importer, base_import, tmp_path):
    fichier = Classeur().ecrire(tmp_path / "f.xlsx")
    with pytest.raises(import_referentiel.ImportImpossible, match="utilisateur inconnu"):
        importer(fichier, auteur="personne")
    assert lots(base_import) == []


@pytest.mark.parametrize("feuille", ["Ouvriers", "Competences", "Chaines", "Besoins_Postes"])
def test_feuille_obligatoire_manquante(importer, base_import, tmp_path, feuille):
    rap = importer(Classeur().supprimer_feuille(feuille).ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "FEUILLE_MANQUANTE" and a.feuille == feuille for a in rap.bloquantes)
    assert referentiel_vide(base_import)


def test_feuille_journaliere_manquante_non_bloquante(importer, tmp_path):
    rap = importer(Classeur().supprimer_feuille("Absences").ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.APPLIQUE
    assert "FEUILLE_MANQUANTE" in rap.codes(r.AVERTISSEMENT)


@pytest.mark.parametrize("feuille, colonne", [
    ("Ouvriers", "Chaîne_actuelle"),
    ("Competences", "Niveau"),
    ("Chaines", "Priorité"),
    ("Besoins_Postes", "Compétence_requise"),
])
def test_colonne_manquante(importer, base_import, tmp_path, feuille, colonne):
    rap = importer(Classeur().supprimer_colonne(feuille, colonne).ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "COLONNE_MANQUANTE" and a.colonne == colonne for a in rap.bloquantes)
    assert referentiel_vide(base_import)


# --- Contenu --------------------------------------------------------------------------

@pytest.mark.parametrize("feuille, ligne", [
    ("Ouvriers", ["T01", "Autre Nom", "LA", "ProduitA", "Piqueur/Piqueuse", "Disponible", 3,
                  "08:00-16:00"]),
    ("Competences", ["T01", "Alpha Test", "Piqueuse", "Secondaire", 2, "Débutant", "Non"]),
    ("Chaines", ["LA", "ProduitC", 1, 1, "Moyenne", "Piqueuse", 10]),
    ("Besoins_Postes", ["LA", "ProduitA", "Piqueur/Piqueuse", 2, "Piqueuse", "Expert"]),
])
def test_identifiant_duplique(importer, base_import, tmp_path, feuille, ligne):
    rap = importer(Classeur().ajouter_ligne(feuille, ligne).ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "IDENTIFIANT_DUPLIQUE" and a.feuille == feuille for a in rap.bloquantes)
    assert referentiel_vide(base_import)


def test_homonymes_acceptes_identification_par_id(importer, base_import, tmp_path):
    c = Classeur().modifier("Ouvriers", 1, "Nom", "Alpha Test")
    c.modifier("Competences", 2, "Nom", "Alpha Test")
    rap = importer(c.ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.APPLIQUE
    assert "HOMONYMES" in rap.codes(r.INFORMATION)
    assert compter(base_import, "worker") == 4


@pytest.mark.parametrize("modif, feuille", [
    (lambda c: c.ajouter_ligne("Competences",
                               ["T99", "Inconnu", "Piqueuse", "Principale", 1, "Débutant", "Non"]),
     "Competences"),
    (lambda c: c.modifier("Ouvriers", 0, "Chaîne_actuelle", "LZ"), "Ouvriers"),
    (lambda c: c.modifier("Chaines", 0, "Compétences_critiques", "Piqueuse;Broderie"), "Chaines"),
    (lambda c: c.ajouter_ligne("Besoins_Postes",
                               ["LZ", "ProduitZ", "Piqueur/Piqueuse", 1, "Piqueuse", "Débutant"]),
     "Besoins_Postes"),
])
def test_reference_orpheline(importer, base_import, tmp_path, modif, feuille):
    c = Classeur()
    modif(c)
    rap = importer(c.ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "REFERENCE_ORPHELINE" and a.feuille == feuille for a in rap.bloquantes)
    assert referentiel_vide(base_import)


@pytest.mark.parametrize("feuille, colonne, valeur", [
    ("Competences", "Niveau", "Avancé"),
    ("Competences", "Niveau", "expert"),          # casse différente : hors nomenclature
    ("Besoins_Postes", "Niveau_minimum", "Senior"),
])
def test_niveau_invalide(importer, base_import, tmp_path, feuille, colonne, valeur):
    rap = importer(Classeur().modifier(feuille, 0, colonne, valeur).ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "NIVEAU_INVALIDE" and a.feuille == feuille for a in rap.bloquantes)
    assert referentiel_vide(base_import)


@pytest.mark.parametrize("feuille, colonne", [
    ("Ouvriers", "Nom"),
    ("Ouvriers", "Horaire"),
    ("Competences", "Années_expérience"),
    ("Competences", "Certification"),
    ("Chaines", "Produit"),
    ("Besoins_Postes", "Compétence_requise"),
])
def test_valeur_obligatoire_absente(importer, base_import, tmp_path, feuille, colonne):
    rap = importer(Classeur().modifier(feuille, 0, colonne, None).ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert any(a.code == "VALEUR_OBLIGATOIRE" and a.colonne == colonne for a in rap.bloquantes)
    assert referentiel_vide(base_import)


@pytest.mark.parametrize("modif, code", [
    (lambda c: c.modifier("Competences", 0, "Type_compétence", "Secondaire"), "NB_PRINCIPALES"),
    (lambda c: c.modifier("Competences", 1, "Type_compétence", "Principale"), "NB_PRINCIPALES"),
    (lambda c: c.modifier("Competences", 0, "Nom", "Autre"), "INCOHERENCE"),
    (lambda c: c.modifier("Ouvriers", 0, "Produit", "ProduitB"), "INCOHERENCE"),
    (lambda c: c.modifier("Ouvriers", 0, "Horaire", "16:00-08:00"), "VALEUR_INVALIDE"),
    (lambda c: c.modifier("Competences", 0, "Années_expérience", 0), "VALEUR_INVALIDE"),
    (lambda c: c.modifier("Competences", 0, "Certification", "Peut-être"), "VALEUR_INVALIDE"),
])
def test_autres_controles_bloquants(importer, base_import, tmp_path, modif, code):
    c = Classeur()
    modif(c)
    rap = importer(c.ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert code in rap.codes(r.BLOQUANTE)
    assert referentiel_vide(base_import)


def test_compteurs_de_lignes_rejetees(importer, tmp_path):
    c = Classeur().modifier("Competences", 0, "Niveau", "Avancé")
    c.modifier("Competences", 3, "Certification", None)
    rap = importer(c.ecrire(tmp_path / "f.xlsx"))
    s = rap.feuilles["Competences"]
    assert (s.lues, s.importees, s.rejetees) == (6, 0, 2)


# --- Réimport, D15, atomicité ---------------------------------------------------------

def test_reimport_du_meme_fichier_sans_doublon(importer, base_import, tmp_path):
    fichier = Classeur().ecrire(tmp_path / "f.xlsx")
    premier = importer(fichier)
    avant = instantane(base_import)
    second = importer(fichier)
    assert second.statut == r.DEJA_IMPORTE
    assert second.id_lot == premier.id_lot
    assert instantane(base_import) == avant
    assert [s for _, s, _ in lots(base_import)] == ["APPLIQUE"]


def test_autre_referentiel_refuse_D15_et_donnees_conservees(importer, base_import, tmp_path):
    assert importer(Classeur().ecrire(tmp_path / "a.xlsx")).statut == r.APPLIQUE
    avant = instantane(base_import)
    autre = Classeur().modifier("Chaines", 0, "Capacité_journalière_unités", 999)
    rap = importer(autre.ecrire(tmp_path / "b.xlsx"))
    assert rap.statut == r.REJETE
    assert "REFERENTIEL_DEJA_PRESENT" in rap.codes(r.BLOQUANTE)
    assert instantane(base_import) == avant
    assert [s for _, s, _ in lots(base_import)] == ["APPLIQUE", "REJETE"]


def test_import_invalide_apres_import_valide_ne_modifie_rien(importer, base_import, tmp_path):
    assert importer(Classeur().ecrire(tmp_path / "a.xlsx")).statut == r.APPLIQUE
    avant = instantane(base_import)
    invalide = Classeur().supprimer_feuille("Competences").ecrire(tmp_path / "b.xlsx")
    assert importer(invalide).statut == r.REJETE
    assert instantane(base_import) == avant


def test_import_valide_possible_apres_un_rejet(importer, base_import, tmp_path):
    invalide = Classeur().modifier("Competences", 0, "Niveau", "Avancé").ecrire(tmp_path / "a.xlsx")
    assert importer(invalide).statut == r.REJETE
    assert importer(Classeur().ecrire(tmp_path / "b.xlsx")).statut == r.APPLIQUE
    assert [s for _, s, _ in lots(base_import)] == ["REJETE", "APPLIQUE"]


def test_retour_arriere_complet_si_l_ecriture_echoue(importer, base_import, tmp_path, monkeypatch):
    """Échec PostgreSQL réel provoqué après l'écriture des ouvriers et compétences."""

    def ecriture_defectueuse(cur, ref, id_lot):
        cur.execute("INSERT INTO position_requirement (id_chaine) VALUES ('LA')")  # NOT NULL violé

    monkeypatch.setattr(import_referentiel, "_ecrire_exigences", ecriture_defectueuse)
    rap = importer(Classeur().ecrire(tmp_path / "f.xlsx"))

    assert rap.statut == r.REJETE
    assert "ERREUR_ECRITURE" in rap.codes(r.BLOQUANTE)
    assert referentiel_vide(base_import)
    assert [s for _, s, _ in lots(base_import)] == ["REJETE"]


def test_retour_arriere_si_controle_differe_echoue(importer, base_import, tmp_path, monkeypatch):
    """Le contrôle différé de la base (une principale par ouvrier) annule toute la transaction,
    même si le contrôle Python a été contourné."""
    from agent_tag.imports import referentiel

    original = referentiel.controler

    def controle_contourne(feuilles, niveaux, rap):
        ref = original(feuilles, niveaux, rap)
        ref.detenues = [d for d in ref.detenues
                        if not (d.id_ouvrier == "T04" and d.type_competence == "PRINCIPALE")]
        return ref

    monkeypatch.setattr(referentiel, "controler", controle_contourne)
    rap = importer(Classeur().ecrire(tmp_path / "f.xlsx"))
    assert rap.statut == r.REJETE
    assert "ERREUR_ECRITURE" in rap.codes(r.BLOQUANTE)
    assert referentiel_vide(base_import)


def test_deux_imports_concurrents_un_seul_applique(base_import, tmp_path):
    fichiers = [Classeur().ecrire(tmp_path / "a.xlsx"),
                Classeur().modifier("Chaines", 0, "Capacité_journalière_unités", 7)
                .ecrire(tmp_path / "b.xlsx")]
    depart = threading.Barrier(2)
    resultats = []

    def lancer(f):
        depart.wait()
        resultats.append(import_referentiel.importer(base_import.app_url, f, "testeur",
                                                     tmp_path / "archives"))

    fils = [threading.Thread(target=lancer, args=(f,)) for f in fichiers]
    for t in fils:
        t.start()
    for t in fils:
        t.join(20)

    assert sorted(x.statut for x in resultats) == [r.APPLIQUE, r.REJETE]
    assert [s for _, s, _ in lots(base_import)].count("APPLIQUE") == 1
    assert compter(base_import, "production_line") == 2
