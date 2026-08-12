"""Conversion PDF → images : bornes mémoire et garde-fou sur le nombre de pages.

Le rendu à 300 DPI est coûteux : une page A4 pèse 26 Mo décompressée. Deux
exigences en découlent, et ce sont exactement les deux défauts corrigés :

1. le pic mémoire ne doit pas dépendre du nombre de pages — pdf2image
   construisait auparavant **toutes** les pages avant de rendre la main
   (mesuré : 900 Mo pour 12 pages) ;
2. le contrôle de `MAX_PAGES` doit précéder le rendu — il intervenait après,
   si bien qu'un document de 100 pages était intégralement rendu avant d'être
   refusé, ce qui vidait le garde-fou de son sens.

Les tests s'exécutent sans poppler : le rendu est simulé, seule la
**discipline d'appel** est vérifiée. Le comportement réel a été mesuré sur des
PDF de 12 et 36 pages (pic constant à ~113 Mo, refus en 0,03 s et 3 Mo).
"""

from pathlib import Path

import pytest

from camwater import pdf_utils
from camwater.pdf_utils import ConversionError, compter_pages, preparer_pages


@pytest.fixture
def pdf(tmp_path):
    chemin = tmp_path / "lot.pdf"
    chemin.write_bytes("%PDF-1.4\n% factice, le rendu est simulé\n".encode("utf-8"))
    return chemin


@pytest.fixture
def poppler(monkeypatch):
    """Simule poppler et enregistre les arguments de rendu réellement passés."""
    monkeypatch.setattr(pdf_utils, "poppler_disponible", lambda: True)
    appels: list[dict] = []

    def rendu(source, **arguments):
        appels.append(arguments)
        dossier = Path(arguments["output_folder"])
        demandees = arguments.get("last_page") or 1000
        produites = min(_pages_du_document[0], demandees)
        chemins = []
        for numero in range(1, produites + 1):
            page = dossier / f"brut_{numero:03d}.png"
            page.write_bytes(b"\x89PNG\r\n\x1a\n" + b"P" * 64)
            chemins.append(str(page))
        return chemins

    import pdf2image

    monkeypatch.setattr(pdf2image, "convert_from_path", rendu)
    monkeypatch.setattr(pdf_utils, "optimiser_image", lambda brut, cible: cible.write_bytes(
        b"\x89PNG\r\n\x1a\n") or cible)
    return appels


#: Nombre de pages du document simulé, réglé par chaque test.
_pages_du_document = [3]


@pytest.fixture(autouse=True)
def document_de_trois_pages():
    _pages_du_document[0] = 3
    yield
    _pages_du_document[0] = 3


# --------------------------------------------------------------------------- #
# Le rendu écrit sur le disque, pas en mémoire
# --------------------------------------------------------------------------- #


def test_le_rendu_ecrit_directement_sur_le_disque(pdf, tmp_path, poppler, monkeypatch):
    """`paths_only` : sans lui, les N pages sont d'abord construites en mémoire."""
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 3)
    preparer_pages(pdf, tmp_path / "travail")

    assert poppler[0]["paths_only"] is True
    assert poppler[0]["output_folder"], "poppler doit écrire dans un dossier de travail"


def test_le_plein_format_est_supprime_apres_reduction(pdf, tmp_path, poppler, monkeypatch):
    """Le fichier 300 DPI n'a plus d'usage une fois la page réduite."""
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 3)
    travail = tmp_path / "travail"
    pages = preparer_pages(pdf, travail)

    assert len(pages) == 3
    assert not list(travail.glob("brut_*.png")), "les pleins formats doivent être libérés"
    assert len(list(travail.glob("*_prete.png"))) == 3


# --------------------------------------------------------------------------- #
# Le garde-fou précède le rendu
# --------------------------------------------------------------------------- #


def test_document_trop_long_refuse_sans_rendu(pdf, tmp_path, poppler, monkeypatch):
    """Régression : les 100 pages étaient rendues avant d'être refusées."""
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 100)
    monkeypatch.setattr(pdf_utils, "MAX_PAGES", 40)

    with pytest.raises(ConversionError) as echec:
        preparer_pages(pdf, tmp_path / "travail")

    assert "100 pages" in str(echec.value)
    assert poppler == [], "aucun rendu ne doit avoir été demandé"


def test_document_dans_la_limite_est_rendu_en_entier(pdf, tmp_path, poppler, monkeypatch):
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 3)
    monkeypatch.setattr(pdf_utils, "MAX_PAGES", 40)

    assert len(preparer_pages(pdf, tmp_path / "travail")) == 3
    assert poppler[0]["last_page"] is None, "aucune borne quand le total est connu"


def test_sans_pdfinfo_le_rendu_reste_borne(pdf, tmp_path, poppler, monkeypatch):
    """Filet : pdfinfo indisponible ne doit pas rendre le garde-fou inopérant."""
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: None)
    monkeypatch.setattr(pdf_utils, "MAX_PAGES", 5)
    _pages_du_document[0] = 36

    with pytest.raises(ConversionError) as echec:
        preparer_pages(pdf, tmp_path / "travail")

    assert "dépasse 5 pages" in str(echec.value)
    assert poppler[0]["last_page"] == 6, "on ne rend jamais plus que la limite + 1"


def test_pdf_sans_page_signale(pdf, tmp_path, poppler, monkeypatch):
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 0)
    _pages_du_document[0] = 0

    with pytest.raises(ConversionError, match="aucune page"):
        preparer_pages(pdf, tmp_path / "travail")


# --------------------------------------------------------------------------- #
# Comptage des pages
# --------------------------------------------------------------------------- #


def test_comptage_impossible_ne_leve_pas(tmp_path):
    """Un PDF illisible par pdfinfo doit renvoyer None, pas exploser."""
    corrompu = tmp_path / "corrompu.pdf"
    corrompu.write_bytes(b"ceci n'est pas un PDF")

    assert compter_pages(corrompu) is None


def test_echec_de_conversion_bascule_sur_le_pdf_natif(pdf, tmp_path, monkeypatch):
    """Une erreur de rendu ne bloque pas : le modèle sait lire un PDF."""
    monkeypatch.setattr(pdf_utils, "poppler_disponible", lambda: True)
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 3)

    import pdf2image

    def rendu_casse(source, **arguments):
        raise RuntimeError("pdftoppm a échoué")

    monkeypatch.setattr(pdf2image, "convert_from_path", rendu_casse)
    pages = preparer_pages(pdf, tmp_path / "travail")

    assert len(pages) == 1
    assert pages[0].est_pdf


def test_document_trop_long_n_est_pas_rattrape_par_le_repli(pdf, tmp_path, poppler, monkeypatch):
    """Un refus délibéré ne doit pas se transformer en lecture native du PDF."""
    monkeypatch.setattr(pdf_utils, "compter_pages", lambda source: 100)
    monkeypatch.setattr(pdf_utils, "MAX_PAGES", 40)

    with pytest.raises(ConversionError):
        preparer_pages(pdf, tmp_path / "travail")
