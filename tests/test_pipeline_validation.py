"""Tests de la normalisation, de la construction des lignes et de la validation."""

import pytest

from camwater.config import COLONNES, MARQUEUR_A_VERIFIER, MARQUEUR_ILLISIBLE
from camwater.extraction import FactureExtraite
from camwater.models import STATUT_OK, RapportTraitement
from camwater.pipeline import construire_lignes, normaliser_periode
from camwater.validation import controler_totaux, valider_ligne, valider_rapport


@pytest.mark.parametrize(
    "brut, annee, attendu",
    [
        ("mars-2026", None, "mars-2026"),
        ("MARS 2026", None, "mars-2026"),
        ("Mars 2026", None, "mars-2026"),
        ("03/2026", None, "mars-2026"),
        ("2026-03", None, "mars-2026"),
        ("janvier 2025", None, "janv-2025"),
        ("AOUT 2026", None, "août-2026"),
        ("décembre 2026", None, "déc-2026"),
        ("mars", 2026, "mars-2026"),
        ("ILLISIBLE", 2026, None),
        (None, 2026, None),
    ],
)
def test_normaliser_periode(brut, annee, attendu):
    assert normaliser_periode(brut, annee) == attendu


def _facture_exemple() -> FactureExtraite:
    return FactureExtraite(
        entete={
            "dr": "DR CENTRE",
            "agence": "0231",
            "periode": "MARS 2026",
            "compte_client": "0012345678",
            "nom_client": "MINISTERE DE LA SANTE PUBLIQUE",
            "ville": "YAOUNDE",
        },
        lignes=[
            {
                "code_abonnement": "PL-4455",
                "nom_abonne": "HOPITAL CENTRAL DE YAOUNDE",
                "numero_compteur": "A123456",
                "index_nouvel": "1 350",
                "index_ancien": "1 250",
                "consommation": "100",
                "location_compteur": "1 000",
                "tva": "7 546",
                "montant_ht": "39 200",
                "montant_ttc": "46 746",
            },
            {
                "code_abonnement": "PL-4456",
                "nom_abonne": "LYCEE DE NGOA EKELLE",
                "numero_compteur": "B778899",
                "index_nouvel": "560",
                "index_ancien": "500",
                "consommation": "60",
                "location_compteur": "0",
                "tva": "",  # illisible : sera dérivée
                "montant_ht": "22 920",
                "montant_ttc": "",
            },
        ],
        total_ht="62 120",
        total_tva="11 958",
        total_ttc="74 078",
        confiance=0.95,
        pages=1,
    )


def test_construction_des_17_colonnes():
    lignes = construire_lignes(_facture_exemple())
    assert len(lignes) == 2
    for ligne in lignes:
        assert list(ligne.valeurs.keys()) == list(COLONNES)
        assert len(ligne.as_row()) == 17


def test_valeurs_et_mapping():
    premiere, seconde = construire_lignes(_facture_exemple())

    assert premiere.valeurs["Période"] == "mars-2026"
    assert premiere.valeurs["Agence"] == "0231"
    assert premiere.valeurs["Consommation"] == 100
    assert premiere.valeurs["Montant HT"] == 39200
    assert premiere.valeurs["TVA"] == 7546
    assert premiere.valeurs["Montant TTC"] == 46746
    assert premiere.valeurs["Ministère_2026"] == "MINSANTE"

    # TVA et TTC absents de la facture : reconstruits par formule.
    assert seconde.valeurs["TVA"] == 4412          # ARRONDI(22920 × 0,1925)
    assert seconde.valeurs["Montant TTC"] == 27332
    assert "tva" in seconde.champs_derives
    assert seconde.valeurs["Ministère_2026"] == "MINESEC"


def test_rapport_coherent_est_valide():
    facture = _facture_exemple()
    rapport = RapportTraitement(fichier="exemple.pdf", confiance=facture.confiance)
    rapport.lignes = construire_lignes(facture)
    rapport.totaux_lus = {"HT": facture.total_ht, "TVA": facture.total_tva, "TTC": facture.total_ttc}

    valider_rapport(rapport)

    assert rapport.nb_ok == 2, rapport.anomalies
    assert rapport.totaux_calcules["HT"] == "62120"


def test_ecart_de_total_marque_toutes_les_lignes():
    facture = _facture_exemple()
    facture.total_ttc = "99 999"  # total faux volontairement
    rapport = RapportTraitement(fichier="exemple.pdf")
    rapport.lignes = construire_lignes(facture)
    rapport.totaux_lus = {"HT": facture.total_ht, "TVA": facture.total_tva, "TTC": facture.total_ttc}

    valider_rapport(rapport)

    assert rapport.nb_ok == 0
    assert all(ligne.statut == MARQUEUR_A_VERIFIER for ligne in rapport.lignes)
    assert any("Total TTC" in anomalie for anomalie in rapport.anomalies)


def test_ligne_illisible_est_marquee():
    facture = _facture_exemple()
    facture.lignes = [
        {
            "code_abonnement": "PL-9999",
            "nom_abonne": "HOPITAL DE DISTRICT",
            "numero_compteur": "ILLISIBLE",
            "index_nouvel": "ILLISIBLE",
            "index_ancien": "ILLISIBLE",
            "consommation": "ILLISIBLE",
            "location_compteur": "",
            "tva": "ILLISIBLE",
            "montant_ht": "ILLISIBLE",
            "montant_ttc": "ILLISIBLE",
        }
    ]
    ligne = valider_ligne(construire_lignes(facture)[0])

    assert ligne.statut == MARQUEUR_ILLISIBLE
    assert ligne.valeurs["Consommation"] == MARQUEUR_ILLISIBLE
    assert ligne.anomalies


def test_ministere_indetermine_est_a_verifier():
    facture = _facture_exemple()
    facture.entete["nom_client"] = "CLIENT DIVERS"
    facture.lignes = [dict(facture.lignes[0], nom_abonne="ABONNE 12")]

    ligne = valider_ligne(construire_lignes(facture)[0])

    assert ligne.valeurs["Ministère_2026"] == MARQUEUR_A_VERIFIER
    assert ligne.statut == MARQUEUR_A_VERIFIER


def test_controle_des_totaux():
    lignes = construire_lignes(_facture_exemple())
    controle = controler_totaux(lignes, "62 120", "11 958", "74 078")
    assert controle.coherent
    assert str(controle.calcules["TTC"]) == "74078"

    controle_faux = controler_totaux(lignes, "62 120", "11 958", "70 000")
    assert not controle_faux.coherent


def test_statut_initial_ok():
    ligne = construire_lignes(_facture_exemple())[0]
    assert ligne.statut == STATUT_OK
