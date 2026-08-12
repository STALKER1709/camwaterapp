"""Orchestration du traitement d'une facture, de la réception à l'Excel.

Enchaînement :

    fichier reçu
      → empreinte SHA-256 (contrôle de doublon)
      → conversion PDF → PNG puis mise à la résolution utile (ou image telle quelle)
      → lecture visuelle par le modèle (extraction.py)
      → normalisation + formules (calculs.py) + mapping ministère (mapping.py)
      → validation et statuts (validation.py)
      → écriture transactionnelle dans l'Excel général (excel_manager.py)
      → archivage du fichier (processed/ ou errors/) + rapport JSON

Aucune exception ne remonte non journalisée : toute erreur bloquante produit un
`RapportTraitement` en échec, le fichier est déplacé dans `errors/` et un
rapport détaillé est écrit.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from .calculs import calculer_ligne, format_nombre
from .config import (
    ERROR_DIR,
    MARQUEUR_A_VERIFIER,
    MARQUEUR_ILLISIBLE,
    MOIS_FR,
    PROCESSED_DIR,
    REJETER_DOUBLONS,
    UPLOAD_DIR,
)
from .excel_manager import ExcelError, ExcelManager
from .extraction import (
    CLE_DIVERGENCES,
    ExtractionError,
    FactureExtraite,
    extraire_facture,
)
from .mapping import resoudre_ministere
from .models import LigneFacture, RapportTraitement
from .pdf_utils import ConversionError, preparer_pages
from .validation import ecrire_rapport, valider_rapport

logger = logging.getLogger(__name__)

__all__ = ["PipelineError", "calculer_empreinte", "normaliser_periode", "traiter_fichier"]


class PipelineError(RuntimeError):
    """Erreur bloquante empêchant l'intégration de la facture."""


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #


def calculer_empreinte(chemin: Path) -> str:
    """Empreinte SHA-256 du fichier (identification des doublons)."""
    condensat = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


_MOIS_ALIAS = {
    "janvier": 0, "janv": 0, "jan": 0,
    "fevrier": 1, "fevr": 1, "fev": 1, "feb": 1,
    "mars": 2, "mar": 2,
    "avril": 3, "avr": 3, "apr": 3,
    "mai": 4, "may": 4,
    "juin": 5, "jun": 5,
    "juillet": 6, "juil": 6, "jul": 6,
    "aout": 7, "aou": 7, "aug": 7,
    "septembre": 8, "sept": 8, "sep": 8,
    "octobre": 9, "oct": 9,
    "novembre": 10, "nov": 10,
    "decembre": 11, "dec": 11,
}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser_periode(brut: Optional[str], annee_defaut: Optional[int] = None) -> Optional[str]:
    """Normalise une période au format `MMM-AAAA` (ex. « mars-2026 »).

    Accepte les formes courantes rencontrées sur les factures :
    « MARS 2026 », « 03/2026 », « 2026-03 », « mars-26 », « Mars 2026 ».
    Retourne `None` si la période n'est pas interprétable.

    >>> normaliser_periode("MARS 2026")
    'mars-2026'
    >>> normaliser_periode("03/2026")
    'mars-2026'
    >>> normaliser_periode("mars", 2026)
    'mars-2026'
    """
    if not brut:
        return None
    texte = _sans_accents(str(brut)).strip().lower()
    if not texte or texte == "illisible":
        return None

    annee: Optional[int] = None
    mois: Optional[int] = None

    for candidat in re.findall(r"\d{4}", texte):
        valeur = int(candidat)
        if 2000 <= valeur <= 2100:
            annee = valeur
            texte = texte.replace(candidat, " ", 1)
            break

    for alias, index in sorted(_MOIS_ALIAS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"(?<![a-z]){alias}(?![a-z])", texte):
            mois = index
            texte = re.sub(rf"(?<![a-z]){alias}(?![a-z])", " ", texte, count=1)
            break

    nombres = [int(n) for n in re.findall(r"\d{1,2}", texte)]
    if mois is None:
        for nombre in nombres:
            if 1 <= nombre <= 12:
                mois = nombre - 1
                nombres.remove(nombre)
                break
    if annee is None:
        for nombre in nombres:
            if 0 <= nombre <= 99:
                annee = 2000 + nombre
                break

    if annee is None:
        annee = annee_defaut
    if mois is None or annee is None:
        return None
    return f"{MOIS_FR[mois]}-{annee}"


