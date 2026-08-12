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


def _alternatives(pattern: str) -> list[str]:
    """Les libellés littéraux d'un motif « mot entier » construit par `_mot()`."""
    import re

    motif = re.match(r"^\(\?<!\[A-Z0-9\]\)\(\?:(.*)\)\(\?!\[A-Z0-9\]\)$", pattern)
    if not motif:
        return []
    return [
        alternative.replace(r"\s+", " ")
        for alternative in motif.group(1).split("|")
        if not re.search(r"[\[\]{}()*+?^$]", alternative)  # motif non littéral
    ]


def test_aucun_pattern_masque_par_une_priorite_superieure():
    """Chaque motif doit résoudre vers son propre ministère.

    Garde-fou contre le « masquage » : un motif générique de priorité forte qui
    intercepte les libellés d'une règle de priorité plus faible (le cas réel :
    « DISTRICT » sous MINAT captait « HOPITAL DE DISTRICT », qui relève de
    MINSANTE). Toute nouvelle règle est vérifiée automatiquement ici.
    """
    from camwater.mapping import REGLES

    collisions = []
    for regle in REGLES:
        if regle.code == "MINISTERE":  # règle générique de dernier recours
            continue
        for pattern in regle.patterns:
            for libelle in _alternatives(pattern):
                obtenu = resoudre_ministere(libelle).ministere
                if obtenu != regle.code:
                    collisions.append(f"« {libelle} » : attendu {regle.code}, obtenu {obtenu}")

    assert not collisions, "Motifs masqués :\n  " + "\n  ".join(collisions)


def test_chaque_exclusion_resout_bien_en_hors_perimetre():
    """Symétrique du test précédent, côté exclusions.

    Le détecteur de masquage ne couvrait que `REGLES` : c'est exactement le
    trou par lequel le défaut A-1 est passé. Une exclusion masquée par une
    règle ministérielle rattacherait une société d'État à un ministère.
    """
    from camwater.mapping import EXCLUSIONS

    collisions = []
    for pattern in EXCLUSIONS:
        for libelle in _alternatives(pattern):
            obtenu = resoudre_ministere(libelle).ministere
            if obtenu != MAPPING_HORS_PERIMETRE:
                collisions.append(f"« {libelle} » : attendu HORS_PERIMETRE, obtenu {obtenu}")

    assert not collisions, "Exclusions masquées :\n  " + "\n  ".join(collisions)


#: Libellés d'entités publiques réellement gouvernementales. Aucun ne doit être
#: happé par une exclusion : un sigle nu ambigu dans la liste d'exclusions
#: rangerait une facture publique parmi les entités hors périmètre — bien plus
#: coûteux qu'une exclusion manquée, qui reste visible en `À_VÉRIFIER`.
_LIBELLES_GOUVERNEMENTAUX = (
    "ECOLE PUBLIQUE DE CDE",
    "CENTRE DE SANTE INTEGRE DE CDC",
    "CITE SIC DE MESSA",
    "CAMP SIC DE NYLON",
    "CENTRE D ART DE DOUALA",
    "COLLEGE ART ET METIERS",
    "SOUS PREFECTURE DE PAD",
    "LYCEE DE PAK",
    "HOPITAL DE DISTRICT DE CDC",
    "DELEGATION DEPARTEMENTALE DES ARTS",
    "LYCEE TECHNIQUE DE NKOLBISSON",
    "BRIGADE DE GENDARMERIE DE MBALMAYO",
)


@pytest.mark.parametrize("libelle", _LIBELLES_GOUVERNEMENTAUX)
def test_aucune_exclusion_ne_happe_une_entite_gouvernementale(libelle):
    """Régression : six sigles nus (CDE, SIC, PAD, PAK, ART, CDC) collisionnaient."""
    resultat = resoudre_ministere(libelle)
    assert resultat.ministere != MAPPING_HORS_PERIMETRE, (
        f"« {libelle} » exclu à tort par {resultat.pattern}"
    )


@pytest.mark.parametrize(
    "abonne, attendu",
    [
        ("LYCEE BILINGUE DE MENDONG", "MINESEC"),
        ("HOPITAL CENTRAL DE YAOUNDE", "MINSANTE"),
        ("PREFECTURE DU WOURI", "MINAT"),
    ],
)
@pytest.mark.parametrize("client", ["CAMWATER", "CDE YAOUNDE", "CAMEROONAISE DES EAUX"])
def test_l_emetteur_dans_le_nom_du_client_n_exclut_pas_la_facture(abonne, client, attendu):
    """Régression A-1 : le cœur du défaut.

    Les exclusions travaillaient sur la concaténation abonné + client. Il
    suffisait que le nom du client porte le nom de l'émetteur de la facture —
    ce qu'un modèle de lecture peut recopier depuis l'en-tête — pour que toute
    la facture bascule en « hors périmètre ».
    """
    assert resoudre_ministere(abonne, client).ministere == attendu


def test_une_exclusion_sur_le_client_reste_appliquee():
    """L'abonné ne conclut pas : c'est alors au client de trancher."""
    resultat = resoudre_ministere("BLOC A", "CRTV YAOUNDE")

    assert resultat.ministere == MAPPING_HORS_PERIMETRE
    assert "nom du client" in resultat.motif


def test_l_exclusion_prime_sur_la_regle_dans_la_meme_source():
    """Une société d'État reste exclue même si son libellé matche une règle."""
    resultat = resoudre_ministere("CAMTEL DIRECTION DES TRAVAUX PUBLICS")

    assert resultat.ministere == MAPPING_HORS_PERIMETRE
    assert "nom abonné" in resultat.motif


def test_hopital_de_district_reste_sante():
    """Régression : un motif MINAT interceptait les libellés hospitaliers."""
    assert resoudre_ministere("HOPITAL DE DISTRICT DE MBALMAYO").ministere == "MINSANTE"
    assert resoudre_ministere("DISTRICT DE SANTE DE BIYEM ASSI").ministere == "MINSANTE"
    assert resoudre_ministere("PREFECTURE DU WOURI").ministere == "MINAT"


def test_normalisation_libelle():
    assert normaliser_libelle("Lycée   Général-Leclerc, B.P. 12") == "LYCEE GENERAL LECLERC B P 12"
    assert normaliser_libelle(None) == ""
