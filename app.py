"""Point d'entrée de l'application CAMWATER.

Lancement en une commande ::

    python app.py

Options utiles (ou variables d'environnement équivalentes) ::

    python app.py --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import argparse
import os
import sys

from camwater.config import ANTHROPIC_API_KEY, EXCEL_PATH, LLM_MODEL, ensure_directories
from camwater.logging_setup import configurer_logs


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Serveur d'extraction de factures CAMWATER")
    analyseur.add_argument("--host", default=os.getenv("CAMWATER_HOST", "0.0.0.0"))
    analyseur.add_argument("--port", type=int, default=int(os.getenv("CAMWATER_PORT", "8000")))
    analyseur.add_argument("--reload", action="store_true", help="Rechargement à chaud (dev)")
    arguments = analyseur.parse_args()

    logger = configurer_logs()
    ensure_directories()

    if not ANTHROPIC_API_KEY:
        logger.warning(
            "ANTHROPIC_API_KEY n'est pas défini. La lecture visuelle échouera tant "
            "qu'aucune authentification (clé API ou profil `ant auth login`) n'est disponible."
        )

    logger.info("Modèle de lecture : %s", LLM_MODEL)
    logger.info("Excel général     : %s", EXCEL_PATH)
    logger.info("Interface web     : http://%s:%d/", arguments.host, arguments.port)

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn n'est pas installé : pip install -r requirements.txt")
        return 1

    uvicorn.run(
        "camwater.api:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_config=None,  # on garde la configuration de logging_setup
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
