"""Compare visuellement une facture avant et après préparation de l'image.

À lancer sur **vos** scans avant d'activer `CAMWATER_ATTENUER_TAMPON` : l'effet
de l'atténuation dépend de la teinte réelle du tampon, que seul votre œil peut
juger sur pièce ::

    python tools/apercu_pretraitement.py data/errors/MinSante.pdf

Produit dans `data/apercus/` :

* `..._1_original.png`  — le rendu tel qu'il est envoyé aujourd'hui ;
* `..._2_optimisee.png` — après mise à la résolution utile ;
* `..._3_tampon.png`    — après atténuation du tampon bleu.

Ouvrez les trois côte à côte et jugez : les chiffres masqués sont-ils plus
lisibles ? Si l'atténuation dégrade quoi que ce soit, laissez l'option à `false`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camwater.config import DATA_DIR, MAX_COTE_LONG, PDF_DPI  # noqa: E402
from camwater.image_utils import attenuer_tampon, redimensionner  # noqa: E402
from camwater.logging_setup import configurer_logs  # noqa: E402
from camwater.pdf_utils import poppler_disponible  # noqa: E402


def _premiere_page(source: Path, dossier: Path) -> Path:
    """Rend la première page en image, quel que soit le format d'entrée."""
    if source.suffix.lower() != ".pdf":
        return source
    if not poppler_disponible():
        raise SystemExit(
            "poppler-utils est requis pour convertir un PDF.\n"
            "Windows : télécharger poppler et ajouter son dossier bin au PATH."
        )
    from pdf2image import convert_from_path

    images = convert_from_path(str(source), dpi=PDF_DPI, first_page=1, last_page=1)
    if not images:
        raise SystemExit(f"Aucune page lisible dans « {source.name} ».")
    brut = dossier / f"{source.stem}_page1_brut.png"
    images[0].save(brut, "PNG")
    return brut


def main() -> int:
    configurer_logs()
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    source = Path(sys.argv[1]).expanduser()
    if not source.is_file():
        raise SystemExit(f"Fichier introuvable : {source}")

    dossier = DATA_DIR / "apercus"
    dossier.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    page = _premiere_page(source, dossier)
    base = source.stem

    with Image.open(page) as image:
        image.load()
        original = image.convert("RGB")

        chemins = {
            "1_original": original,
            "2_optimisee": redimensionner(original, MAX_COTE_LONG),
            "3_tampon": redimensionner(attenuer_tampon(original), MAX_COTE_LONG),
        }
        print(f"\nAperçus de « {source.name} » ({original.width}x{original.height} px) :\n")
        for suffixe, rendu in chemins.items():
            cible = dossier / f"{base}_{suffixe}.png"
            rendu.save(cible, "PNG", optimize=True)
            print(f"  {cible}   {rendu.width}x{rendu.height} px")

    print(
        "\nOuvrez les trois images et comparez la zone couverte par le tampon.\n"
        "Si « 3_tampon » rend les chiffres plus lisibles, activez dans .env :\n"
        "    CAMWATER_ATTENUER_TAMPON=true\n"
        "Dans le doute, laissez l'option désactivée : la version 2 est déjà un\n"
        "gain net par rapport au réglage d'origine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
