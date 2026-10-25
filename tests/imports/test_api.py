"""API HTTP : parcours complet via FastAPI (client de test), sur base jetable."""

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_tag.api.app import creer_app
from agent_tag.config import settings
from agent_tag.imports import import_journalier
from agent_tag.services import configuration

pytestmark = pytest.mark.db

CLASSEUR = (Path(__file__).resolve().parents[2] / "donnees" / "reference"
            / "Base_Allocation_Production_150_Ouvriers_v2.xlsx")
RESP = {"X-Utilisateur": "testeur"}
LECT = {"X-Utilisateur": "lecteur"}


@pytest.fixture
def client(importer, base_import, tmp_path):
    importer(CLASSEUR)
    import_journalier.importer(base_import.app_url, CLASSEUR, "testeur", tmp_path / "a", True)
    with base_import.owner() as c:
        c.execute("INSERT INTO app_user (identifiant, nom, role) "
                  "VALUES ('lecteur', 'Lecteur', 'LECTURE_TEST')")
    configuration.installer_profil_provisoire(base_import.owner_url, "A", "testeur")
    conf = settings.Settings("TEST", base_import.app_url, None)
    return TestClient(creer_app(conf))


def test_demarrage_refuse_si_usage_different(base_import):
    with pytest.raises(Exception, match="différent"):
        creer_app(settings.Settings("EXPLOITATION", base_import.app_url, None))


def test_parcours_complet_par_l_api(client):
    etat = client.get("/api/etat").json()
    assert etat["environnement"]["usage"] == "TEST"
    assert etat["configuration"]["validee"] is False
    assert "provisoires" in etat["configuration"]["avertissement"]
    assert etat["dates"] == ["2026-10-12"]

    eff = client.get("/api/effectifs", params={"date": "2026-10-12", "chaine": "L1"}).json()
    assert eff["synthese"] == {"ABSENT": 10, "DISPONIBLE": 20}

    r = client.post("/api/runs", json={"date": "2026-10-12", "chaine": "L1"}, headers=RESP)
    assert r.status_code == 201
    det = r.json()
    assert det["decision"]["possible"] is True
    assert det["iteration"]["couverture_maximale"] == 8
    besoins = {b["absent"]: b for b in det["besoins"]}
    assert besoins["O004"]["statut"] == "BLOQUE" and besoins["O004"]["proposition"] is None
    assert besoins["O005"]["rejets"].get("P3") == 43
    pid = besoins["O002"]["proposition"]["id"]

    r = client.post(f"/api/propositions/{pid}/accepter", json={}, headers=LECT)
    assert r.status_code == 403 and r.json()["code"] == "ROLE_NON_AUTORISE"
    r = client.post(f"/api/propositions/{pid}/accepter", json={}, headers=RESP)
    assert r.status_code == 200
    r = client.post(f"/api/propositions/{pid}/accepter", json={}, headers=RESP)
    assert r.status_code == 409 and r.json()["code"] == "PROPOSITION_NON_ACTIVE"

    id_run = det["run"]["id"]
    det = client.get(f"/api/runs/{id_run}", headers=RESP).json()
    o002 = next(b for b in det["besoins"] if b["absent"] == "O002")
    assert o002["statut"] == "POURVU" and o002["remplacement"]["usage"] == "TEST"

    pid10 = next(b for b in det["besoins"] if b["absent"] == "O010")["proposition"]["id"]
    r = client.post(f"/api/propositions/{pid10}/refuser", json={"motif": ""}, headers=RESP)
    assert r.status_code == 409 and r.json()["code"] == "MOTIF_REQUIS"
    assert client.post(f"/api/propositions/{pid10}/refuser", json={"motif": "test"},
                       headers=RESP).status_code == 200

    historique = client.get("/api/decisions", params={"date": "2026-10-12", "chaine": "L1"}).json()
    assert [h["type"] for h in historique] == ["REFUSER", "ACCEPTER"]
    assert all(h["usage"] == "TEST" and not h["configuration_validee"] for h in historique)
    assert client.get("/api/integrite").json() == {}

    assert client.post(f"/api/runs/{id_run}/cloturer", json={"motif": "fin"},
                       headers=RESP).json()["run"]["statut"] == "CLOS"


