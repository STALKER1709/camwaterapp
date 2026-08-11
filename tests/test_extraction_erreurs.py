"""Tests du traitement des erreurs d'accès à l'API de lecture visuelle.

Deux exigences :

* une erreur **définitive** (crédit épuisé, clé absente ou invalide, droits
  insuffisants) doit remonter immédiatement, sans réessai, avec une consigne
  d'action en français — et non le JSON brut de l'API ;
* une erreur **transitoire** (débit dépassé, surcharge, coupure réseau) doit au
  contraire être réessayée.
"""

import pytest

from camwater import extraction
from camwater.extraction import ExtractionError, _erreur_definitive, extraire_page
from camwater.pdf_utils import Page


# Messages réellement renvoyés par l'API, recopiés depuis des cas observés.
CREDIT_EPUISE = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.'}, "
    "'request_id': 'req_011CdwUq1riMhD3QcmZxZjEZ'}"
)
CLE_ABSENTE = (
    "Could not resolve authentication method. Expected one of api_key, auth_token "
    "or credentials to be set."
)
CLE_INVALIDE = (
    "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
    "'message': 'invalid x-api-key'}}"
)


@pytest.mark.parametrize(
    "message, attendu",
    [
        (CREDIT_EPUISE, "crédit"),
        (CLE_ABSENTE, "ANTHROPIC_API_KEY"),
        (CLE_INVALIDE, "invalide"),
        ("Error code: 403 - {'type': 'permission_error'}", "droits"),
        ("Error code: 404 - {'type': 'not_found_error'}", "introuvable"),
    ],
)
def test_erreurs_definitives_reconnues(message, attendu):
    consigne = _erreur_definitive(Exception(message))
    assert consigne is not None, f"non reconnue : {message[:60]}"
    assert attendu.lower() in consigne.lower()
    # La consigne doit être actionnable, pas un simple constat.
    assert any(mot in consigne for mot in ("platform.claude.com", ".env"))


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 - rate_limit_error",
        "Error code: 529 - overloaded_error",
        "Connection error.",
        "Request timed out.",
    ],
)
def test_erreurs_transitoires_non_classees_definitives(message):
    assert _erreur_definitive(Exception(message)) is None


def _page_factice(tmp_path):
    chemin = tmp_path / "page.png"
    chemin.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return Page(numero=1, chemin=chemin, media_type="image/png")


class _ClientQuiEchoue:
    """Client factice comptant les appels réellement tentés."""

    def __init__(self, message):
        self.message = message
        self.appels = 0
        self.messages = self

    def stream(self, **_):
        self.appels += 1
        raise RuntimeError(self.message)


def test_credit_epuise_ne_declenche_aucun_reessai(tmp_path, monkeypatch):
    """Réessayer une erreur de crédit est inutile : un seul appel doit partir."""
    client = _ClientQuiEchoue(CREDIT_EPUISE)
    monkeypatch.setattr(extraction, "_obtenir_client", lambda: client)

    with pytest.raises(ExtractionError) as erreur:
        extraire_page(_page_factice(tmp_path))

    assert client.appels == 1, f"{client.appels} tentative(s) au lieu d'une seule"
    texte = str(erreur.value)
    assert "crédit" in texte.lower()
    assert "platform.claude.com" in texte
    # Le JSON brut de l'API ne doit pas être exposé à l'utilisateur.
    assert "invalid_request_error" not in texte
    assert "request_id" not in texte


def test_erreur_transitoire_est_reessayee(tmp_path, monkeypatch):
    client = _ClientQuiEchoue("Error code: 529 - overloaded_error")
    monkeypatch.setattr(extraction, "_obtenir_client", lambda: client)
    monkeypatch.setattr(extraction, "LLM_MAX_RETRIES", 3)
    monkeypatch.setattr(extraction.time, "sleep", lambda _: None)  # pas d'attente

    with pytest.raises(ExtractionError):
        extraire_page(_page_factice(tmp_path))

    assert client.appels == 3, f"{client.appels} tentative(s) au lieu de 3"
