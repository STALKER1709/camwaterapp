"""Contrôle de la version du SDK Anthropic.

Le code passe `output_config` (schéma JSON imposé + niveau d'effort) et
`cache_control`. Une version trop ancienne du SDK ne les connaît pas et échoue
au premier appel de lecture sur un `TypeError` muet sur la cause — panne
d'autant plus déroutante qu'elle ne survient qu'au dépôt d'une facture, jamais
à l'installation.

Ces tests vérifient que le problème est détecté et **expliqué**, et surtout
qu'il ne bloque jamais à tort.
"""

import pytest

from camwater import extraction
from camwater.extraction import (
    VERSION_SDK_MINIMALE,
    ExtractionError,
    verifier_version_sdk,
)


@pytest.fixture(autouse=True)
def client_non_instancie():
    """Le client est mis en cache dans un global : on repart à zéro."""
    extraction._client = None
    yield
    extraction._client = None


def _version(monkeypatch, valeur):
    monkeypatch.setattr(extraction, "_version_installee", lambda: valeur)


# --------------------------------------------------------------------------- #
# Détection
# --------------------------------------------------------------------------- #


def test_version_installee_est_lisible():
    """Le SDK réellement installé doit satisfaire le plancher déclaré."""
    assert verifier_version_sdk() is None


@pytest.mark.parametrize("trop_ancienne", [(0, 69, 0), (0, 99), (0, 120, 9), (0,)])
def test_version_trop_ancienne_detectee(monkeypatch, trop_ancienne):
    _version(monkeypatch, trop_ancienne)
    message = verifier_version_sdk()

    assert message is not None
    assert ".".join(str(n) for n in VERSION_SDK_MINIMALE) in message


@pytest.mark.parametrize("acceptable", [VERSION_SDK_MINIMALE, (0, 121, 0), (0, 200), (1, 0)])
def test_version_suffisante_acceptee(monkeypatch, acceptable):
    _version(monkeypatch, acceptable)
    assert verifier_version_sdk() is None


def test_version_illisible_ne_bloque_pas(monkeypatch):
    """Ne pas savoir lire un numéro de version n'est pas une raison de refuser."""
    _version(monkeypatch, None)
    assert verifier_version_sdk() is None


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("0.121.0", (0, 121, 0)),
        ("0.69.0", (0, 69, 0)),
        ("1.0", (1, 0)),
        ("0.122.0b1", (0, 122, 0)),      # pré-version : le suffixe est ignoré
        ("0.122.0.dev3", (0, 122, 0)),
        ("inconnue", None),              # illisible → aucun blocage
    ],
)
def test_lecture_du_numero_de_version(monkeypatch, brut, attendu):
    import anthropic

    monkeypatch.setattr(anthropic, "__version__", brut, raising=False)
    assert extraction._version_installee() == attendu


# --------------------------------------------------------------------------- #
# Message et remontée
# --------------------------------------------------------------------------- #


def test_le_message_dit_quoi_faire(monkeypatch):
    _version(monkeypatch, (0, 69, 0))
    message = verifier_version_sdk()

    assert "0.69" in message, "la version fautive doit être citée"
    assert "pip install -r requirements.txt" in message
    assert "demarrer.bat" in message, "le chemin Windows doit être rappelé"


def test_l_appel_echoue_avec_une_cause_intelligible(monkeypatch):
    """Le pipeline présente ce message tel quel : il doit se suffire à lui-même."""
    _version(monkeypatch, (0, 69, 0))

    with pytest.raises(ExtractionError) as echec:
        extraction._obtenir_client()

    assert "trop ancienne" in str(echec.value)
    assert "TypeError" not in str(echec.value)


def test_une_version_a_jour_laisse_passer(monkeypatch):
    _version(monkeypatch, (0, 121, 0))
    monkeypatch.setattr(extraction, "ANTHROPIC_API_KEY", "sk-ant-factice")

    assert extraction._obtenir_client() is not None
