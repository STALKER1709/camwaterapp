"""Lecture visuelle des factures CAMWATER par un modèle Claude.

L'OCR classique échoue sur ces scans (watermark circulaire bleu, pas de couche
texte fiable). On soumet donc chaque page en image au modèle, avec un prompt
strict et un **schéma de sortie JSON imposé** (`output_config.format`), de sorte
que la réponse est structurellement garantie et n'a jamais besoin d'être
« devinée ».

Principe directeur : le modèle **transcrit**, il ne calcule pas. Chaque nombre
est rendu tel qu'il est imprimé (chaîne de caractères) ; toute l'arithmétique et
les vérifications sont faites côté Python (`calculs.py`, `validation.py`).
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import (
    ANTHROPIC_API_KEY,
    LLM_EFFORT,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_MODEL,
)
from .pdf_utils import Page

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionError",
    "FactureExtraite",
    "PROMPT_EXTRACTION",
    "SCHEMA_FACTURE",
    "extraire_facture",
    "extraire_page",
]


class ExtractionError(RuntimeError):
    """La lecture visuelle a échoué de façon irrécupérable."""


# --------------------------------------------------------------------------- #
# Prompt interne envoyé au modèle pour chaque page
# --------------------------------------------------------------------------- #

PROMPT_EXTRACTION = """\
Tu es un opérateur de saisie expert, spécialisé dans les factures d'eau CAMWATER
adressées aux administrations publiques camerounaises.

L'image ci-jointe est le scan d'UNE page de facture. Elle porte un TAMPON
CIRCULAIRE BLEU (watermark) qui recouvre partiellement le texte : lis À TRAVERS
ce tampon, il ne fait jamais partie des données. Ignore également les mentions
manuscrites, cachets et annotations en marge.

TA MISSION : transcrire fidèlement, sans rien calculer et sans rien inventer.

════════════════════════ CE QUE TU DOIS EXTRAIRE ════════════════════════

1. EN-TÊTE de la page (cadre supérieur) :
   • dr             — Direction Régionale (ex. « DR CENTRE », « DRC »)
   • agence         — code agence à 4 chiffres (ex. « 0231 »)
   • periode        — période de facturation, format « MMM-AAAA » en français
                      abrégé (janv, févr, mars, avr, mai, juin, juil, août,
                      sept, oct, nov, déc) — ex. « mars-2026 ». Si la facture
                      indique un mois en toutes lettres ou un format différent,
                      convertis-le dans ce format.
   • compte_client  — numéro de compte client (le tenir tel quel, zéros inclus)
   • nom_client     — raison sociale du client facturé (l'administration)
   • ville          — ville / localité du client

2. TOUTES LES LIGNES du tableau de facturation, sans exception, dans l'ordre
   d'apparition, y compris les lignes à consommation nulle. Pour chacune :
   • compte_client     — numéro de compte client **si le tableau porte une
                         colonne compte par ligne**. Si la facture ne donne le
                         compte que dans l'en-tête, laisse "" : il sera repris
                         de l'en-tête. Mets "ILLISIBLE" seulement si la colonne
                         existe et que la valeur est indéchiffrable.
   • code_abonnement   — code d'abonnement, dit « PL »
   • nom_abonne        — libellé de l'abonné (souvent le service ou l'entité)
   • numero_compteur   — numéro de compteur
   • index_nouvel      — index nouveau relevé
   • index_ancien      — index ancien
   • consommation      — consommation en m³
   • location_compteur — montant de location du compteur
   • tva               — montant de TVA de la ligne
   • montant_ht        — montant hors taxes de la ligne
   • montant_ttc       — montant toutes taxes comprises de la ligne

3. TOTAUX de la facture (pied de tableau ou cadre récapitulatif) :
   total_ht, total_tva, total_ttc.

═══════════════════════ RÈGLES ABSOLUES SUR LES NOMBRES ═══════════════════════

• Rends CHAQUE nombre sous forme de CHAÎNE, exactement comme il est imprimé,
  y compris ses séparateurs : « 1.234,56 », « 12 500 », « 0 ».
  N'ajoute pas de séparateur, n'en retire pas, n'arrondis jamais, ne convertis
  pas en notation anglaise.
• N'effectue AUCUN calcul, AUCUNE somme, AUCUNE déduction. Si une case est vide
  sur la facture, rends la chaîne vide "".
