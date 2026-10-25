"""API HTTP d'Agent TAG (FastAPI) et service de l'interface web.

Lancement : python -m agent_tag.api   (voir README).
Identification : en-tête `X-Utilisateur` = identifiant d'un utilisateur actif. Aucune
authentification à ce stade (D14 ouverte) : convient uniquement à l'environnement TEST.
Les refus métier renvoient 409 (code + message), les refus d'autorisation 403.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_tag.config import demarrage, settings
from agent_tag.persistence import db
from agent_tag.services import allocation as s
from agent_tag.services import integrite, vues

STATIQUE = Path(__file__).parent / "static"


class Lancement(BaseModel):
    date: date
    chaine: str


class Motif(BaseModel):
    motif: str | None = None


class Choix(BaseModel):
    id_ouvrier: str
    motif: str | None = None


class Annulation(BaseModel):
    motif: str
    exclure_ouvrier: bool


def creer_app(conf: settings.Settings | None = None) -> FastAPI:
    conf = conf or settings.charger()
    with db.connecter(conf.database_url) as conn:
        demarrage.verifier(conn, conf.usage)   # refuse de démarrer si l'usage diffère (T94)
    url = conf.database_url
    app = FastAPI(title="Agent TAG", version="0.4.0")

    def lire(fn, *args, **kw):
        """Lectures dans une transaction REPEATABLE READ READ ONLY : vue cohérente, aucune écriture."""
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return fn(conn, *args, **kw)

    @app.exception_handler(s.RefusMetier)
    async def _refus(request: Request, exc: s.RefusMetier):
        statut = 404 if isinstance(exc, s.NonTrouve) else 403 if isinstance(exc, s.Interdit) else 409
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=statut)

    @app.exception_handler(ValueError)
    async def _valeur(request: Request, exc: ValueError):
        return JSONResponse({"code": "REQUETE_INVALIDE", "message": str(exc)}, status_code=400)

    # --- Lectures ------------------------------------------------------------------------
    @app.get("/api/etat")
    def etat():
        return lire(vues.etat)

    @app.get("/api/effectifs")
    def effectifs(date: date, chaine: str):
        return lire(vues.effectifs, date, chaine)

    @app.get("/api/runs")
    def runs(date: date | None = None, chaine: str | None = None):
        return lire(vues.runs, date, chaine)

    @app.get("/api/runs/{id_run}")
    def detail_run(id_run: int, x_utilisateur: str | None = Header(default=None)):
        return lire(vues.detail_run, id_run, x_utilisateur)

    @app.get("/api/decisions")
    def decisions(date: date | None = None, chaine: str | None = None, run: int | None = None):
        return lire(vues.decisions, date, chaine, run)

    @app.get("/api/engagements")
    def engagements(date: date):
        return lire(vues.engagements, date)

    @app.get("/api/imports")
    def imports(date: date):
        return lire(vues.imports, date)

    @app.get("/api/integrite")
    def controle_integrite():
        return lire(integrite.verifier)

    # --- Opérations ----------------------------------------------------------------------
    @app.post("/api/runs", status_code=201)
    def lancer(corps: Lancement, x_utilisateur: str | None = Header(default=None)):
        id_run = s.lancer(url, corps.date, corps.chaine, x_utilisateur)
        return lire(vues.detail_run, id_run, x_utilisateur)

    @app.post("/api/runs/{id_run}/recalculer")
    def recalculer(id_run: int, x_utilisateur: str | None = Header(default=None)):
        s.recalculer(url, id_run, x_utilisateur)
        return lire(vues.detail_run, id_run, x_utilisateur)

    @app.post("/api/runs/{id_run}/cloturer")
    def cloturer(id_run: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        s.cloturer(url, id_run, x_utilisateur, corps.motif or "")
        return lire(vues.detail_run, id_run, x_utilisateur)

    @app.post("/api/propositions/{id_p}/accepter")
    def accepter(id_p: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        id_rempl = s.accepter(url, id_p, x_utilisateur, corps.motif)
        return {"remplacement": id_rempl}

    @app.post("/api/propositions/{id_p}/refuser")
    def refuser(id_p: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        s.refuser(url, id_p, x_utilisateur, corps.motif or "")
        return {"ok": True}

    @app.post("/api/propositions/{id_p}/choisir-autre")
    def choisir_autre(id_p: int, corps: Choix, x_utilisateur: str | None = Header(default=None)):
        id_rempl = s.choisir_autre(url, id_p, corps.id_ouvrier, x_utilisateur, corps.motif or "")
        return {"remplacement": id_rempl}

    @app.post("/api/besoins/{id_b}/rouvrir")
    def rouvrir(id_b: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        s.rouvrir(url, id_b, x_utilisateur, corps.motif or "")
        return {"ok": True}

    @app.post("/api/besoins/{id_b}/laisser-non-pourvu")
    def non_pourvu(id_b: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        s.laisser_non_pourvu(url, id_b, x_utilisateur, corps.motif or "")
        return {"ok": True}

    @app.post("/api/remplacements/{id_r}/annuler")
    def annuler(id_r: int, corps: Annulation, x_utilisateur: str | None = Header(default=None)):
        s.annuler_remplacement(url, id_r, x_utilisateur, corps.motif, corps.exclure_ouvrier)
        return {"ok": True}

    @app.post("/api/remplacements/{id_r}/confirmer-apres-reimport")
    def confirmer(id_r: int, corps: Motif, x_utilisateur: str | None = Header(default=None)):
        s.confirmer_apres_reimport(url, id_r, x_utilisateur, corps.motif or "")
        return {"ok": True}

    # --- Interface -----------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATIQUE), name="static")

    @app.get("/", include_in_schema=False)
    def accueil():
        return FileResponse(STATIQUE / "index.html")

    return app
