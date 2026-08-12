"""Contrôle d'accès à l'interface web.

Le classeur général et les rapports de traitement contiennent des numéros de
compte, des montants et la ventilation par ministère de l'ensemble des
administrations. Rien ne justifie que n'importe quelle machine du réseau puisse
les télécharger.

Le dispositif tient en une règle, volontairement simple à retenir :

    **sans mot de passe, l'application n'écoute que la machine locale.**

Un poste unique fonctionne donc sans rien configurer, et sans être exposé.
Ouvrir aux autres postes suppose de définir `CAMWATER_MOT_DE_PASSE` : c'est un
acte délibéré, pas un défaut de configuration. Le mot de passe est ensuite
demandé par le navigateur (authentification HTTP Basic), ce qui évite d'avoir à
distribuer un jeton ou à construire un écran de connexion.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
from typing import Optional

from .config import (
    AUTH_ACTIVE,
    AUTH_MOT_DE_PASSE,
    AUTH_UTILISATEUR,
    HOTES_LOCAUX,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CHEMINS_LIBRES",
    "acces_autorise",
    "hote_effectif",
    "identifiants_valides",
]

#: Chemins accessibles sans identifiants. Volontairement réduit à la sonde de
#: disponibilité : elle ne révèle aucune donnée de facturation et doit rester
#: interrogeable par un outil de supervision.
CHEMINS_LIBRES = frozenset({"/health"})


def identifiants_valides(utilisateur: str, mot_de_passe: str) -> bool:
    """Compare les identifiants en temps constant.

    `compare_digest` plutôt que `==` : une comparaison ordinaire s'arrête au
    premier caractère différent, ce qui laisse deviner le secret caractère par
    caractère. Les deux comparaisons sont évaluées, sans court-circuit, pour ne
    pas révéler non plus lequel des deux champs est faux.
    """
    nom_ok = secrets.compare_digest(utilisateur, AUTH_UTILISATEUR)
    passe_ok = secrets.compare_digest(mot_de_passe, AUTH_MOT_DE_PASSE)
    return nom_ok and passe_ok


def _decoder_basic(entete: str) -> Optional[tuple[str, str]]:
    """Extrait (utilisateur, mot de passe) d'un en-tête `Authorization`."""
    schema, _, valeur = entete.partition(" ")
    if schema.lower() != "basic" or not valeur:
        return None
    try:
        decode = base64.b64decode(valeur.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    utilisateur, separateur, mot_de_passe = decode.partition(":")
    if not separateur:
        return None
    return utilisateur, mot_de_passe


def acces_autorise(chemin: str, entete_authorization: Optional[str]) -> bool:
    """L'appel peut-il aboutir ?

    Retourne `True` quand l'authentification est désactivée : dans ce cas
    l'application n'écoute que la machine locale (voir `hote_effectif`), et
    exiger un mot de passe de l'agent assis devant le poste n'apporterait rien.
    """
    if not AUTH_ACTIVE or chemin in CHEMINS_LIBRES:
        return True
    if not entete_authorization:
        return False
    identifiants = _decoder_basic(entete_authorization)
    if identifiants is None:
        return False
    return identifiants_valides(*identifiants)


def hote_effectif(hote_demande: str) -> tuple[str, Optional[str]]:
    """Adresse d'écoute réellement retenue, et l'explication s'il y a écart.

    Sans mot de passe, une demande d'écoute sur le réseau est ramenée à la
    machine locale. On refuse d'exposer le classeur, mais on ne refuse pas de
    démarrer : l'agent qui double-clique sur `demarrer.bat` doit pouvoir
    travailler, et lire dans le journal pourquoi les autres postes n'y accèdent
    pas encore.
    """
    if AUTH_ACTIVE or hote_demande in HOTES_LOCAUX:
        return hote_demande, None

    message = (
        f"Aucun mot de passe défini : l'écoute sur « {hote_demande} » est ramenée à "
        "127.0.0.1, et l'application n'est donc accessible que depuis cette machine. "
        "Le classeur général et les rapports contiennent des numéros de compte et des "
        "montants : les exposer au réseau sans mot de passe n'est pas fait par défaut.\n"
        "Pour ouvrir l'accès aux autres postes, ajoutez dans le fichier .env :\n"
        "    CAMWATER_MOT_DE_PASSE=un-mot-de-passe-solide\n"
        "puis relancez. Le navigateur le demandera au premier accès "
        f"(utilisateur « {AUTH_UTILISATEUR} »)."
    )
    return "127.0.0.1", message
