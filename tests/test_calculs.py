"""Tests du parsing des nombres et des formules de facturation."""

from decimal import Decimal

import pytest

from camwater.calculs import arrondi, calculer_ligne, parse_nombre


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1 234", Decimal("1234")),
        ("12 500 FCFA", Decimal("12500")),
        ("1.234", Decimal("1234")),          # groupes de milliers
        ("12.5", Decimal("12.5")),           # décimal, pas des milliers
        ("0", Decimal("0")),
        ("(250)", Decimal("-250")),
        ("-1.000", Decimal("-1000")),
        (382, Decimal("382")),
        (12.5, Decimal("12.5")),
        (Decimal("7"), Decimal("7")),
    ],
)
def test_parse_nombre_formats(brut, attendu):
    assert parse_nombre(brut) == attendu


@pytest.mark.parametrize("brut", [None, "", "   ", "ILLISIBLE", "n/a", "-", "néant", True])
def test_parse_nombre_valeurs_vides(brut):
    assert parse_nombre(brut) is None


def test_arrondi_moitie_superieure():
    assert arrondi(Decimal("0.5")) == Decimal("1")
    assert arrondi(Decimal("1.5")) == Decimal("2")
    assert arrondi(Decimal("2.4")) == Decimal("2")


def test_calcul_nominal_complet():
    """Facture parfaitement lisible : rien n'est dérivé, rien n'est signalé."""
    ligne = calculer_ligne(
        {
            "consommation": "100",
            "location_compteur": "1 000",
            "montant_ht": "39 200",   # 100 × 382 + 1000
            "tva": "7 546",           # ARRONDI(39200 × 0,1925) = 7546
            "montant_ttc": "46 746",
            "index_ancien": "1 000",
            "index_nouvel": "1 100",
        }
    )
    assert ligne.montant_ht == Decimal("39200")
    assert ligne.tva == Decimal("7546")
    assert ligne.montant_ttc == Decimal("46746")
    assert ligne.champs_derives == []
    assert ligne.anomalies == []


def test_montants_derives_depuis_la_consommation():
    ligne = calculer_ligne({"consommation": "50", "location_compteur": "500"})
    assert ligne.montant_ht == Decimal("19600")             # 50×382 + 500
    assert ligne.tva == Decimal("3773")                     # ARRONDI(19600×0,1925)
    assert ligne.montant_ttc == Decimal("23373")
    assert set(ligne.champs_derives) == {"montant_ht", "tva", "montant_ttc"}
    assert ligne.anomalies == []


def test_consommation_derivee_depuis_les_index():
    ligne = calculer_ligne({"index_ancien": "2 000", "index_nouvel": "2 075"})
    assert ligne.consommation == Decimal("75")
    assert "consommation" in ligne.champs_derives


def test_consommation_derivee_depuis_le_montant_ht():
    ligne = calculer_ligne({"montant_ht": "38 200", "location_compteur": "0"})
    assert ligne.consommation == Decimal("100")
    assert "consommation" in ligne.champs_derives


def test_incoherence_tva_signalee():
    ligne = calculer_ligne(
        {"consommation": "100", "location_compteur": "0", "montant_ht": "38 200", "tva": "5 000"}
    )
    assert any("TVA" in anomalie for anomalie in ligne.anomalies)


def test_incoherence_index_signalee():
    ligne = calculer_ligne(
        {"consommation": "100", "index_ancien": "1 000", "index_nouvel": "1 050"}
    )
    assert any("Index" in anomalie for anomalie in ligne.anomalies)


def test_ligne_totalement_illisible():
    ligne = calculer_ligne(
        {"consommation": "ILLISIBLE", "montant_ht": "ILLISIBLE", "tva": "", "montant_ttc": None}
    )
    assert ligne.consommation is None
    assert ligne.montant_ht is None
    assert not ligne.complete