• Si un chiffre est masqué, coupé ou réellement indéchiffrable, rends
  exactement "ILLISIBLE" pour ce champ. Ne devine jamais un chiffre partiel :
  une valeur fausse est bien plus grave qu'une valeur marquée ILLISIBLE.
• Attention aux confusions fréquentes sur ces scans : 0/O, 1/7, 5/6, 8/B, 3/8.
  Si le doute persiste après un examen attentif, marque "ILLISIBLE".
• Vérifie le nombre de chiffres de chaque montant avant de le rendre (un
  montant à 6 chiffres transcrit sur 5 est l'erreur la plus coûteuse).

═════════════════════════ CAS PARTICULIERS ═════════════════════════

• Page sans tableau de facturation (page de garde, conditions générales,
  annexe) : rends « lignes »: [] et signale-le dans « remarques ».
• Page de continuation sans en-tête : laisse les champs d'en-tête à "" ; ils
  seront repris de la première page.
• Une même page peut contenir plusieurs blocs de lignes : concatène-les tous.
• Si le tableau se poursuit page suivante, ne transcris que ce que TU VOIS ici.

Renseigne « confiance » entre 0 et 1 (qualité de lecture globale de la page) et
« remarques » pour toute observation utile à un contrôleur humain (zone masquée
par le tampon, page floue, colonne tronquée, etc.).
"""

# --------------------------------------------------------------------------- #
# Schéma de sortie imposé au modèle (structured outputs)
# --------------------------------------------------------------------------- #

_CHAINE = {"type": "string"}


def _objet(proprietes: dict[str, Any]) -> dict[str, Any]:
    """Objet JSON strict : toutes les propriétés requises, rien en plus."""
    return {
        "type": "object",
        "properties": proprietes,
        "required": list(proprietes),
        "additionalProperties": False,
    }


SCHEMA_LIGNE = _objet(
    {
        "compte_client": _CHAINE,
        "code_abonnement": _CHAINE,
        "nom_abonne": _CHAINE,
        "numero_compteur": _CHAINE,
        "index_nouvel": _CHAINE,
        "index_ancien": _CHAINE,
        "consommation": _CHAINE,
        "location_compteur": _CHAINE,
        "tva": _CHAINE,
        "montant_ht": _CHAINE,
        "montant_ttc": _CHAINE,
    }
)

SCHEMA_FACTURE = _objet(
    {
        "dr": _CHAINE,
        "agence": _CHAINE,
        "periode": _CHAINE,
        "compte_client": _CHAINE,
        "nom_client": _CHAINE,
        "ville": _CHAINE,
        "lignes": {"type": "array", "items": SCHEMA_LIGNE},
        "total_ht": _CHAINE,
        "total_tva": _CHAINE,
        "total_ttc": _CHAINE,
        "confiance": {"type": "number"},
        "remarques": {"type": "array", "items": _CHAINE},
    }
)

CHAMPS_ENTETE = ("dr", "agence", "periode", "compte_client", "nom_client", "ville")


# --------------------------------------------------------------------------- #
# Structures de retour
# --------------------------------------------------------------------------- #


@dataclass
class PageExtraite:
    """Résultat brut de la lecture d'une page."""

    numero: int
    donnees: dict[str, Any]
    confiance: float = 0.0
    remarques: list[str] = field(default_factory=list)


@dataclass
class FactureExtraite:
    """Facture complète, reconstituée à partir de toutes ses pages."""

    entete: dict[str, str] = field(default_factory=dict)
    lignes: list[dict[str, str]] = field(default_factory=list)
    total_ht: Optional[str] = None
    total_tva: Optional[str] = None
    total_ttc: Optional[str] = None
    confiance: float = 0.0
    remarques: list[str] = field(default_factory=list)
    pages: int = 0

    def valeur_entete(self, champ: str) -> Optional[str]:
        valeur = (self.entete.get(champ) or "").strip()
        return valeur or None


# --------------------------------------------------------------------------- #
# Appel au modèle
# --------------------------------------------------------------------------- #

_client = None


def _obtenir_client():
    """Instancie (une seule fois) le client Anthropic."""
    global _client
    if _client is not None:
        return _client
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dépendance déclarée
        raise ExtractionError(
            "Le paquet « anthropic » n'est pas installé : pip install -r requirements.txt"
        ) from exc

    if not ANTHROPIC_API_KEY:
        # Le SDK sait aussi lire un profil `ant auth login` ; on n'échoue donc
        # pas ici, on prévient seulement.
        logger.warning(
            "ANTHROPIC_API_KEY n'est pas défini ; le SDK tentera d'utiliser un "
            "profil d'authentification local."
        )
    _client = Anthropic()
    return _client


def _bloc_document(page: Page) -> dict[str, Any]:
    """Encode une page en bloc de contenu (image ou document PDF)."""
    donnees = base64.standard_b64encode(page.chemin.read_bytes()).decode("ascii")
    if page.est_pdf:
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": donnees,
            },
        }
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": page.media_type,
            "data": donnees,
        },
    }


