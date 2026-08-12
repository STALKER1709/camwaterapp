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

__all__ = [
    "ConversionError",
    "Page",
    "compter_pages",
    "poppler_disponible",
    "preparer_pages",
]


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


def compter_pages(source: Path) -> Optional[int]:
    """Nombre de pages du PDF **sans rien rendre**, ou `None` si indéterminable.

    Permet de refuser un document trop long avant d'avoir dépensé la moindre
    mémoire : le contrôle de `MAX_PAGES` n'a de sens que s'il précède le rendu.
    """
    try:
        from pdf2image import pdfinfo_from_path

        return int(pdfinfo_from_path(str(source))["Pages"])
    except Exception as exc:
        logger.debug("Nombre de pages indéterminable pour %s (%s).", source.name, exc)
        return None


def _convertir_pdf(source: Path, destination: Path, dpi: int) -> list[Page]:
    """Convertit un PDF en PNG (un fichier par page) via `pdf2image`/poppler.

    Le rendu écrit **directement sur le disque** (`paths_only`). Sans cela,
    pdf2image construit toutes les pages en mémoire avant de rendre la main :
    à 300 DPI une page A4 pèse 26 Mo décompressée, et la mesure sur un lot de
    12 pages donnait un pic de 900 Mo — près de 3 Go extrapolés à `MAX_PAGES`.
    Page par page, le pic ne dépend plus du nombre de pages.
    """
    from pdf2image import convert_from_path  # import tardif : dépendance lourde

    destination.mkdir(parents=True, exist_ok=True)

    # Contrôle *avant* rendu : c'est tout l'intérêt du garde-fou. Il était
    # auparavant appliqué après coup, donc un document de 100 pages était
    # intégralement rendu avant d'être refusé.
    total = compter_pages(source)
    if total is not None and total > MAX_PAGES:
        raise ConversionError(
            f"Le PDF « {source.name} » contient {total} pages "
            f"(maximum autorisé : {MAX_PAGES})."
        )

    chemins = convert_from_path(
        str(source),
        dpi=dpi,
        output_folder=str(destination),
        fmt="png",
        paths_only=True,
        # Filet quand pdfinfo est indisponible : on ne rend jamais plus que la
        # limite, plus une page pour pouvoir constater le dépassement.
        last_page=None if total is not None else MAX_PAGES + 1,
    )
    if not chemins:
        raise ConversionError(f"Le PDF « {source.name} » ne contient aucune page.")
    if len(chemins) > MAX_PAGES:
        raise ConversionError(
            f"Le PDF « {source.name} » dépasse {MAX_PAGES} pages "
            f"(maximum autorisé : {MAX_PAGES})."
        )

    pages: list[Page] = []
    for numero, brut in enumerate(chemins, start=1):
        brut = Path(brut)
        # Réduction maîtrisée à la taille lue par le modèle (cf. image_utils),
        # une page à la fois : rien n'est conservé d'une itération à l'autre.
        cible = optimiser_image(brut, destination / f"page_{numero:03d}_prete.png")
        if cible != brut:
            brut.unlink(missing_ok=True)  # le plein format n'a plus d'usage
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
