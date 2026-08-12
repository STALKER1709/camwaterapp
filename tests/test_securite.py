"""Contrôle d'accès à l'interface web.

Le classeur général et les rapports contiennent des numéros de compte, des
montants et la ventilation par ministère de toutes les administrations. Sans
protection, n'importe quelle machine du réseau pouvait les télécharger.

La règle tient en une phrase : **sans mot de passe, l'application n'écoute que
la machine locale**. Un poste unique fonctionne donc sans configuration et sans
être exposé ; ouvrir aux autres postes suppose un acte délibéré.

Ces tests portent sur les deux volets — l'adresse d'écoute et l'authentification
— et surtout sur les cas où le dispositif pourrait se croire actif sans l'être.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from camwater import securite
from camwater.securite import CHEMINS_LIBRES, acces_autorise, hote_effectif


def _basic(utilisateur: str, mot_de_passe: str) -> str:
    jeton = base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode("utf-8")).decode("ascii")
    return f"Basic {jeton}"


@pytest.fixture
def protege(monkeypatch):
    """Active l'authentification avec un mot de passe connu."""
    monkeypatch.setattr(securite, "AUTH_ACTIVE", True)
    monkeypatch.setattr(securite, "AUTH_UTILISATEUR", "camwater")
    monkeypatch.setattr(securite, "AUTH_MOT_DE_PASSE", "mot-de-passe-solide")


# --------------------------------------------------------------------------- #
# Adresse d'écoute : sûr par défaut
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("demande", ["0.0.0.0", "192.168.1.20", "::"])
def test_sans_mot_de_passe_l_ecoute_est_ramenee_au_local(demande):
    hote, avertissement = hote_effectif(demande)

    assert hote == "127.0.0.1"
    assert avertissement is not None
    assert "CAMWATER_MOT_DE_PASSE" in avertissement, "le message doit dire quoi faire"


@pytest.mark.parametrize("demande", ["127.0.0.1", "localhost", "::1"])
def test_une_demande_locale_n_est_pas_avertie(demande):
    """Rien d'anormal à écouter en local sans mot de passe : pas de bruit."""
    hote, avertissement = hote_effectif(demande)

    assert hote == demande
    assert avertissement is None


def test_avec_mot_de_passe_l_ecoute_reseau_est_accordee(protege):
    hote, avertissement = hote_effectif("0.0.0.0")

    assert hote == "0.0.0.0"
    assert avertissement is None


def test_l_application_demarre_quand_meme():
    """On refuse d'exposer le classeur, pas de fonctionner."""
    hote, _ = hote_effectif("0.0.0.0")
    assert hote, "un hôte utilisable doit toujours être retourné"


# --------------------------------------------------------------------------- #
# Authentification
# --------------------------------------------------------------------------- #


def test_sans_mot_de_passe_tout_passe():
    """L'agent devant le poste ne doit pas s'authentifier auprès de lui-même."""
    assert acces_autorise("/api/excel", None) is True


def test_identifiants_corrects_acceptes(protege):
    assert acces_autorise("/api/excel", _basic("camwater", "mot-de-passe-solide")) is True


@pytest.mark.parametrize(
    "entete",
    [
        None,
        "",
        "Basic",
        "Bearer un-jeton",
        "Basic pas-du-base64!!",
        _basic("camwater", "mauvais"),
        _basic("intrus", "mot-de-passe-solide"),
        _basic("camwater", ""),
        _basic("", ""),
        # Base64 valide mais sans séparateur « : »
        f"Basic {base64.b64encode(b'camwater').decode()}",
    ],
)
def test_acces_refuse(protege, entete):
    assert acces_autorise("/api/excel", entete) is False


def test_la_sonde_de_disponibilite_reste_ouverte(protege):
    """Un outil de supervision doit pouvoir interroger /health sans secret."""
    assert acces_autorise("/health", None) is True
    assert CHEMINS_LIBRES == {"/health"}, "la liste doit rester minimale"


def test_un_prefixe_du_mot_de_passe_ne_suffit_pas(protege):
    """Garde-fou contre une comparaison qui s'arrêterait au premier écart."""
    assert acces_autorise("/api/excel", _basic("camwater", "mot-de-passe-solid")) is False
    assert acces_autorise("/api/excel", _basic("camwater", "m")) is False


# --------------------------------------------------------------------------- #
# Bout en bout, à travers l'application HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
def client_protege(tmp_path, monkeypatch):
    from camwater import api, config

    for nom in ("DATA_DIR", "UPLOAD_DIR", "PROCESSED_DIR", "ERROR_DIR",
                "OUTPUT_DIR", "REPORT_DIR", "INBOX_DIR", "LOG_DIR"):
        monkeypatch.setattr(config, nom, tmp_path / nom.lower(), raising=False)
    monkeypatch.setattr(config, "ALL_DIRS", tuple(
        getattr(config, n) for n in ("DATA_DIR", "UPLOAD_DIR", "PROCESSED_DIR",
                                     "ERROR_DIR", "OUTPUT_DIR", "REPORT_DIR",
                                     "INBOX_DIR", "LOG_DIR")))
    # Pas besoin de remplacer `api.acces_autorise` : il pointe déjà sur la
    # fonction de `securite`, dont on règle ici les constantes de module.
    monkeypatch.setattr(securite, "AUTH_ACTIVE", True)
    monkeypatch.setattr(securite, "AUTH_UTILISATEUR", "camwater")
    monkeypatch.setattr(securite, "AUTH_MOT_DE_PASSE", "mot-de-passe-solide")
    return TestClient(api.creer_application())


@pytest.mark.parametrize("chemin", ["/", "/api/stats", "/api/rapports", "/docs", "/openapi.json"])
def test_les_endpoints_sont_proteges(client_protege, chemin):
    reponse = client_protege.get(chemin)

    assert reponse.status_code == 401
    # Sans cet en-tête, le navigateur affiche une erreur au lieu de demander
    # les identifiants.
    assert reponse.headers["WWW-Authenticate"].startswith("Basic")


def test_le_classeur_n_est_pas_telechargeable_sans_mot_de_passe(client_protege):
    assert client_protege.get("/api/excel").status_code == 401


def test_le_depot_de_facture_est_protege(client_protege):
    reponse = client_protege.post(
        "/api/upload", files={"fichiers": ("f.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    assert reponse.status_code == 401


def test_avec_les_bons_identifiants_l_acces_est_rendu(client_protege):
    reponse = client_protege.get("/api/stats", auth=("camwater", "mot-de-passe-solide"))
    assert reponse.status_code == 200


def test_health_reste_interrogeable(client_protege):
    assert client_protege.get("/health").status_code == 200
