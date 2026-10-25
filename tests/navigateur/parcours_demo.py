"""Parcours de bout en bout dans Chromium contre l'API réelle (base de démonstration TEST).

Prérequis : API lancée sur la base agent_tag_demo fraîchement initialisée, et Playwright
installé (pip install playwright && playwright install chromium). Usage :
    DEMO_URL=postgresql://agent_tag_app:...@.../agent_tag_demo python tests/navigateur/parcours_demo.py DOSSIER_CAPTURES
AGENT_TAG_PYTHON : Python où agent_tag est installé (par défaut celui qui exécute ce script).
DEMO_URL sert à la simulation de réimport (commande simuler-reimport, usage TEST).
Non collecté par pytest (nom de fichier sans préfixe test_)."""
import json, os, subprocess, sys, urllib.request
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8000"
CAP = sys.argv[1]
erreurs = []

def integrite():
    return json.load(urllib.request.urlopen(BASE + "/api/integrite"))

with sync_playwright() as p:
    nav = p.chromium.launch()
    page = nav.new_page(viewport={"width": 1400, "height": 1000})
    page.on("console", lambda m: m.type == "error" and erreurs.append(m.text))
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    page.goto(BASE + "/")
    expect(page.locator("#avertissement")).to_contain_text("Paramètres provisoires de TEST")
    expect(page.locator("#titre-chaine")).to_have_text("Chaîne L1 le 12/10/2026")
    expect(page.locator("#synthese")).to_contain_text("10")
    assert page.locator(".carreau.ABSENT").count() == 10, "10 absents attendus dans la bande"
    assert page.locator(".carreau.DISPONIBLE").count() == 20
    page.screenshot(path=f"{CAP}/1_accueil.png", full_page=True)
    print("1. accueil : avertissement provisoire, 20 disponibles / 10 absents affichés")

    # Lecteur : calcul possible, décisions bloquées
    page.select_option("#utilisateur", "demo.lecteur")
    page.click("#bouton-lancer")
    expect(page.locator("#table-besoins tbody tr")).to_have_count(10)
    expect(page.locator("#raison-decision")).to_contain_text("LECTURE_TEST ne peut pas décider")
    assert page.locator("#accepter").count() == 0, "aucun bouton de confirmation pour le lecteur"
    print("2. lecteur : calcul lancé (10 besoins), confirmation indisponible :",
          page.locator("#raison-decision").inner_text())

    # Responsable : confirmer la proposition de O002
    page.select_option("#utilisateur", "demo.responsable")
    expect(page.locator("#raison-decision")).to_be_hidden()
    page.click("tr[data-besoin] >> text=O002")
    propose = page.locator(".encadre.proposition .titre").inner_text()
    page.screenshot(path=f"{CAP}/2_proposition.png", full_page=True)
    page.click("#accepter")
    expect(page.locator("#message")).to_contain_text("confirmé")
    ligne = page.locator("tr[data-besoin]", has_text="O002")
    expect(ligne).to_contain_text("Remplacement confirmé")
    print("3. confirmation :", propose, "→", ligne.inner_text().replace("\n", " | "))

    # Refuser la proposition de O010 avec motif (sans motif : refus attendu)
    page.click("tr[data-besoin] >> text=O010")
    avant = page.locator(".encadre.proposition .titre").inner_text()
    page.click("#refuser")
    expect(page.locator("#message")).to_contain_text("motif")
    expect(page.locator("#refuser")).to_be_enabled()
    page.fill("#motif-decision", "Ouvrier en formation ce jour (démonstration)")
    page.click("#refuser")
    expect(page.locator("#message")).to_contain_text("refusée")
    page.click("tr[data-besoin] >> text=O010")
    expect(page.locator(".encadre.proposition .titre")).not_to_have_text(avant)
    apres = page.locator(".encadre.proposition .titre").inner_text()
    print("4. refus :", avant, "→ nouvelle", apres)

    # Besoin bloqué O004
    page.click("tr[data-besoin] >> text=O004")
    expect(page.locator(".encadre.bloque")).to_contain_text("EXIGENCE_ABSENTE")
    assert page.locator("#accepter").count() == 0
    page.screenshot(path=f"{CAP}/3_bloque.png", full_page=True)
    print("5. O004 bloqué :", " ".join(page.locator(".encadre.bloque p").nth(1).inner_text().split()))

    # Candidats écartés visibles pour O005
    page.click("tr[data-besoin] >> text=O005")
    expect(page.locator(".encadre.sans-candidat")).to_contain_text("P3")
    page.click("details.ecartes summary")
    print("6. O005 sans candidat :", page.locator("details.ecartes summary").inner_text())

    # Choisir un autre candidat admissible (motif exigé)
    choisi = None
    for absent in ["O001", "O003", "O006", "O007", "O008", "O009"]:
        page.click(f"tr[data-besoin] >> text={absent}")
        if page.locator(".encadre.proposition").count() == 0:
            continue
        boutons = page.locator("[data-choisir]")
        if boutons.count() == 0:
            continue
        boutons.first.click()
        expect(page.locator("#message")).to_contain_text("motif")
        page.fill("#motif-decision", "Préférence du chef d'atelier (démonstration)")
        candidat = boutons.first.get_attribute("data-choisir")
        boutons.first.click()
        expect(page.locator("#message")).not_to_contain_text("motif")
        texte = page.locator("#message").inner_text()
        if "choisi et confirmé" in texte:
            choisi = (absent, candidat)
            break
        print("   choix refusé pour", absent, ":", texte)
    assert choisi, "aucun autre candidat n'a pu être choisi"
    ligne = page.locator("tr[data-besoin]", has_text=choisi[0])
    expect(ligne).to_contain_text("Remplacement confirmé")
    expect(ligne).to_contain_text(choisi[1])
    page.click(f"tr[data-besoin] >> text={choisi[0]}")
    expect(page.locator(".decisions-besoin")).to_contain_text("Autre candidat choisi")
    page.screenshot(path=f"{CAP}/4_choix_autre.png", full_page=True)
    print("7. autre candidat :", choisi[1], "choisi pour", choisi[0], "→", ligne.inner_text().replace("\n", " | "))

    # Laisser non pourvu puis rouvrir
    restant = next(a for a in ["O001", "O003", "O006", "O007", "O008", "O009"]
                   if a != choisi[0] and "Proposition" in page.locator("tr[data-besoin]", has_text=a).inner_text())
    page.click(f"tr[data-besoin] >> text={restant}")
    page.fill("#motif-decision", "Poste fermé ce jour (démonstration)")
    page.click("#non-pourvu")
    expect(page.locator("tr[data-besoin]", has_text=restant)).to_contain_text("Laissé non pourvu")
    page.click(f"tr[data-besoin] >> text={restant}")
    page.click("#rouvrir")
    expect(page.locator("#message")).to_contain_text("motif")
    page.fill("#motif-rouvrir", "Poste finalement ouvert (démonstration)")
    page.click("#rouvrir")
    expect(page.locator("#message")).to_contain_text("rouvert")
    print("8. non pourvu puis rouvert :", restant, "→",
          page.locator("tr[data-besoin]", has_text=restant).inner_text().replace("\n", " | "))

    # Réservations et engagements
    eng = page.locator("#table-engagements tbody tr")
    engages = eng.filter(has_text="Engagé").count()
    reserves = eng.filter(has_text="Réservé").count()
    assert engages == 2, f"2 engagés attendus, {engages} affichés"
    print(f"9. engagements : {engages} engagés, {reserves} réservés")

    # Historique
    lignes = page.locator("#table-historique tbody tr")
    expect(lignes).to_have_count(5)
    print("10. historique :", [l.split("\t")[1] for l in lignes.all_inner_texts()])
    page.screenshot(path=f"{CAP}/5_engagements_historique.png", full_page=True)

    # Réimport simulé (TEST) : le remplaçant de O002 devient absent
    id_remplacant = page.locator("tr[data-besoin]", has_text="O002").locator("td").nth(3).inner_text().split()[0]
    env = dict(os.environ, AGENT_TAG_DATABASE_URL=os.environ["DEMO_URL"])
    sortie = subprocess.run([os.environ.get("AGENT_TAG_PYTHON", sys.executable), "-m", "agent_tag.cli", "simuler-reimport", "--ouvrier",
                             id_remplacant], env=env, capture_output=True, text=True)
    assert sortie.returncode == 0, sortie.stdout + sortie.stderr
    page.reload()
    expect(page.locator("#bandeau-reimport")).to_be_visible()
    expect(page.locator("#bandeau-reimport")).to_contain_text("à revoir")
    expect(page.locator("tr[data-besoin]", has_text="O002")).to_contain_text("à revoir")
    expect(page.locator("#table-imports tbody tr")).to_have_count(2)
    print("11. réimport simulé (", id_remplacant, "absent ) :", page.locator("#bandeau-reimport").inner_text())
    print("    imports :", [l.replace("\n", " | ") for l in page.locator("#table-imports tbody tr").all_inner_texts()])
    page.screenshot(path=f"{CAP}/6_reimport.png", full_page=True)
    page.click("#bouton-recalculer")
    expect(page.locator("#message")).to_contain_text("relancé")
    print("12. recalcul :", page.locator("#resume-calcul").inner_text())

    # Affichage mobile
    page.set_viewport_size({"width": 390, "height": 900})
    page.screenshot(path=f"{CAP}/7_mobile.png", full_page=False)
    largeur = page.evaluate("document.documentElement.scrollWidth")
    print("13. mobile : largeur de page", largeur, "px pour une fenêtre de 390 px")
    nav.close()

print("14. invariants côté serveur :", integrite() or "aucune violation")
print("Erreurs du navigateur :", erreurs or "aucune")
