"""Conversion PDF → images PNG et préparation des pages à envoyer au LLM."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import IMAGE_EXTENSIONS, MAX_PAGES, MEDIA_TYPES, PDF_DPI, PDF_EXTENSIONS
from .image_utils import optimiser_image

logger = logging.getLogger(__name__)

__all__ = ["Page", "ConversionError", "poppler_disponible", "preparer_pages"]


class ConversionError(RuntimeError):
    """Le fichier n'a pas pu être converti en pages exploitables."""


@dataclass
class Page:
    """Une page à soumettre au LLM.

    `chemin` pointe soit vers une image PNG/JPEG, soit vers le PDF d'origine
    lorsque la conversion n'est pas possible (repli sur la lecture native du PDF
    par le modèle, qui accepte les documents PDF en entrée).
    """

    numero: int
    chemin: Path
    media_type: str

    @property
    def est_pdf(self) -> bool:
        return self.media_type == "application/pdf"


def poppler_disponible() -> bool:
    """`pdftoppm` (poppler-utils) est-il installé sur la machine ?"""
    return shutil.which("pdftoppm") is not None


def _convertir_pdf(source: Path, destination: Path, dpi: int) -> list[Page]:
    """Convertit un PDF en PNG (un fichier par page) via `pdf2image`/poppler."""
    from pdf2image import convert_from_path  # import tardif : dépendance lourde

    destination.mkdir(parents=True, exist_ok=True)
    images = convert_from_path(str(source), dpi=dpi)
    if not images:
        raise ConversionError(f"Le PDF « {source.name} » ne contient aucune page.")
    if len(images) > MAX_PAGES:
        raise ConversionError(
            f"Le PDF « {source.name} » contient {len(images)} pages "
            f"(maximum autorisé : {MAX_PAGES})."
        )

    pages: list[Page] = []
    for numero, image in enumerate(images, start=1):
        cible = destination / f"page_{numero:03d}.png"
        image.save(cible, "PNG")
        # Réduction maîtrisée à la taille lue par le modèle (cf. image_utils).
        cible = optimiser_image(cible, destination / f"page_{numero:03d}_prete.png")
        pages.append(Page(numero=numero, chemin=cible, media_type="image/png"))
    logger.info("PDF converti : %s → %d page(s) PNG à %d DPI", source.name, len(pages), dpi)
    return pages


def preparer_pages(source: Path, dossier_travail: Path, dpi: int = PDF_DPI) -> list[Page]:
    """Retourne la liste des pages exploitables pour un fichier reçu.

    * image (PNG/JPG/JPEG) → une seule page, le fichier lui-même ;
    * PDF → conversion en PNG à `dpi` points par pouce ;
    * PDF non convertible (poppler absent ou en erreur) → repli sur l'envoi du
      PDF natif au modèle, en journalisant clairement la raison.
    """
    extension = source.suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        # Une photo de téléphone dépasse souvent la taille lue par le modèle :
        # la réduire ici évite une réduction non maîtrisée côté service, et
        # allège la facturation en jetons image.
        dossier_travail.mkdir(parents=True, exist_ok=True)
        prete = optimiser_image(source, dossier_travail / f"{source.stem}_prete.png")
        media = "image/png" if prete != source else MEDIA_TYPES[extension]
        return [Page(numero=1, chemin=prete, media_type=media)]

    if extension not in PDF_EXTENSIONS:
        raise ConversionError(f"Extension non prise en charge : « {extension} ».")

    if poppler_disponible():
        try:
            return _convertir_pdf(source, dossier_travail, dpi)
        except ConversionError:
            raise
        except Exception as exc:  # pdf2image remonte des erreurs très variées
            logger.warning(
                "Conversion PDF→PNG impossible pour %s (%s) — repli sur la lecture "
                "native du PDF par le modèle.",
                source.name,
                exc,
            )
    else:
        logger.warning(
            "poppler-utils (pdftoppm) est absent : repli sur la lecture native du "
            "PDF par le modèle. Installez poppler pour la conversion à %d DPI.",
            dpi,
        )

    return [Page(numero=1, chemin=source, media_type="application/pdf")]