def _texte_reponse(message: Any) -> str:
    return "".join(bloc.text for bloc in message.content if bloc.type == "text")


#: Erreurs qu'un nouvel essai ne résoudra jamais : inutile de réessayer, et le
#: message brut de l'API (JSON anglais) est incompréhensible pour un agent.
#: Chaque entrée associe un motif du message d'erreur à une consigne d'action.
_ERREURS_DEFINITIVES: tuple[tuple[str, str], ...] = (
    (
        "credit balance is too low",
        "Le crédit du compte API Anthropic est épuisé. Rechargez-le sur "
        "https://platform.claude.com (Plans & Billing), puis relancez le traitement. "
        "La clé API est valide : seul le solde est en cause.",
    ),
    (
        "could not resolve authentication",
        "Aucune clé API n'est configurée. Renseignez ANTHROPIC_API_KEY dans le "
        "fichier .env à la racine du projet, puis relancez l'application.",
    ),
    (
        "invalid x-api-key",
        "La clé API est invalide ou a été révoquée. Vérifiez ANTHROPIC_API_KEY "
        "dans le fichier .env, ou créez une nouvelle clé sur "
        "https://platform.claude.com (Settings → API keys).",
    ),
    (
        "authentication_error",
        "Échec d'authentification auprès de l'API Anthropic. Vérifiez la clé "
        "ANTHROPIC_API_KEY dans le fichier .env.",
    ),
    (
        "permission_error",
        "La clé API n'a pas les droits nécessaires pour ce modèle "
        f"({LLM_MODEL}). Vérifiez les permissions de la clé sur "
        "https://platform.claude.com.",
    ),
    (
        "not_found_error",
        f"Le modèle « {LLM_MODEL} » est introuvable. Corrigez CAMWATER_MODEL "
        "dans le fichier .env.",
    ),
)


def _erreur_definitive(exc: Exception) -> Optional[str]:
    """Retourne un message d'action si l'erreur ne peut pas se résoudre d'elle-même.

    Réessayer une erreur de crédit ou de clé est inutile : cela retarde
    l'affichage du vrai problème sans aucune chance de succès.
    """
    texte = str(exc).lower()
    for motif, consigne in _ERREURS_DEFINITIVES:
        if motif in texte:
            return consigne
    return None


