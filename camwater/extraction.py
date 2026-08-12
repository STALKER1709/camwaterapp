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

from .calculs import parse_nombre
from .config import (
    ANTHROPIC_API_KEY,
    DOUBLE_LECTURE,
    LLM_EFFORT,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_MODEL,
)
from .pdf_utils import Page

logger = logging.getLogger(__name__)

__all__ = [
    "CLE_DIVERGENCES",
    "ExtractionError",
    "FactureExtraite",
    "PROMPT_EXTRACTION",
    "SCHEMA_FACTURE",
    "VERSION_SDK_MINIMALE",
    "confronter",
    "extraire_facture",
    "extraire_page",
    "lire_page",
    "verifier_version_sdk",
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

#: Version minimale du SDK Anthropic. Le code passe `output_config` (schéma JSON
#: imposé + niveau d'effort) et `cache_control` : le SDK 0.69 n'en connaît aucun,
#: et un environnement qui résout vers un plancher trop bas — miroir de paquets
#: d'entreprise, `pip install --no-index`, venv ancien jamais mis à jour —
#: échouerait au premier appel sur un `TypeError` muet sur la cause.
VERSION_SDK_MINIMALE = (0, 121)


def _version_installee() -> Optional[tuple[int, ...]]:
    """Version du SDK sous forme comparable, ou `None` si non interprétable."""
    try:
        from anthropic import __version__
    except Exception:  # pragma: no cover - SDK absent, traité en amont
        return None

    fragments: list[int] = []
    for fragment in str(__version__).split("."):
        chiffres = ""
        for caractere in fragment:
            if not caractere.isdigit():
                break
            chiffres += caractere
        if not chiffres:
            break
        fragments.append(int(chiffres))
    return tuple(fragments) or None


def verifier_version_sdk() -> Optional[str]:
    """Retourne un message d'action si le SDK installé est trop ancien.

    Retourne `None` quand tout va bien — y compris lorsque la version n'est pas
    interprétable : refuser de fonctionner faute d'avoir su lire un numéro de
    version serait pire que de laisser l'appel tenter sa chance.
    """
    installee = _version_installee()
    if installee is None or installee >= VERSION_SDK_MINIMALE:
        return None

    lisible = ".".join(str(n) for n in installee)
    minimale = ".".join(str(n) for n in VERSION_SDK_MINIMALE)
    return (
        f"Le paquet « anthropic » installé est en version {lisible}, trop ancienne "
        f"pour cette application (minimum {minimale}). Les versions antérieures ne "
        "connaissent pas les paramètres de lecture utilisés ici, et l'appel "
        "échouerait sans expliquer pourquoi. Mettez à jour avec :\n"
        "    pip install -r requirements.txt --upgrade\n"
        "Sous Windows, relancer demarrer.bat suffit : il réinstalle les "
        "dépendances dès que requirements.txt a changé."
    )


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

    probleme = verifier_version_sdk()
    if probleme:
        raise ExtractionError(probleme)

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

    # Les consignes restent rigoureusement identiques d'une page à l'autre :
    # c'est ce qui rend le préfixe cachable. Le contexte, lui, varie — il part
    # donc dans le tour utilisateur, après l'image.
    consignes = PROMPT_EXTRACTION
    rappel_contexte = ""
    if contexte:
        rappel_contexte = (
            "\n\nEn-tête déjà lu sur les pages précédentes :\n"
            f"{contexte}\n"
            "Utilise-le uniquement pour lever une ambiguïté d'en-tête ; "
            "ne recopie jamais une ligne de facturation venant de ce contexte."
        )

    # L'image est placée AVANT le texte (meilleure lecture visuelle), et les
    # consignes partent en « system » avec un point de cache : elles sont
    # identiques d'une page à l'autre, donc facturées au tarif « lecture de
    # cache » (~10 %) dès la deuxième page traitée.
    systeme = [{"type": "text", "text": consignes, "cache_control": {"type": "ephemeral"}}]
    contenu = [
        _bloc_document(page),
        {
            "type": "text",
            "text": f"Transcris cette page (page {page.numero} du document).{rappel_contexte}",
        },
    ]

    derniere_erreur: Optional[Exception] = None
    for tentative in range(1, LLM_MAX_RETRIES + 1):
        try:
            with client.messages.stream(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                system=systeme,
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
            usage = getattr(message, "usage", None)
            cache = getattr(usage, "cache_read_input_tokens", 0) or 0
            logger.info(
                "Page %d lue : %d ligne(s), confiance %.2f%s",
                page.numero,
                len(donnees.get("lignes") or []),
                confiance,
                f", {cache} jetons servis depuis le cache" if cache else "",
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


#: Champs numériques confrontés entre deux lectures indépendantes.
CHAMPS_CHIFFRES = (
    "index_nouvel",
    "index_ancien",
    "consommation",
    "location_compteur",
    "tva",
    "montant_ht",
    "montant_ttc",
)

#: Clé technique portant, sur une ligne, les champs où les deux lectures
#: divergent. Exploitée par `pipeline.construire_lignes` pour marquer la ligne.
CLE_DIVERGENCES = "_divergences"


def _memes_valeurs(gauche: Any, droite: Any) -> bool:
    """Deux transcriptions désignent-elles la même valeur ?

    La comparaison porte sur le nombre, pas sur son écriture : « 1 234 » et
    « 1.234 » sont identiques, alors que « 1234 » et « 1284 » divergent.
    """
    a, b = parse_nombre(gauche), parse_nombre(droite)
    if a is not None or b is not None:
        return a == b
    return str(gauche or "").strip().upper() == str(droite or "").strip().upper()


def confronter(premiere: PageExtraite, seconde: PageExtraite) -> PageExtraite:
    """Compare deux lectures d'une même page et signale les divergences.

    Une erreur de lecture est rapportée avec autant d'assurance qu'une lecture
    juste : seule une seconde lecture indépendante permet de la repérer. Les
    valeurs retenues sont celles de la lecture la plus confiante ; chaque champ
    divergent est marqué pour qu'un humain tranche sur pièce.
    """
    retenue, autre = (
        (premiere, seconde) if premiere.confiance >= seconde.confiance else (seconde, premiere)
    )
    lignes_retenues = retenue.donnees.get("lignes") or []
    lignes_autres = autre.donnees.get("lignes") or []

    if len(lignes_retenues) != len(lignes_autres):
        retenue.remarques.append(
            f"Double lecture : {len(lignes_retenues)} ligne(s) contre "
            f"{len(lignes_autres)} — le tableau n'a pas été découpé de la même "
            "façon, contrôle humain nécessaire"
        )
        return retenue

    total_divergences = 0
    for index, (ligne, temoin) in enumerate(zip(lignes_retenues, lignes_autres), start=1):
        divergences = [
            champ
            for champ in CHAMPS_CHIFFRES
            if not _memes_valeurs(ligne.get(champ), temoin.get(champ))
        ]
        if divergences:
            ligne[CLE_DIVERGENCES] = [
                f"{champ} : « {ligne.get(champ)} » puis « {temoin.get(champ)} »"
                for champ in divergences
            ]
            total_divergences += len(divergences)

    for champ in ("total_ht", "total_tva", "total_ttc"):
        if not _memes_valeurs(retenue.donnees.get(champ), autre.donnees.get(champ)):
            retenue.remarques.append(
                f"Double lecture : {champ} lu « {retenue.donnees.get(champ)} » "
                f"puis « {autre.donnees.get(champ)} »"
            )

    if total_divergences:
        logger.warning(
            "Page %d : %d divergence(s) entre les deux lectures — lignes marquées à vérifier",
            retenue.numero,
            total_divergences,
        )
    else:
        logger.info("Page %d : les deux lectures concordent sur tous les chiffres", retenue.numero)
    return retenue


def lire_page(page: Page, contexte: str = "") -> PageExtraite:
    """Lit une page, une ou deux fois selon `CAMWATER_DOUBLE_LECTURE`."""
    premiere = extraire_page(page, contexte=contexte)
    if not DOUBLE_LECTURE:
        return premiere
    return confronter(premiere, extraire_page(page, contexte=contexte))


def _ligne_non_vide(ligne: dict[str, Any]) -> bool:
    """Écarte les lignes entièrement vides renvoyées par mégarde."""
    return any(
        str(valeur).strip()
        for cle, valeur in ligne.items()
        if cle != CLE_DIVERGENCES
    )


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

        extraite = lire_page(page, contexte=contexte)
        donnees = extraite.donnees

        for champ in CHAMPS_ENTETE:
            valeur = str(donnees.get(champ) or "").strip()
            if valeur and valeur.upper() != "ILLISIBLE" and not facture.entete.get(champ):
                facture.entete[champ] = valeur

        for ligne in donnees.get("lignes") or []:
            if isinstance(ligne, dict) and _ligne_non_vide(ligne):
                facture.lignes.append(
                    {
                        cle: valeur if cle == CLE_DIVERGENCES else str(valeur)
                        for cle, valeur in ligne.items()
                    }
                )

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
