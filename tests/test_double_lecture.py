"""Tests de la double lecture (`CAMWATER_DOUBLE_LECTURE`).

Un modèle de lecture visuelle rapporte une erreur avec la même assurance qu'une
valeur juste : rien dans sa réponse ne distingue « 1284 » mal lu de « 1234 » bien
lu. Confronter deux lectures indépendantes est le seul moyen automatique de
repérer ces écarts. Ces tests vérifient que la confrontation compare bien des
**nombres** (et non leur écriture) et qu'aucune divergence ne passe en silence.
"""

import pytest

from camwater.extraction import (
    CLE_DIVERGENCES,
    PageExtraite,
    _memes_valeurs,
    confronter,
)


def _page(numero=1, confiance=0.9, lignes=None, **totaux):
    donnees = {"lignes": lignes or [], **totaux}
    return PageExtraite(numero=numero, donnees=donnees, confiance=confiance)


# --------------------------------------------------------------------------- #
# Comparaison de valeurs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "gauche, droite",
    [
        ("1 234", "1.234"),        # séparateurs de milliers différents
        ("1.234,50", "1234.50"),   # écriture française contre anglaise
        ("0", "0,00"),
        ("12 500 FCFA", "12500"),
        (None, None),
        ("ILLISIBLE", "illisible"),  # marqueur, comparé en texte
    ],
)
def test_ecritures_differentes_meme_valeur(gauche, droite):
    assert _memes_valeurs(gauche, droite)


@pytest.mark.parametrize(
    "gauche, droite",
    [
        ("1234", "1284"),   # le 3 lu comme un 8 : l'erreur que l'on traque
        ("1234", "12340"),  # chiffre surnuméraire
        ("382", "-382"),
        ("100", None),      # une lecture a vu une valeur, l'autre non
        ("100", "ILLISIBLE"),
    ],
)
def test_valeurs_divergentes(gauche, droite):
    assert not _memes_valeurs(gauche, droite)


# --------------------------------------------------------------------------- #
# Confrontation de deux lectures
# --------------------------------------------------------------------------- #


def test_lectures_concordantes_ne_marquent_rien():
    ligne = {"compte_client": "123", "consommation": "40", "montant_ht": "15 280"}
    resultat = confronter(_page(lignes=[dict(ligne)]), _page(lignes=[dict(ligne)]))

    assert CLE_DIVERGENCES not in resultat.donnees["lignes"][0]
    assert resultat.remarques == []


def test_ecriture_differente_n_est_pas_une_divergence():
    """« 15 280 » et « 15.280 » sont le même montant : ne pas alerter pour rien."""
    resultat = confronter(
        _page(lignes=[{"montant_ht": "15 280"}]),
        _page(lignes=[{"montant_ht": "15.280"}]),
    )
    assert CLE_DIVERGENCES not in resultat.donnees["lignes"][0]


def test_chiffre_divergent_est_signale():
    resultat = confronter(
        _page(lignes=[{"consommation": "40", "montant_ht": "15280"}]),
        _page(lignes=[{"consommation": "46", "montant_ht": "15280"}]),
    )

    divergences = resultat.donnees["lignes"][0][CLE_DIVERGENCES]
    assert len(divergences) == 1
    assert "consommation" in divergences[0]
    assert "40" in divergences[0] and "46" in divergences[0]


def test_la_lecture_la_plus_confiante_est_retenue():
    resultat = confronter(
        _page(confiance=0.6, lignes=[{"consommation": "40"}]),
        _page(confiance=0.95, lignes=[{"consommation": "46"}]),
    )
    assert resultat.confiance == 0.95
    assert resultat.donnees["lignes"][0]["consommation"] == "46"


def test_nombre_de_lignes_different_arrete_la_comparaison():
    """Deux découpages différents du tableau : rien à confronter ligne à ligne."""
    resultat = confronter(
        _page(lignes=[{"consommation": "40"}, {"consommation": "12"}]),
        _page(lignes=[{"consommation": "40"}]),
    )

    assert CLE_DIVERGENCES not in resultat.donnees["lignes"][0]
    assert any("2 ligne(s) contre 1" in remarque for remarque in resultat.remarques)


def test_totaux_divergents_sont_remarques():
    resultat = confronter(
        _page(total_ht="100 000", total_tva="19 250", total_ttc="119 250"),
        _page(total_ht="100 000", total_tva="19 250", total_ttc="119 260"),
    )
    assert len(resultat.remarques) == 1
    assert "total_ttc" in resultat.remarques[0]


def test_toutes_les_lignes_divergentes_sont_marquees():
    resultat = confronter(
        _page(lignes=[{"consommation": "40"}, {"tva": "1 000"}, {"consommation": "7"}]),
        _page(lignes=[{"consommation": "41"}, {"tva": "1 000"}, {"consommation": "9"}]),
    )
    lignes = resultat.donnees["lignes"]

    assert CLE_DIVERGENCES in lignes[0]
    assert CLE_DIVERGENCES not in lignes[1]
    assert CLE_DIVERGENCES in lignes[2]


# --------------------------------------------------------------------------- #
# Effet sur le pointage
# --------------------------------------------------------------------------- #


def test_une_divergence_marque_la_ligne_a_verifier():
    """Bout en bout : une divergence doit ressortir dans le fichier Excel."""
    from camwater.config import MARQUEUR_A_VERIFIER
    from camwater.pipeline import construire_lignes
    from camwater.extraction import FactureExtraite

    facture = FactureExtraite(
        entete={"compte_client": "123456", "periode": "mars-2026", "nom_client": "MINSANTE"},
        lignes=[
            {
                "compte_client": "123456",
                "nom_abonne": "HOPITAL CENTRAL",
                "consommation": "40",
                "location_compteur": "1 000",
                CLE_DIVERGENCES: ["consommation : « 40 » puis « 46 »"],
            }
        ],
    )
    ligne = construire_lignes(facture, "facture.pdf")[0]

    assert ligne.statut == MARQUEUR_A_VERIFIER
    assert any("Double lecture divergente" in a for a in ligne.anomalies)


def test_ligne_sans_divergence_reste_valide():
    from camwater.pipeline import construire_lignes
    from camwater.extraction import FactureExtraite

    facture = FactureExtraite(
        entete={"compte_client": "123456", "periode": "mars-2026", "nom_client": "MINSANTE"},
        lignes=[
            {
                "compte_client": "123456",
                "nom_abonne": "HOPITAL CENTRAL",
                "consommation": "40",
                "location_compteur": "1 000",
            }
        ],
    )
    ligne = construire_lignes(facture, "facture.pdf")[0]

    assert not any("Double lecture" in a for a in ligne.anomalies)