def test_erreurs_explicites(client):
    assert client.get("/api/runs/999").status_code == 404
    r = client.post("/api/runs", json={"date": "2026-10-13", "chaine": "L1"}, headers=RESP)
    assert r.status_code == 409 and r.json()["code"] == "DONNEES_INCOMPLETES"
    r = client.post("/api/runs", json={"date": "2026-10-12", "chaine": "L9"}, headers=RESP)
    assert r.status_code == 404
    r = client.post("/api/runs", json={"date": "2026-10-12", "chaine": "L1"})
    assert r.status_code == 403 and r.json()["code"] == "UTILISATEUR_REQUIS"
    assert client.post("/api/runs", json={"date": "pas une date", "chaine": "L1"},
                       headers=RESP).status_code == 422


def test_interface_servie(client):
    page = client.get("/")
    assert page.status_code == 200 and "Agent TAG" in page.text
    for fichier in ("app.js", "style.css"):
        assert client.get(f"/static/{fichier}").status_code == 200


def test_choix_reouverture_engagements_et_imports_par_l_api(client):
    det = client.post("/api/runs", json={"date": "2026-10-12", "chaine": "L1"}, headers=RESP).json()
    id_run = det["run"]["id"]
    # Un besoin avec proposition et un candidat éligible non proposé, non réservé.
    reserves = {e["ouvrier"] for e in client.get("/api/engagements", params={"date": "2026-10-12"}).json()}
    choix = next(((b, c["ouvrier"]) for b in det["besoins"] if b["proposition"]
                  for c in b["candidats"] if c["eligible"] and c["ouvrier"] not in reserves), None)
    assert choix, "aucun candidat éligible libre dans le classeur de référence"
    besoin, ouvrier = choix
    url = f"/api/propositions/{besoin['proposition']['id']}/choisir-autre"
    r = client.post(url, json={"id_ouvrier": ouvrier, "motif": ""}, headers=RESP)
    assert r.status_code == 409 and r.json()["code"] == "MOTIF_REQUIS"
    r = client.post(url, json={"id_ouvrier": ouvrier, "motif": "atelier"}, headers=LECT)
    assert r.status_code == 403
    r = client.post(url, json={"id_ouvrier": ouvrier, "motif": "atelier"}, headers=RESP)
    if r.status_code == 409 and r.json()["code"] in ("P1", "P3"):
        pytest.skip(f"candidat refusé par {r.json()['code']}")
    assert r.status_code == 200, r.json()

    engagements = client.get("/api/engagements", params={"date": "2026-10-12"}).json()
    assert {"ouvrier": ouvrier, "type": "ENGAGE"}.items() <= next(
        e for e in engagements if e["ouvrier"] == ouvrier).items()

    det = client.get(f"/api/runs/{id_run}", headers=RESP).json()
    b = next(x for x in det["besoins"] if x["id"] == besoin["id"])
    assert b["statut"] == "POURVU" and b["remplacement"]["ouvrier"] == ouvrier
    assert [d["type"] for d in b["decisions"]] == ["CHOISIR_AUTRE"]

    # Laisser non pourvu puis rouvrir un autre besoin.
    autre = next(x for x in det["besoins"] if x["proposition"])
    assert client.post(f"/api/besoins/{autre['id']}/laisser-non-pourvu", json={"motif": "test"},
                       headers=RESP).status_code == 200
    r = client.post(f"/api/besoins/{autre['id']}/rouvrir", json={"motif": ""}, headers=RESP)
    assert r.status_code == 409 and r.json()["code"] == "MOTIF_REQUIS"
    assert client.post(f"/api/besoins/{autre['id']}/rouvrir", json={"motif": "test"},
                       headers=RESP).status_code == 200
    assert client.post("/api/besoins/999999/rouvrir", json={"motif": "x"},
                       headers=RESP).status_code == 404

    lots = client.get("/api/imports", params={"date": "2026-10-12"}).json()
    assert len(lots) == 1 and lots[0]["courant"] is True and lots[0]["propositions_annulees"] == 0
    assert client.get("/api/imports", params={"date": "2026-10-13"}).json() == []
    assert client.get("/api/engagements", params={"date": "2026-10-13"}).json() == []
    assert client.get("/api/integrite").json() == {}
