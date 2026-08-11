"""Mode « dossier partagé » : surveille `data/inbox/` et traite tout nouveau fichier.

Utile pour les postes qui déposent leurs scans sur un partage réseau plutôt que
via le navigateur. Lancement ::

    python -m camwater.watcher --intervalle 10

Le fichier n'est pris en compte que lorsque sa taille est stable entre deux
scrutations : cela évite de traiter une copie réseau encore en cours.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Optional

from .config import ALLOWED_EXTENSIONS, INBOX_DIR, ensure_directories
from .excel_manager import ExcelManager
from .logging_setup import configurer_logs
from .pipeline import traiter_fichier

logger = logging.getLogger(__name__)


def _fichiers_candidats(dossier: Path) -> list[Path]:
    return sorted(
        chemin
        for chemin in dossier.iterdir()
        if chemin.is_file()
        and chemin.suffix.lower() in ALLOWED_EXTENSIONS
        and not chemin.name.startswith(".")
    )


def surveiller(
    dossier: Optional[Path] = None,
    intervalle: float = 10.0,
    annee: Optional[int] = None,
    administration: Optional[str] = None,
    utilisateur: str = "dossier-partage",
    boucle_unique: bool = False,
) -> int:
    """Boucle de surveillance. Retourne le nombre de fichiers traités."""
    ensure_directories()
    dossier = Path(dossier) if dossier else INBOX_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    excel = ExcelManager()
    tailles: dict[Path, int] = {}
    total = 0

    logger.info("Surveillance de %s (intervalle %.1fs)", dossier, intervalle)
    while True:
        try:
            for chemin in _fichiers_candidats(dossier):
                taille = chemin.stat().st_size
                if tailles.get(chemin) != taille:
                    # Copie probablement en cours : on attend le prochain tour.
                    tailles[chemin] = taille
                    continue
                tailles.pop(chemin, None)
                rapport = traiter_fichier(
                    chemin,
                    annee=annee,
                    administration=administration,
                    utilisateur=utilisateur,
                    excel=excel,
                )
                total += 1
                logger.info(rapport.resume())
        except OSError as exc:
            logger.error("Erreur d'accès au dossier surveillé : %s", exc)

        if boucle_unique:
            return total
        time.sleep(intervalle)


def main() -> None:
    analyseur = argparse.ArgumentParser(
        description="Surveille un dossier et intègre les factures CAMWATER déposées."
    )
    analyseur.add_argument("--dossier", type=Path, default=INBOX_DIR, help="Dossier surveillé")
    analyseur.add_argument(
        "--intervalle", type=float, default=10.0, help="Délai entre deux scrutations (s)"
    )
    analyseur.add_argument("--annee", type=int, default=None, help="Année de repli")
    analyseur.add_argument(
        "--administration", default=None, help="Ministère de repli si le mapping échoue"
    )
    analyseur.add_argument(
        "--une-passe",
        action="store_true",
        help="Traiter les fichiers présents puis quitter",
    )
    arguments = analyseur.parse_args()

    configurer_logs()
    surveiller(
        dossier=arguments.dossier,
        intervalle=arguments.intervalle,
        annee=arguments.annee,
        administration=arguments.administration,
        boucle_unique=arguments.une_passe,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
