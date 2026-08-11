"""Configuration des journaux : console + `logs/app.log` avec rotation."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR, LOG_FILE

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"
_configure = False


def configurer_logs(niveau: str | None = None) -> logging.Logger:
    """Installe les gestionnaires de logs (idempotent) et retourne le logger racine."""
    global _configure
    racine = logging.getLogger()
    if _configure:
        return racine

    niveau_effectif = (niveau or os.getenv("CAMWATER_LOG_LEVEL", "INFO")).upper()
    racine.setLevel(getattr(logging, niveau_effectif, logging.INFO))
    formateur = logging.Formatter(_FORMAT, datefmt=_DATE)

    # Les messages contiennent des symboles absents de cp1252 (« ≠ », « → »,
    # « − »), encodage par défaut d'une console Windows francophone lorsque la
    # sortie est redirigée (service, `> journal.txt`, pipe). Sans ce forçage en
    # UTF-8, l'écriture du log lèverait UnicodeEncodeError.
    flux = sys.stdout
    try:
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # flux déjà remplacé (tests, pipe exotique)
        pass

    console = logging.StreamHandler(flux)
    console.setFormatter(formateur)
    racine.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fichier = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            errors="replace",
        )
        fichier.setFormatter(formateur)
        racine.addHandler(fichier)
    except OSError as exc:  # disque plein, droits insuffisants…
        racine.warning("Journal fichier indisponible (%s) : logs console uniquement.", exc)

    # Le SDK HTTP est très bavard en DEBUG ; on le calme.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configure = True
    return racine
