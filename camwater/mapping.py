"""Affectation du ministère (`Ministère_2026`) à partir des libellés facture.

Trois familles de règles, appliquées dans cet ordre :

1. **Exclusions** — entités publiques *non gouvernementales* (sociétés d'État,
   établissements autonomes, médias…). Elles ne relèvent d'aucun ministère et
   sont marquées `HORS_PERIMETRE`.
2. **Patterns priorisés** — le premier pattern qui matche gagne. La priorité
   basse est la plus forte (1 = institutions, 10 = ministères techniques).
3. **Repli** — ministère du dossier source s'il est fourni, sinon `À_VÉRIFIER`.

Le champ testé est la concaténation `Nom abonné` + `Nom du client` normalisée
(majuscules, accents retirés, ponctuation réduite à des espaces).

Extensibilité : déposer un fichier JSON à l'emplacement pointé par
`CAMWATER_MAPPING_FILE` pour ajouter/écraser des règles sans toucher au code ::

    {
      "regles": [
        {"code": "MINSANTE", "priorite": 5, "patterns": ["CENTRE MEDICO SOCIAL"]}
      ],
      "exclusions": ["MA SOCIETE SA"]
    }
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .config import MARQUEUR_A_VERIFIER

logger = logging.getLogger(__name__)

__all__ = [
    "MAPPING_HORS_PERIMETRE",
    "ResultatMapping",
    "charger_regles_personnalisees",
    "normaliser_libelle",
    "resoudre_ministere",
]

MAPPING_HORS_PERIMETRE = "HORS_PERIMETRE"

_PONCTUATION = re.compile(r"[^A-Z0-9]+")


def normaliser_libelle(texte: Optional[str]) -> str:
    """Majuscules, sans accents, ponctuation remplacée par des espaces."""
    if not texte:
        return ""
    decompose = unicodedata.normalize("NFKD", str(texte))
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return _PONCTUATION.sub(" ", sans_accents.upper()).strip()


@dataclass(frozen=True)
class Regle:
    """Un ministère et les motifs qui permettent de le reconnaître."""

    code: str
    priorite: int
    patterns: tuple[str, ...]

    def correspond(self, libelle: str) -> Optional[str]:
        for pattern in self.patterns:
            if re.search(pattern, libelle):
                return pattern
        return None


@dataclass
class ResultatMapping:
    """Ministère retenu et justification (utile pour l'audit)."""

    ministere: str
    motif: str
    pattern: Optional[str] = None
    certain: bool = True


def _mot(*variantes: str) -> str:
    """Construit un motif « mot entier » tolérant les espaces internes."""
    alternatives = "|".join(v.replace(" ", r"\s+") for v in variantes)
    return rf"(?<![A-Z0-9])(?:{alternatives})(?![A-Z0-9])"


# --------------------------------------------------------------------------- #
# Entités publiques non gouvernementales : jamais rattachées à un ministère.
# --------------------------------------------------------------------------- #

EXCLUSIONS: tuple[str, ...] = (
    _mot("CRTV", "CAMEROON RADIO TELEVISION"),
    _mot("BEAC", "BANQUE DES ETATS DE L AFRIQUE CENTRALE"),
    _mot("CAMRAIL"),
    _mot("CAMTEL", "CAMEROON TELECOMMUNICATIONS"),
    _mot("CAMAIR CO", "CAMAIRCO", "CAMEROON AIRLINES"),
    _mot("CAMWATER", "CDE", "CAMEROONAISE DES EAUX"),
    _mot("ENEO", "AES SONEL", "SONEL"),
    _mot("SONARA"),
    _mot("SNH", "SOCIETE NATIONALE DES HYDROCARBURES"),
    _mot("SODECOTON"),
    _mot("ALUCAM"),
    _mot("MAGZI"),
    _mot("SIC", "SOCIETE IMMOBILIERE DU CAMEROUN"),
    _mot("CNPS", "CAISSE NATIONALE DE PREVOYANCE SOCIALE"),
    _mot("PAD", "PORT AUTONOME DE DOUALA", "PAK", "PORT AUTONOME DE KRIBI"),
    _mot("ART", "AGENCE DE REGULATION DES TELECOMMUNICATIONS"),
    _mot("ANOR"),
    _mot("CDC", "CAMEROON DEVELOPMENT CORPORATION"),
    _mot("MTN", "ORANGE CAMEROUN", "NEXTTEL"),
    _mot("SCDP", "SOCIETE CAMEROUNAISE DES DEPOTS PETROLIERS"),
    _mot("MIPROMALO"),
    _mot("CICAM"),
    _mot("PMUC"),
)

# --------------------------------------------------------------------------- #
# Règles priorisées. Priorité 1 = institutions de souveraineté.
# --------------------------------------------------------------------------- #

REGLES: tuple[Regle, ...] = (
    # --- 1. Présidence et institutions ------------------------------------ #
    # Note sur les sigles ambigus : lorsqu'un acronyme court désigne deux
    # entités relevant de ministères différents (CES = Conseil économique et
    # social ou Collège d'enseignement secondaire ; ENSP = École nationale
    # supérieure de police ou Polytechnique ; PR = Présidence ou titre), seule
    # la forme développée est retenue. Un sigle nu tombe ainsi en `À_VÉRIFIER`
    # plutôt que d'être affecté au mauvais ministère en silence.
    Regle(
        "PRC",
        1,
        (
            _mot("PRC"),
            _mot("PRESIDENCE DE LA REPUBLIQUE", "PRESIDENCE"),
            _mot("SGPR", "SECRETARIAT GENERAL DE LA PRESIDENCE"),
            _mot("PALAIS DE L UNITE", "ETAT MAJOR PARTICULIER"),
        ),
    ),
    Regle(
        "GP",
        1,
        (
            _mot("GP", "GARDE PRESIDENTIELLE", "GARDE PRESIDENTIEL"),
            _mot("GROUPEMENT PRESIDENTIEL"),
        ),
    ),
    Regle("SPM", 1, (_mot("SPM", "SERVICES DU PREMIER MINISTRE", "PREMIER MINISTRE"),)),
    # « AN » nu est écarté : le sigle se confond avec le mot français « an ».
    Regle("AN", 1, (_mot("ASSEMBLEE NATIONALE"),)),
    Regle("SENAT", 1, (_mot("SENAT", "SENATEUR"),)),
    Regle("CONSUPE", 2, (_mot("CONSUPE", "CONTROLE SUPERIEUR DE L ETAT"),)),
    Regle("ELECAM", 2, (_mot("ELECAM", "ELECTIONS CAMEROON"),)),
    Regle("CONAC", 2, (_mot("CONAC", "COMMISSION NATIONALE ANTI CORRUPTION"),)),
    Regle("CC", 2, (_mot("CONSEIL CONSTITUTIONNEL"),)),
    Regle("CES", 2, (_mot("CONSEIL ECONOMIQUE ET SOCIAL"),)),
    Regle("CNDHL", 2, (_mot("CNDHL", "COMMISSION NATIONALE DES DROITS DE L HOMME"),)),
    # --- 3. Sécurité et défense ------------------------------------------- #
    Regle(
        "DGSN",
        3,
        (
            _mot("DGSN", "SURETE NATIONALE", "SURETE"),
            _mot("COMMISSARIAT", "COMMISSARIAT CENTRAL", "POLICE"),
            _mot("GMI", "GROUPEMENT MOBILE D INTERVENTION"),
            _mot("ECOLE NATIONALE SUPERIEURE DE POLICE"),
        ),
    ),
    Regle("DGRE", 3, (_mot("DGRE", "RECHERCHE EXTERIEURE"),)),
    Regle(
        "MINDEF",
        3,
        (
            _mot("MINDEF", "MINISTERE DE LA DEFENSE", "DEFENSE NATIONALE"),
            _mot("GENDARMERIE", "LEGION DE GENDARMERIE", "BRIGADE DE GENDARMERIE"),
            _mot("SED", "SECRETARIAT D ETAT A LA DEFENSE"),
            _mot("BIR", "BATAILLON D INTERVENTION RAPIDE"),
            _mot("BASE AERIENNE", "BASE NAVALE", "REGION MILITAIRE", "EMAT", "CEMA"),
            _mot("HOPITAL MILITAIRE", "CAMP MILITAIRE", "GARNISON"),
        ),
    ),
    Regle(
        "MINJUSTICE",
        3,
        (
            _mot("MINJUSTICE", "MINJUS", "MINISTERE DE LA JUSTICE"),
            _mot("TRIBUNAL", "COUR D APPEL", "COUR SUPREME", "PARQUET"),
            _mot("PRISON", "PENITENTIAIRE", "MAISON D ARRET"),
        ),
    ),
    # --- 4. Administration territoriale ------------------------------------ #
    Regle(
        "MINAT",
        4,
        (
            _mot("MINAT", "MINATD", "ADMINISTRATION TERRITORIALE"),
            _mot("GOUVERNORAT", "GOUVERNEUR", "PREFECTURE", "PREFET"),
            # « DISTRICT » nu est volontairement absent : il apparaît surtout
            # dans « HOPITAL DE DISTRICT » et « DISTRICT DE SANTE », qui
            # relèvent de MINSANTE (priorité plus faible, donc masqués ici).
            _mot("SOUS PREFECTURE", "SOUS PREFET"),
            _mot("PROTECTION CIVILE", "SAPEURS POMPIERS"),
        ),
    ),
    Regle(
        "MINDDEVEL",
        4,
        (
            _mot("MINDDEVEL", "DECENTRALISATION ET DEVELOPPEMENT LOCAL"),
            _mot("FEICOM"),
        ),
    ),
    # --- 5. Santé et social ------------------------------------------------- #
    Regle(
        "MINSANTE",
        5,
        (
            _mot("MINSANTE", "MINISTERE DE LA SANTE", "SANTE PUBLIQUE"),
            _mot("HOPITAL", "HOPITAL CENTRAL", "HOPITAL GENERAL", "HOPITAL DE DISTRICT"),
            _mot("CENTRE DE SANTE", "CENTRE MEDICAL", "CSI", "CMA", "DISTRICT DE SANTE"),
            _mot("DELEGATION REGIONALE DE LA SANTE", "PHARMACIE PROVINCIALE", "CAPR"),
        ),
    ),
    Regle("MINAS", 5, (_mot("MINAS", "AFFAIRES SOCIALES"),)),
    Regle("MINPROFF", 5, (_mot("MINPROFF", "PROMOTION DE LA FEMME"),)),
    Regle("MINJEC", 5, (_mot("MINJEC", "JEUNESSE ET EDUCATION CIVIQUE"),)),
    Regle("MINSEP", 5, (_mot("MINSEP", "SPORTS ET EDUCATION PHYSIQUE", "STADE"),)),
    # --- 6. Éducation ------------------------------------------------------- #
    Regle(
        "MINEDUB",
        6,
        (
            _mot("MINEDUB", "EDUCATION DE BASE"),
            _mot("ECOLE PUBLIQUE", "EP", "ECOLE MATERNELLE", "INSPECTION D ARRONDISSEMENT"),
        ),
    ),
    Regle(
        "MINESEC",
        6,
        (
            _mot("MINESEC", "ENSEIGNEMENTS SECONDAIRES"),
            _mot("LYCEE", "COLLEGE", "CETIC", "CES", "SAR SM", "ENIEG", "ENIET"),
        ),
    ),
    Regle(
        "MINESUP",
        6,
        (
            _mot("MINESUP", "ENSEIGNEMENT SUPERIEUR"),
            _mot("UNIVERSITE", "RECTORAT", "FACULTE", "IUT", "ENS", "CUSS"),
            _mot("CENTRE DES OEUVRES UNIVERSITAIRES", "CROU"),
        ),
    ),
    Regle("MINEFOP", 6, (_mot("MINEFOP", "FORMATION PROFESSIONNELLE"),)),
    Regle("MINRESI", 6, (_mot("MINRESI", "RECHERCHE SCIENTIFIQUE", "IRAD", "IMPM"),)),
    # --- 7. Finances et économie -------------------------------------------- #
    Regle(
        "MINFI",
        7,
        (
            _mot("MINFI", "MINISTERE DES FINANCES"),
            _mot("DGI", "IMPOTS", "CENTRE DES IMPOTS", "DGTCFM", "TRESORERIE", "PAIERIE"),
            _mot("DOUANES", "DGD", "SECTEUR DES DOUANES"),
        ),
    ),
    Regle("MINEPAT", 7, (_mot("MINEPAT", "ECONOMIE DE LA PLANIFICATION", "PLANIFICATION"),)),
    Regle("MINCOMMERCE", 7, (_mot("MINCOMMERCE", "MINCOMMERCE", "MINISTERE DU COMMERCE"),)),
    Regle("MINMIDT", 7, (_mot("MINMIDT", "MINES DE L INDUSTRIE"),)),
    Regle("MINPMEESA", 7, (_mot("MINPMEESA", "PETITES ET MOYENNES ENTREPRISES"),)),
    Regle("MINTOUL", 7, (_mot("MINTOUL", "TOURISME ET LOISIRS"),)),
    # --- 8. Infrastructures et territoire ----------------------------------- #
    Regle("MINTP", 8, (_mot("MINTP", "TRAVAUX PUBLICS"),)),
    Regle("MINHDU", 8, (_mot("MINHDU", "HABITAT ET DEVELOPPEMENT URBAIN"),)),
    Regle("MINDCAF", 8, (_mot("MINDCAF", "DOMAINES DU CADASTRE", "CADASTRE"),)),
    Regle("MINT", 8, (_mot("MINT", "MINTRANSPORTS", "MINISTERE DES TRANSPORTS"),)),
    Regle("MINEE", 8, (_mot("MINEE", "EAU ET DE L ENERGIE", "ENERGIE"),)),
    Regle("MINPOSTEL", 8, (_mot("MINPOSTEL", "POSTES ET TELECOMMUNICATIONS"),)),
    # --- 9. Ruralité et environnement ---------------------------------------- #
    Regle("MINADER", 9, (_mot("MINADER", "AGRICULTURE ET DU DEVELOPPEMENT RURAL"),)),
    Regle("MINEPIA", 9, (_mot("MINEPIA", "ELEVAGE DES PECHES"),)),
    Regle("MINFOF", 9, (_mot("MINFOF", "FORETS ET DE LA FAUNE"),)),
    Regle("MINEPDED", 9, (_mot("MINEPDED", "ENVIRONNEMENT PROTECTION DE LA NATURE"),)),
    # --- 10. Autres départements ministériels -------------------------------- #
    Regle("MINREX", 10, (_mot("MINREX", "RELATIONS EXTERIEURES", "AMBASSADE", "CONSULAT"),)),
    Regle("MINCOM", 10, (_mot("MINCOM", "MINISTERE DE LA COMMUNICATION"),)),
    Regle("MINAC", 10, (_mot("MINAC", "MINISTERE DES ARTS ET DE LA CULTURE", "MUSEE"),)),
    Regle("MINTSS", 10, (_mot("MINTSS", "TRAVAIL ET DE LA SECURITE SOCIALE"),)),
    Regle("MINFOPRA", 10, (_mot("MINFOPRA", "FONCTION PUBLIQUE"),)),
    Regle("MINMAP", 10, (_mot("MINMAP", "MARCHES PUBLICS"),)),
    # Générique : un libellé « MINxxx » non listé reste identifiable.
    Regle("MINISTERE", 20, (_mot("MIN[A-Z]{2,10}"), _mot("MINISTERE"))),
)


def _regles_triees(regles: Iterable[Regle]) -> list[Regle]:
    return sorted(regles, key=lambda r: (r.priorite, r.code))


_REGLES_ACTIVES: list[Regle] = _regles_triees(REGLES)
_EXCLUSIONS_ACTIVES: list[str] = list(EXCLUSIONS)


def charger_regles_personnalisees(chemin: Optional[Path] = None) -> int:
    """Fusionne un fichier de règles externe. Retourne le nombre de règles ajoutées.

    Les règles portant un code déjà connu **remplacent** les patterns d'origine.
    """
    global _REGLES_ACTIVES, _EXCLUSIONS_ACTIVES

    if chemin is None:
        brut = os.getenv("CAMWATER_MAPPING_FILE", "").strip()
        if not brut:
            return 0
        chemin = Path(brut).expanduser()
    if not chemin.is_file():
        logger.warning("Fichier de mapping introuvable : %s", chemin)
        return 0

    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Mapping personnalisé illisible (%s) : %s", chemin, exc)
        return 0

    par_code = {regle.code: regle for regle in REGLES}
    ajoutees = 0
    for entree in donnees.get("regles", []):
        code = str(entree.get("code", "")).strip()
        patterns = tuple(str(p) for p in entree.get("patterns", []) if str(p).strip())
        if not code or not patterns:
            continue
        par_code[code] = Regle(code, int(entree.get("priorite", 15)), patterns)
        ajoutees += 1

    _REGLES_ACTIVES = _regles_triees(par_code.values())
    _EXCLUSIONS_ACTIVES = list(EXCLUSIONS) + [
        str(e) for e in donnees.get("exclusions", []) if str(e).strip()
    ]
    logger.info("Mapping personnalisé chargé depuis %s (%d règles)", chemin, ajoutees)
    return ajoutees


def resoudre_ministere(
    nom_abonne: Optional[str],
    nom_client: Optional[str] = None,
    ministere_dossier: Optional[str] = None,
) -> ResultatMapping:
    """Détermine le ministère d'une ligne d'abonnement.

    >>> resoudre_ministere("LYCEE DE NGOA EKELLE").ministere
    'MINESEC'
    >>> resoudre_ministere("CRTV YAOUNDE").ministere
    'HORS_PERIMETRE'
    >>> resoudre_ministere("ABONNE INCONNU", ministere_dossier="MINSANTE").ministere
    'MINSANTE'
    >>> resoudre_ministere("ABONNE INCONNU").ministere
    'À_VÉRIFIER'
    """
    libelle_abonne = normaliser_libelle(nom_abonne)
    libelle_client = normaliser_libelle(nom_client)

    if not libelle_abonne and not libelle_client:
        if ministere_dossier:
            return ResultatMapping(
                ministere=ministere_dossier.strip().upper(),
                motif="libellés vides — ministère du dossier source",
                certain=False,
            )
        return ResultatMapping(
            ministere=MARQUEUR_A_VERIFIER,
            motif="aucun libellé exploitable",
            certain=False,
        )

    for pattern in _EXCLUSIONS_ACTIVES:
        if re.search(pattern, f"{libelle_abonne} {libelle_client}"):
            return ResultatMapping(
                ministere=MAPPING_HORS_PERIMETRE,
                motif="entité exclue (non gouvernementale)",
                pattern=pattern,
            )

    # `Nom abonné` désigne l'entité réellement desservie : il est examiné en
    # premier, sur toute la liste de priorités. `Nom du client` (le titulaire du
    # compte, souvent le ministère payeur) ne sert que si l'abonné ne permet pas
    # de conclure — sans quoi un lycée facturé sur un compte MINSANTE serait
    # rattaché à la santé.
    for source, libelle in (("nom abonné", libelle_abonne), ("nom du client", libelle_client)):
        if not libelle:
            continue
        for regle in _REGLES_ACTIVES:
            pattern = regle.correspond(libelle)
            if pattern:
                return ResultatMapping(
                    ministere=regle.code,
                    motif=f"pattern prioritaire ({regle.priorite}) sur le {source}",
                    pattern=pattern,
                    certain=regle.code != "MINISTERE",
                )

    if ministere_dossier:
        return ResultatMapping(
            ministere=ministere_dossier.strip().upper(),
            motif="aucun pattern — ministère du dossier source",
            certain=False,
        )

    return ResultatMapping(
        ministere=MARQUEUR_A_VERIFIER,
        motif="aucun pattern et pas de ministère de repli",
        certain=False,
    )


# Chargement automatique d'un éventuel fichier de règles personnalisées.
charger_regles_personnalisees()
