"""Préparation des images avant envoi au modèle de lecture visuelle.

Deux leviers, tous deux propres à des scans de factures tamponnés :

1. **Résolution utile** — le modèle lit jusqu'à 2576 px sur le grand côté.
   En deçà, on gaspille de la finesse sur des chiffres déjà difficiles ; au-delà,
   c'est le service qui réduit l'image, sans que l'on maîtrise le filtre.
   On rend donc la page en haute définition puis on réduit soi-même en Lanczos :
   ce sur-échantillonnage préserve mieux les traits fins qu'un rendu direct à la
   taille cible.

2. **Atténuation du tampon bleu** — l'encre bleue réfléchit le bleu : dans le
   canal BLEU elle est presque aussi claire que le papier et s'efface, alors que
   le texte noir y reste sombre. Ne garder que ce canal fait donc pâlir le
   tampon sans toucher aux chiffres. Le gain dépend de la teinte réelle du
   tampon : l'option est désactivée par défaut et doit être validée à l'œil sur
   vos propres scans (`tools/apercu_pretraitement.py`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import ATTENUER_TAMPON, MAX_COTE_LONG

logger = logging.getLogger(__name__)

__all__ = ["attenuer_tampon", "optimiser_image", "redimensionner"]


def redimensionner(image, cote_long: int = MAX_COTE_LONG):
    """Ramène le grand côté à `cote_long` par filtre de Lanczos.

    N'agrandit jamais : une image plus petite ne gagne aucune information à
    être étirée, et cela coûterait des jetons pour rien.
    """
    from PIL import Image

    actuel = max(image.size)
    if actuel <= cote_long:
        return image
    facteur = cote_long / actuel
    taille = (max(1, round(image.width * facteur)), max(1, round(image.height * facteur)))
    return image.resize(taille, Image.LANCZOS)


def attenuer_tampon(image):
    """Fait pâlir le tampon circulaire bleu en ne conservant que le canal BLEU.

    C'est bien le canal bleu, et non le rouge : l'encre bleue **réfléchit** le
    bleu, elle y est donc presque aussi claire que le papier et s'efface ; le
    texte noir, faible sur les trois canaux, reste sombre. Prendre le canal
    rouge produirait l'effet inverse — le tampon y est très sombre et
    masquerait davantage les chiffres.
    """
    from PIL import ImageOps

    if image.mode not in ("RGB", "RGBA"):
        return image
    bleu = image.convert("RGB").split()[2]
    # Étale l'histogramme : le papier redevient franchement blanc, l'encre noire
    # franchement noire, ce qui aide la lecture des chiffres fins.
    return ImageOps.autocontrast(bleu, cutoff=1).convert("RGB")


def optimiser_image(
    source: Path,
    destination: Optional[Path] = None,
    attenuer: Optional[bool] = None,
    cote_long: int = MAX_COTE_LONG,
) -> Path:
    """Prépare une image pour la lecture visuelle ; retourne le fichier à envoyer.

    Si aucune transformation n'est nécessaire (image déjà à la bonne taille et
    atténuation désactivée), le fichier d'origine est renvoyé tel quel — aucune
    recompression inutile.
    """
    attenuer = ATTENUER_TAMPON if attenuer is None else attenuer
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - dépendance déclarée
        logger.warning("Pillow absent : image transmise sans préparation.")
        return source

    try:
        with Image.open(source) as image:
            image.load()
            original = image.size
            travail = attenuer_tampon(image) if attenuer else image.convert("RGB")
            travail = redimensionner(travail, cote_long)

            if travail.size == original and not attenuer:
                return source

            cible = destination or source.with_name(f"{source.stem}_optimisee.png")
            cible.parent.mkdir(parents=True, exist_ok=True)
            travail.save(cible, "PNG", optimize=True)

        logger.info(
            "Image préparée : %s %s -> %s%s",
            source.name,
            f"{original[0]}x{original[1]}",
            f"{travail.size[0]}x{travail.size[1]}",
            " (tampon atténué)" if attenuer else "",
        )
        return cible
    except Exception as exc:
        # Une préparation ratée ne doit jamais empêcher la lecture : on renvoie
        # l'original plutôt que d'interrompre le traitement de la facture.
        logger.warning("Préparation impossible de %s (%s) : image envoyée telle quelle.", source, exc)
        return source