def extraire_page(page: Page, contexte: str = "") -> PageExtraite:
    """Soumet une page au modèle et retourne les données transcrites.

    `contexte` permet de rappeler au modèle l'en-tête déjà lu sur les pages
    précédentes (utile pour les pages de continuation).
    """
    client = _obtenir_client()

    consignes = PROMPT_EXTRACTION
    if contexte:
        consignes += (
            "\n═══════════ CONTEXTE DES PAGES PRÉCÉDENTES ═══════════\n"
            f"{contexte}\n"
            "Utilise-le uniquement pour lever une ambiguïté d'en-tête ; "
            "ne recopie jamais une ligne de facturation venant du contexte."
        )

    contenu = [
        _bloc_document(page),
        {"type": "text", "text": f"{consignes}\n\n(Page {page.numero} du document.)"},
    ]

    derniere_erreur: Optional[Exception] = None
    for tentative in range(1, LLM_MAX_RETRIES + 1):
        try:
            with client.messages.stream(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                output_config={
                    "effort": LLM_EFFORT,
                    "format": {"type": "json_schema", "schema": SCHEMA_FACTURE},
                },
                messages=[{"role": "user", "content": contenu}],
            ) as flux:
                message = flux.get_final_message()

            if message.stop_reason == "refusal":
                raise ExtractionError(
                    "Le modèle a refusé de traiter la page "
                    f"{page.numero} (catégorie : "
                    f"{getattr(message.stop_details, 'category', 'inconnue')})."
                )
            if message.stop_reason == "max_tokens":
                raise ExtractionError(
                    f"Réponse tronquée sur la page {page.numero} : augmentez "
                    "CAMWATER_MAX_TOKENS."
                )

            donnees = json.loads(_texte_reponse(message))
            confiance = float(donnees.get("confiance") or 0.0)
            remarques = [str(r) for r in donnees.get("remarques") or []]
            logger.info(
                "Page %d lue : %d ligne(s), confiance %.2f",
                page.numero,
                len(donnees.get("lignes") or []),
                confiance,
            )
            return PageExtraite(
                numero=page.numero,
                donnees=donnees,
                confiance=confiance,
                remarques=remarques,
            )

        except ExtractionError:
            raise
        except json.JSONDecodeError as exc:
            derniere_erreur = exc
            logger.warning(
                "Réponse non JSON pour la page %d (tentative %d/%d) : %s",
                page.numero,
                tentative,
                LLM_MAX_RETRIES,
                exc,
            )
        except Exception as exc:  # erreurs réseau / API
            # Une erreur de crédit, de clé ou de droits ne se résoudra pas en
            # réessayant : on remonte immédiatement une consigne d'action, sans
            # faire patienter l'utilisateur ni noyer la cause dans du JSON.
            consigne = _erreur_definitive(exc)
            if consigne:
                logger.error("Erreur bloquante d'accès à l'API : %s", exc)
                raise ExtractionError(consigne) from exc

            derniere_erreur = exc
            logger.warning(
                "Échec d'appel au modèle pour la page %d (tentative %d/%d) : %s",
                page.numero,
                tentative,
                LLM_MAX_RETRIES,
                exc,
            )

        if tentative < LLM_MAX_RETRIES:
            time.sleep(min(2**tentative, 16))

    raise ExtractionError(
        f"Lecture impossible de la page {page.numero} après {LLM_MAX_RETRIES} "
        f"tentatives : {derniere_erreur}"
    )


def _ligne_non_vide(ligne: dict[str, Any]) -> bool:
    """Écarte les lignes entièrement vides renvoyées par mégarde."""
    return any(str(valeur).strip() for valeur in ligne.values())


def extraire_facture(pages: list[Page]) -> FactureExtraite:
    """Lit toutes les pages et reconstitue une facture unique.

    * l'en-tête est constitué de la première valeur non vide rencontrée, page
      après page ;
    * les lignes de toutes les pages sont concaténées dans l'ordre ;
    * les totaux retenus sont ceux de la dernière page qui en porte (le pied de
      tableau se trouve sur la dernière page du document).
    """
    if not pages:
        raise ExtractionError("Aucune page à traiter.")

    facture = FactureExtraite(pages=len(pages))
    confiances: list[float] = []

    for page in pages:
        contexte = ""
        if facture.entete:
            contexte = "\n".join(f"{cle} = {val}" for cle, val in facture.entete.items() if val)

        extraite = extraire_page(page, contexte=contexte)
        donnees = extraite.donnees

        for champ in CHAMPS_ENTETE:
            valeur = str(donnees.get(champ) or "").strip()
            if valeur and valeur.upper() != "ILLISIBLE" and not facture.entete.get(champ):
                facture.entete[champ] = valeur

        for ligne in donnees.get("lignes") or []:
            if isinstance(ligne, dict) and _ligne_non_vide(ligne):
                facture.lignes.append({k: str(v) for k, v in ligne.items()})

        for cle, attribut in (
            ("total_ht", "total_ht"),
            ("total_tva", "total_tva"),
            ("total_ttc", "total_ttc"),
        ):
            valeur = str(donnees.get(cle) or "").strip()
            if valeur:
                setattr(facture, attribut, valeur)

        confiances.append(extraite.confiance)
        facture.remarques.extend(
            f"page {page.numero} : {remarque}" for remarque in extraite.remarques
        )

    facture.confiance = sum(confiances) / len(confiances) if confiances else 0.0

    if not facture.lignes:
        raise ExtractionError(
            "Aucune ligne de facturation lisible dans le document "
            f"({len(pages)} page(s) analysée(s))."
        )

    logger.info(
        "Facture reconstituée : %d ligne(s) sur %d page(s), confiance moyenne %.2f",
        len(facture.lignes),
        len(pages),
        facture.confiance,
    )
    return facture