def _texte(valeur: Optional[str]) -> Optional[str]:
    """Nettoie une valeur textuelle ; `ILLISIBLE` est conservé tel quel."""
    if valeur is None:
        return None
    nettoye = " ".join(str(valeur).split())
    if not nettoye:
        return None
    if nettoye.upper() == "ILLISIBLE":
        return MARQUEUR_ILLISIBLE
    return nettoye


def _archiver(source: Path, destination_dir: Path) -> Path:
    """Déplace le fichier traité, en évitant tout écrasement."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    cible = destination_dir / source.name
    if cible.exists():
        horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
        cible = destination_dir / f"{source.stem}_{horodatage}{source.suffix}"
    try:
        shutil.move(str(source), str(cible))
    except OSError as exc:
        logger.error("Archivage impossible de %s vers %s : %s", source, cible, exc)
        return source
    return cible


# --------------------------------------------------------------------------- #
# Construction des lignes
# --------------------------------------------------------------------------- #


def construire_lignes(
    facture: FactureExtraite,
    annee: Optional[int] = None,
    administration: Optional[str] = None,
) -> list[LigneFacture]:
    """Transforme l'extraction brute en lignes prêtes pour l'Excel (17 colonnes).

    `annee` complète une période dont l'année est illisible ; `administration`
    sert de ministère de repli lorsqu'aucun pattern ne matche.
    """
    dr = _texte(facture.valeur_entete("dr"))
    agence = _texte(facture.valeur_entete("agence"))
    periode = normaliser_periode(facture.valeur_entete("periode"), annee)
    compte_client = _texte(facture.valeur_entete("compte_client"))
    nom_client = _texte(facture.valeur_entete("nom_client"))
    ville = _texte(facture.valeur_entete("ville"))

    lignes: list[LigneFacture] = []
    for numero, brut in enumerate(facture.lignes, start=1):
        calcul = calculer_ligne(brut)
        nom_abonne = _texte(brut.get("nom_abonne"))

        # Certaines factures récapitulatives portent un compte par ligne. Une
        # valeur vide signifie « pas de colonne compte dans ce tableau » : on
        # reprend alors celui de l'en-tête. ILLISIBLE, en revanche, signifie
        # que la colonne existe mais n'est pas déchiffrable : la ligne restera
        # sans compte, donc écartée du pointage.
        compte_ligne = _texte(brut.get("compte_client"))
        compte = compte_ligne if compte_ligne is not None else compte_client
        affectation = resoudre_ministere(nom_abonne, nom_client, administration)

        ligne = LigneFacture(
            numero=numero,
            champs_derives=list(calcul.champs_derives),
            anomalies=list(calcul.anomalies),
            valeurs={
                "DR": dr,
                "Agence": agence,
                "Période": periode,
                "Compte client": compte,
                "Nom du client": nom_client,
                "Ville": ville,
                "Code abonnement (PL)": _texte(brut.get("code_abonnement")),
                "Nom abonné": nom_abonne,
                "N° compteur": _texte(brut.get("numero_compteur")),
                "Index nouvel": format_nombre(calcul.index_nouvel),
                "Index ancien": format_nombre(calcul.index_ancien),
                "Consommation": format_nombre(calcul.consommation),
                "Location compteur": format_nombre(calcul.location_compteur),
                "TVA": format_nombre(calcul.tva),
                "Montant HT": format_nombre(calcul.montant_ht),
                "Ministère_2026": affectation.ministere,
                "Montant TTC": format_nombre(calcul.montant_ttc),
            },
        )
        # Divergence entre deux lectures indépendantes : la valeur retenue est
        # celle de la lecture la plus confiante, mais un humain doit trancher.
        for divergence in brut.get(CLE_DIVERGENCES) or []:
            ligne.marquer(
                MARQUEUR_A_VERIFIER,
                f"Double lecture divergente sur {divergence}",
            )

        if not affectation.certain:
            ligne.anomalies.append(f"Ministère incertain : {affectation.motif}")
        if periode is None:
            ligne.anomalies.append("Période illisible ou non interprétable")
        lignes.append(ligne)

    return lignes


# --------------------------------------------------------------------------- #
# Traitement complet
# --------------------------------------------------------------------------- #


def traiter_fichier(
    chemin: Path,
    annee: Optional[int] = None,
    administration: Optional[str] = None,
    utilisateur: str = "",
    excel: Optional[ExcelManager] = None,
    archiver: bool = True,
) -> RapportTraitement:
    """Traite une facture de bout en bout et retourne le rapport de traitement.

    Ne lève jamais : les erreurs bloquantes sont capturées dans
    `RapportTraitement.erreur`, le fichier est déplacé dans `errors/` et un
    rapport JSON est écrit dans tous les cas.
    """
    debut = time.monotonic()
    chemin = Path(chemin)
    rapport = RapportTraitement(fichier=chemin.name)
    excel = excel or ExcelManager()
    dossier_travail = UPLOAD_DIR / ".work" / chemin.stem

    try:
        if not chemin.is_file():
            raise PipelineError(f"Fichier introuvable : {chemin}")

        rapport.empreinte = calculer_empreinte(chemin)
        logger.info("Traitement de %s (sha256 %s…)", chemin.name, rapport.empreinte[:12])

        if REJETER_DOUBLONS:
            deja = excel.fichier_deja_traite(rapport.empreinte)
            if deja:
                raise PipelineError(
                    f"Facture déjà intégrée sous le nom « {deja} » (empreinte identique). "
                    "Aucune ligne n'a été ajoutée pour éviter un doublon."
                )

        pages = preparer_pages(chemin, dossier_travail)
        rapport.pages = len(pages)

        facture = extraire_facture(pages)
        rapport.confiance = facture.confiance
        rapport.remarques = list(facture.remarques)
        rapport.totaux_lus = {
            "HT": facture.total_ht,
            "TVA": facture.total_tva,
            "TTC": facture.total_ttc,
        }

        rapport.lignes = construire_lignes(facture, annee=annee, administration=administration)
        valider_rapport(rapport)

        # Contrôle de doublon **métier**, après lecture : l'empreinte SHA-256
        # ne repère que le même fichier, alors qu'un re-scan ou un recadrage de
        # la même facture produit un fichier différent. L'identité réelle d'une
        # facture est le couple (compte client, période).
        if REJETER_DOUBLONS:
            deja_presentes = excel.facture_deja_presente(rapport.lignes)
            if deja_presentes:
                details = ", ".join(
                    f"compte {compte} sur {periode}" for compte, periode in deja_presentes
                )
                raise PipelineError(
                    f"Facture déjà présente dans le fichier général ({details}). "
                    "Aucune ligne n'a été ajoutée pour éviter un doublon. "
                    "Si cette facture est bien nouvelle, vérifiez le compte client "
                    "et la période lus sur le document."
                )

        rapport.lignes_ecrites = excel.ajouter_lignes(
            rapport.lignes,
            fichier=chemin.name,
            empreinte=rapport.empreinte,
            utilisateur=utilisateur,
            pages=rapport.pages,
            confiance=rapport.confiance,
        )
        rapport.succes = True

    except (ConversionError, ExtractionError, ExcelError, PipelineError) as exc:
        rapport.erreur = str(exc)
        logger.error("Échec du traitement de %s : %s", chemin.name, exc)
    except Exception as exc:  # filet de sécurité : rien ne doit passer en silence
        rapport.erreur = f"Erreur inattendue : {exc}"
        logger.exception("Erreur inattendue lors du traitement de %s", chemin.name)

    finally:
        rapport.duree_secondes = time.monotonic() - debut
        if dossier_travail.exists():
            shutil.rmtree(dossier_travail, ignore_errors=True)
        if archiver and chemin.is_file():
            destination = PROCESSED_DIR if rapport.succes else ERROR_DIR
            rapport.chemin_archive = str(_archiver(chemin, destination))
        try:
            ecrire_rapport(rapport)
        except OSError as exc:
            logger.error("Impossible d'écrire le rapport de %s : %s", chemin.name, exc)

    logger.info(rapport.resume())
    return rapport
