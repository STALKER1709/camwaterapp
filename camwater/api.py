"""Interface HTTP (FastAPI) : réception des factures et supervision.

Endpoints :

    GET  /                 page d'upload (HTML minimal, aucun build front)
    GET  /health           sonde de disponibilité
    POST /api/upload       dépôt d'une ou plusieurs factures (PDF, PNG, JPG)
    GET  /api/stats        état du classeur général
    GET  /api/excel        téléchargement du fichier Excel général
    GET  /api/rapports     liste des rapports de traitement
    GET  /api/rapports/{nom}   contenu d'un rapport

Plusieurs postes peuvent envoyer en parallèle : l'écriture Excel est sérialisée
par le verrou de `excel_manager`, et le traitement lourd (conversion + appel au
modèle) s'exécute dans le pool de threads pour ne pas bloquer la boucle
d'événements.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import (
    ALLOWED_EXTENSIONS,
    EXCEL_PATH,
    LLM_MODEL,
    MAX_UPLOAD_BYTES,
    REPORT_DIR,
    STATIC_DIR,
    UPLOAD_DIR,
    ensure_directories,
)
from .excel_manager import ExcelManager
from .logging_setup import configurer_logs
from .pdf_utils import poppler_disponible
from .pipeline import traiter_fichier

logger = logging.getLogger(__name__)

_NOM_SUR = re.compile(r"[^A-Za-z0-9._-]+")
_TAILLE_BLOC = 1024 * 1024


def _nom_sur(nom: str) -> str:
    """Nom de fichier assaini : pas de chemin, pas d'accent, pas d'espace."""
    base = Path(nom or "facture").name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _NOM_SUR.sub("_", base).strip("._") or "facture"
    return base[:120]


def creer_application() -> FastAPI:
    """Construit l'application FastAPI (utilisée par `app.py` et les tests)."""
    configurer_logs()
    ensure_directories()

    @asynccontextmanager
    async def cycle_de_vie(_: FastAPI):
        logger.info(
            "Application démarrée (version %s, modèle %s, Excel %s)",
            __version__,
            LLM_MODEL,
            EXCEL_PATH,
        )
        if not poppler_disponible():
            logger.warning(
                "poppler-utils absent : les PDF seront transmis nativement au modèle "
                "au lieu d'être convertis en PNG. Installez poppler pour de meilleurs résultats."
            )
        yield
        logger.info("Arrêt de l'application.")

    application = FastAPI(
        lifespan=cycle_de_vie,
        title="CAMWATER — Extraction automatique de factures",
        version=__version__,
        description=(
            "Dépôt de factures CAMWATER (PDF/PNG/JPG), lecture visuelle par IA, "
            "application des règles métier et alimentation du fichier Excel général."
        ),
    )
    excel = ExcelManager()

    # ------------------------------------------------------------------ #
    # Pages et sondes
    # ------------------------------------------------------------------ #

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def accueil() -> HTMLResponse:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            return HTMLResponse(
                "<h1>CAMWATER</h1><p>Page d'accueil absente ; l'API reste disponible "
                "sur <a href='/docs'>/docs</a>.</p>",
                status_code=200,
            )
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @application.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "statut": "ok",
            "version": __version__,
            "modele": LLM_MODEL,
            "conversion_pdf": "poppler" if poppler_disponible() else "repli PDF natif",
            "excel": str(EXCEL_PATH),
            "excel_existe": EXCEL_PATH.exists(),
        }

    # ------------------------------------------------------------------ #
    # Dépôt de factures
    # ------------------------------------------------------------------ #

    async def _enregistrer_upload(fichier: UploadFile) -> Path:
        """Écrit le fichier reçu dans `uploads/` en contrôlant taille et extension."""
        nom = _nom_sur(fichier.filename or "facture")
        extension = Path(nom).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Format non pris en charge : « {extension or 'inconnu'} ». "
                    f"Formats acceptés : {', '.join(sorted(ALLOWED_EXTENSIONS))}."
                ),
            )

        horodatage = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        cible = UPLOAD_DIR / f"{horodatage}_{nom}"
        taille = 0
        try:
            with cible.open("wb") as sortie:
                while bloc := await fichier.read(_TAILLE_BLOC):
                    taille += len(bloc)
                    if taille > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"Fichier trop volumineux (> {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)."
                            ),
                        )
                    sortie.write(bloc)
        except HTTPException:
            cible.unlink(missing_ok=True)
            raise
        except OSError as exc:
            cible.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Écriture impossible : {exc}") from exc
        finally:
            await fichier.close()

        if taille == 0:
            cible.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Fichier vide.")
        return cible

    @application.post("/api/upload")
    async def upload(
        fichiers: list[UploadFile] = File(..., description="Factures PDF, PNG ou JPG"),
        annee: Optional[int] = Form(None, description="Année à utiliser si illisible"),
        administration: Optional[str] = Form(
            None, description="Ministère de repli si le mapping échoue"
        ),
        utilisateur: Optional[str] = Form(None, description="Poste ou agent déposant"),
    ) -> JSONResponse:
        """Reçoit les factures, déclenche le pipeline et renvoie les rapports."""
        if not fichiers:
            raise HTTPException(status_code=400, detail="Aucun fichier reçu.")

        resultats: list[dict[str, Any]] = []
        for fichier in fichiers:
            try:
                chemin = await _enregistrer_upload(fichier)
            except HTTPException as exc:
                resultats.append(
                    {
                        "fichier": fichier.filename,
                        "succes": False,
                        "erreur": exc.detail,
                    }
                )
                continue

            rapport = await run_in_threadpool(
                traiter_fichier,
                chemin,
                annee=annee,
                administration=(administration or "").strip() or None,
                utilisateur=(utilisateur or "").strip(),
                excel=excel,
            )
            resultats.append(rapport.to_dict())

        succes = sum(1 for r in resultats if r.get("succes"))
        charge = {
            "recus": len(resultats),
            "traites": succes,
            "en_erreur": len(resultats) - succes,
            "lignes_ajoutees": sum(
                (r.get("statistiques") or {}).get("lignes_ecrites", 0) for r in resultats
            ),
            "rapports": resultats,
        }
        return JSONResponse(charge, status_code=200 if succes else 422)

    # ------------------------------------------------------------------ #
    # Supervision
    # ------------------------------------------------------------------ #

    @application.get("/api/stats")
    async def stats() -> dict[str, Any]:
        return await run_in_threadpool(excel.statistiques)

    @application.get("/api/excel")
    async def telecharger_excel() -> FileResponse:
        if not EXCEL_PATH.is_file():
            raise HTTPException(
                status_code=404,
                detail="Le fichier Excel général n'existe pas encore : déposez une facture.",
            )
        return FileResponse(
            EXCEL_PATH,
            filename=EXCEL_PATH.name,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    @application.get("/api/rapports")
    async def lister_rapports(limite: int = 50) -> dict[str, Any]:
        if not REPORT_DIR.is_dir():
            return {"rapports": []}
        fichiers = sorted(
            REPORT_DIR.glob("*.rapport*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[: max(1, min(limite, 500))]
        return {
            "rapports": [
                {
                    "nom": f.name,
                    "modifie": datetime.fromtimestamp(f.stat().st_mtime).isoformat(
                        timespec="seconds"
                    ),
                    "taille_octets": f.stat().st_size,
                }
                for f in fichiers
            ]
        }

    @application.get("/api/rapports/{nom}")
    async def lire_rapport(nom: str) -> FileResponse:
        cible = (REPORT_DIR / Path(nom).name).resolve()
        if not str(cible).startswith(str(REPORT_DIR.resolve())) or not cible.is_file():
            raise HTTPException(status_code=404, detail="Rapport introuvable.")
        return FileResponse(cible, media_type="application/json", filename=cible.name)

    return application


app = creer_application()
