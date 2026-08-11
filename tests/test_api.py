"""Tests de l'interface HTTP (traitement simulé)."""

import pytest
from fastapi.testclient import TestClient

from camwater import api
from camwater.models import RapportTraitement


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir()
    return TestClient(api.creer_application())


def test_health(client):
    reponse = client.get("/health")
    assert reponse.status_code == 200
    charge = reponse.json()
    assert charge["statut"] == "ok"
    assert "modele" in charge


def test_page_accueil(client):
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert "CAMWATER" in reponse.text


def test_upload_format_refuse(client):
    reponse = client.post(
        "/api/upload",
        files={"fichiers": ("note.txt", b"contenu", "text/plain")},
    )
    assert reponse.status_code == 422
    rapport = reponse.json()["rapports"][0]
    assert rapport["succes"] is False
    assert "Format non pris en charge" in rapport["erreur"]


def test_upload_fichier_vide(client):
    reponse = client.post(
        "/api/upload",
        files={"fichiers": ("vide.png", b"", "image/png")},
    )
    assert reponse.json()["rapports"][0]["erreur"] == "Fichier vide."


def test_upload_reussi(client, monkeypatch):
    def traitement_simule(chemin, **kwargs):
        rapport = RapportTraitement(fichier=chemin.name, succes=True, pages=1, confiance=0.97)
        rapport.lignes_ecrites = 3
        return rapport

    monkeypatch.setattr(api, "traiter_fichier", traitement_simule)

    reponse = client.post(
        "/api/upload",
        files={"fichiers": ("facture.png", b"\x89PNG\r\n\x1a\n0000", "image/png")},
        data={"annee": "2026", "administration": "MINSANTE", "utilisateur": "poste-2"},
    )

    assert reponse.status_code == 200
    charge = reponse.json()
    assert charge["recus"] == 1
    assert charge["traites"] == 1
    assert charge["lignes_ajoutees"] == 3


def test_upload_multiple(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "traiter_fichier",
        lambda chemin, **kwargs: RapportTraitement(fichier=chemin.name, succes=True),
    )
    reponse = client.post(
        "/api/upload",
        files=[
            ("fichiers", ("a.png", b"\x89PNG1", "image/png")),
            ("fichiers", ("b.jpg", b"\xff\xd8\xff", "image/jpeg")),
        ],
    )
    assert reponse.status_code == 200
    assert reponse.json()["recus"] == 2


def test_excel_absent(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "EXCEL_PATH", tmp_path / "inexistant.xlsx")
    reponse = client.get("/api/excel")
    assert reponse.status_code == 404


def test_stats(client):
    reponse = client.get("/api/stats")
    assert reponse.status_code == 200
    assert "existe" in reponse.json()
