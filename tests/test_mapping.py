"""Tests des règles d'affectation du ministère."""

import pytest

from camwater.config import MARQUEUR_A_VERIFIER
from camwater.mapping import MAPPING_HORS_PERIMETRE, normaliser_libelle, resoudre_ministere


@pytest.mark.parametrize(
    "libelle, attendu",
    [
        ("LYCÉE CLASSIQUE DE YAOUNDÉ", "MINESEC"),
        ("ECOLE PUBLIQUE DE MVOG-ADA", "MINEDUB"),
        ("UNIVERSITE DE DOUALA - RECTORAT", "MINESUP"),
        ("HOPITAL CENTRAL DE YAOUNDE", "MINSANTE"),
        ("CENTRE DE SANTE INTEGRE DE NKOLBISSON", "MINSANTE"),
        ("LEGION DE GENDARMERIE DU CENTRE", "MINDEF"),
        ("COMMISSARIAT CENTRAL N°1", "DGSN"),
        ("DELEGATION GENERALE A LA SURETE NATIONALE", "DGSN"),
        ("PREFECTURE DU MFOUNDI", "MINAT"),
        ("CENTRE DES IMPOTS DE BASTOS", "MINFI"),
        ("TRIBUNAL DE PREMIERE INSTANCE", "MINJUSTICE"),
        ("PRESIDENCE DE LA REPUBLIQUE", "PRC"),
        ("GARDE PRESIDENTIELLE", "GP"),
        ("ASSEMBLEE NATIONALE", "AN"),
        ("MINSANTE / DELEGATION REGIONALE", "MINSANTE"),
    ],
)
def test_patterns_ministeres(libelle, attendu):
    assert resoudre_ministere(libelle).ministere == attendu


@pytest.mark.parametrize(
    "libelle",
    ["CRTV YAOUNDE", "CAMTEL DIRECTION GENERALE", "BEAC AGENCE DE DOUALA", "CAMRAIL"],
)
def test_entites_exclues(libelle):
    resultat = resoudre_ministere(libelle)
    assert resultat.ministere == MAPPING_HORS_PERIMETRE


def test_priorite_institutions_sur_ministeres():
    """La Présidence l'emporte sur un libellé secondaire de plus faible priorité."""
    resultat = resoudre_ministere("PRESIDENCE DE LA REPUBLIQUE - SERVICE DES TRAVAUX PUBLICS")
    assert resultat.ministere == "PRC"


def test_repli_sur_le_ministere_du_dossier():
    resultat = resoudre_ministere("ABONNE SANS INDICE", ministere_dossier="MINSANTE")
    assert resultat.ministere == "MINSANTE"
    assert resultat.certain is False


def test_a_verifier_sans_repli():
    resultat = resoudre_ministere("ABONNE SANS INDICE")
    assert resultat.ministere == MARQUEUR_A_VERIFIER
    assert resultat.certain is False


def test_le_nom_du_client_sert_de_secours():
    resultat = resoudre_ministere("BLOC A", "DELEGATION REGIONALE DE LA SANTE DU CENTRE")
    assert resultat.ministere == "MINSANTE"


def test_aucun_pattern_masque_par_une_priorite_superieure():
    """Chaque motif doit résoudre vers son propre ministère.

    Garde-fou contre le « masquage » : un motif générique de priorité forte qui
    intercepte les libellés d'une règle de priorité plus faible (le cas réel :
    « DISTRICT » sous MINAT captait « HOPITAL DE DISTRICT », qui relève de
    MINSANTE). Toute nouvelle règle est vérifiée automatiquement ici.
    """
    import re

    from camwater.mapping import REGLES

    def alternatives(pattern: str) -> list[str]:
        motif = re.match(r"^\(\?<!\[A-Z0-9\]\)\(\?:(.*)\)\(\?!\[A-Z0-9\]\)$", pattern)
        return [a.replace(r"\s+", " ") for a in motif.group(1).split("|")] if motif else []

    collisions = []
    for regle in REGLES:
        if regle.code == "MINISTERE":  # règle générique de dernier recours
            continue
        for pattern in regle.patterns:
            for libelle in alternatives(pattern):
                if re.search(r"[\[\]{}()*+?^$]", libelle):  # motif non littéral
                    continue
                obtenu = resoudre_ministere(libelle).ministere
                if obtenu != regle.code:
                    collisions.append(f"« {libelle} » : attendu {regle.code}, obtenu {obtenu}")

    assert not collisions, "Motifs masqués :\n  " + "\n  ".join(collisions)


def test_hopital_de_district_reste_sante():
    """Régression : un motif MINAT interceptait les libellés hospitaliers."""
    assert resoudre_ministere("HOPITAL DE DISTRICT DE MBALMAYO").ministere == "MINSANTE"
    assert resoudre_ministere("DISTRICT DE SANTE DE BIYEM ASSI").ministere == "MINSANTE"
    assert resoudre_ministere("PREFECTURE DU WOURI").ministere == "MINAT"


def test_normalisation_libelle():
    assert normaliser_libelle("Lycée   Général-Leclerc, B.P. 12") == "LYCEE GENERAL LECLERC B P 12"
    assert normaliser_libelle(None) == ""
