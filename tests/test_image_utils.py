"""Tests de la préparation d'image avant lecture visuelle.

Le point sensible est le **choix du canal** pour atténuer le tampon bleu : une
première version utilisait le canal rouge, ce qui assombrissait le tampon au
lieu de l'effacer — exactement l'inverse du but recherché. Les tests ci-dessous
mesurent l'effet réel plutôt que de faire confiance au raisonnement.
"""

import pytest
from PIL import Image, ImageDraw, ImageStat

from camwater.image_utils import attenuer_tampon, optimiser_image, redimensionner

# Zones connues de l'image de test construite par la fixture.
ZONE_TAMPON = (312, 90, 328, 200)
ZONE_TEXTE = (70, 65, 250, 85)
ZONE_PAPIER = (450, 90, 550, 200)


@pytest.fixture
def scan_tamponne():
    """Reproduit la configuration réelle : chiffres noirs sous un trait bleu."""
    image = Image.new("RGB", (600, 300), "white")
    ImageDraw.Draw(image).rectangle([60, 60, 260, 90], fill=(25, 25, 25))
    tampon = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(tampon).line([(320, 40), (320, 260)], fill=(40, 70, 190, 205), width=26)
    return Image.alpha_composite(image.convert("RGBA"), tampon).convert("RGB")


def _clarte(image, zone):
    """Luminosité moyenne d'une zone : 0 = noir, 255 = blanc."""
    return ImageStat.Stat(image.convert("L").crop(zone)).mean[0]


def test_le_tampon_palit(scan_tamponne):
    """Régression : avec le canal rouge, le tampon s'assombrissait (110 -> 104)."""
    avant = _clarte(scan_tamponne, ZONE_TAMPON)
    apres = _clarte(attenuer_tampon(scan_tamponne), ZONE_TAMPON)
    assert apres > avant, f"le tampon doit pâlir, pas s'assombrir ({avant:.0f} -> {apres:.0f})"


def test_les_chiffres_restent_sombres(scan_tamponne):
    apres = _clarte(attenuer_tampon(scan_tamponne), ZONE_TEXTE)
    assert apres < 60, f"le texte noir doit rester sombre (obtenu {apres:.0f})"


def test_le_contraste_tampon_texte_augmente(scan_tamponne):
    traite = attenuer_tampon(scan_tamponne)
    avant = _clarte(scan_tamponne, ZONE_TAMPON) - _clarte(scan_tamponne, ZONE_TEXTE)
    apres = _clarte(traite, ZONE_TAMPON) - _clarte(traite, ZONE_TEXTE)
    assert apres > avant * 1.5, f"contraste insuffisamment amélioré ({avant:.0f} -> {apres:.0f})"


def test_le_tampon_se_rapproche_du_papier(scan_tamponne):
    """Un tampon qui « disparaît » tend vers la clarté du papier."""
    traite = attenuer_tampon(scan_tamponne)
    avant = abs(_clarte(scan_tamponne, ZONE_TAMPON) - _clarte(scan_tamponne, ZONE_PAPIER))
    apres = abs(_clarte(traite, ZONE_TAMPON) - _clarte(traite, ZONE_PAPIER))
    assert apres < avant


def test_redimensionnement_reduit_au_cote_long():
    image = Image.new("RGB", (4000, 3000), "white")
    reduite = redimensionner(image, 2576)
    assert max(reduite.size) == 2576
    assert reduite.size == (2576, 1932)          # proportions conservées


def test_jamais_d_agrandissement():
    """Étirer une image n'ajoute aucune information et coûte des jetons."""
    image = Image.new("RGB", (1000, 700), "white")
    assert redimensionner(image, 2576).size == (1000, 700)


def test_image_deja_conforme_non_recompressee(tmp_path):
    source = tmp_path / "page.png"
    Image.new("RGB", (1200, 900), "white").save(source)
    assert optimiser_image(source, attenuer=False) == source


def test_grande_image_reduite_sur_disque(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (4000, 3000), "white").save(source)
    cible = optimiser_image(source, tmp_path / "prete.png", attenuer=False)

    assert cible != source
    with Image.open(cible) as reduite:
        assert max(reduite.size) == 2576


def test_fichier_illisible_renvoie_l_original(tmp_path):
    """Une préparation ratée ne doit jamais bloquer le traitement de la facture."""
    source = tmp_path / "corrompu.png"
    source.write_bytes(b"ceci n'est pas une image")
    assert optimiser_image(source, tmp_path / "prete.png") == source
