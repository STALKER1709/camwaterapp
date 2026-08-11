"""Parsing des nombres et formules de facturation CAMWATER.

Deux responsabilités :

1. **Interpréter sans perte** les nombres tels qu'ils sont imprimés sur la
   facture (séparateurs français, espaces insécables, parenthèses négatives…).
2. **Recalculer** les montants à partir de la consommation, puis *dériver* les
   valeurs manquantes lorsque la facture est partiellement illisible.

Formules (constantes dans `config`) ::

    Montant consommation = Consommation × 382
    Montant HT           = Montant consommation + Location compteur
    TVA                  = ARRONDI(Montant HT × 0,1925)
    Montant TTC          = Montant HT + TVA
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from .config import (
    MARQUEUR_ILLISIBLE,
    PRIX_UNITAIRE,
    TAUX_TVA,
    TOLERANCE_MONTANT,
)

__all__ = [
    "LigneCalculee",
    "arrondi",
    "calculer_ligne",
    "format_nombre",
    "parse_nombre",
]

# Caractères à neutraliser avant analyse : espaces (dont insécables), symboles
# monétaires et suffixes courants collés au nombre.
_ESPACES = dict.fromkeys(map(ord, "    '"), None)
_SUFFIXES = re.compile(
    r"(?:f\s*cfa|fcfa|xaf|frs?|f)\s*$", re.IGNORECASE
)
_NON_NUMERIQUE = re.compile(r"[^0-9,.\-]")
_GROUPES_MILLIERS = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")
_VALEURS_VIDES = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "nd",
    "n.d.",
    "null",
    "none",
    "néant",
    "neant",
    "illisible",
    MARQUEUR_ILLISIBLE.lower(),
}


def parse_nombre(brut: object) -> Optional[Decimal]:
    """Convertit une valeur brute lue sur la facture en `Decimal`.

    Règles appliquées (dans cet ordre) :

    * `None`, chaîne vide ou marqueur d'illisibilité  → ``None`` ;
    * les nombres déjà typés (`int`, `float`, `Decimal`) sont conservés ;
    * les espaces, symboles monétaires et parenthèses de négation sont retirés ;
    * si la valeur contient `.` **et** `,`, le dernier séparateur rencontré est
      le séparateur décimal (``1.234,56`` → ``1234.56``, ``1,234.56`` → ``1234.56``) ;
    * une virgule seule est toujours un séparateur décimal ;
    * un point seul est un séparateur de milliers **uniquement** si la valeur
      forme des groupes de trois chiffres (``1.234`` → ``1234``), sinon c'est un
      séparateur décimal (``12.5`` → ``12.5``).

    Aucune valeur n'est arrondie ni tronquée : la précision lue est conservée.

    >>> parse_nombre("1.234,56")
    Decimal('1234.56')
    >>> parse_nombre("12 345 FCFA")
    Decimal('12345')
    >>> parse_nombre("(250)")
    Decimal('-250')
    >>> parse_nombre("ILLISIBLE") is None
    True
    """
    if brut is None:
        return None
    if isinstance(brut, bool):  # évite le piège True == 1
        return None
    if isinstance(brut, Decimal):
        return brut
    if isinstance(brut, int):
        return Decimal(brut)
    if isinstance(brut, float):
        return Decimal(str(brut))

    texte = str(brut).strip()
    if texte.lower() in _VALEURS_VIDES:
        return None

    negatif = False
    if texte.startswith("(") and texte.endswith(")"):
        negatif = True
        texte = texte[1:-1]

    texte = texte.translate(_ESPACES)
    texte = _SUFFIXES.sub("", texte)
    texte = _NON_NUMERIQUE.sub("", texte)
    if not texte or texte in {"-", ".", ","}:
        return None

    if texte.startswith("-"):
        negatif = not negatif
        texte = texte[1:]
    texte = texte.replace("-", "")
    if not texte:
        return None

    a_point = "." in texte
    a_virgule = "," in texte

    if a_point and a_virgule:
        # Le séparateur décimal est le dernier des deux.
        if texte.rfind(",") > texte.rfind("."):
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", "")
    elif a_virgule:
        # Virgule = point : séparateur décimal. Plusieurs virgules ⇒ milliers.
        if texte.count(",") > 1:
            texte = texte.replace(",", "")
        else:
            texte = texte.replace(",", ".")
    elif a_point:
        if _GROUPES_MILLIERS.match(texte) or texte.count(".") > 1:
            texte = texte.replace(".", "")

    try:
        valeur = Decimal(texte)
    except InvalidOperation:
        return None
    return -valeur if negatif else valeur


def arrondi(valeur: Decimal, decimales: int = 0) -> Decimal:
    """Arrondi commercial (ARRONDI d'Excel) : moitié supérieure, comme la facture."""
    quantum = Decimal(1).scaleb(-decimales)
    return valeur.quantize(quantum, rounding=ROUND_HALF_UP)


def format_nombre(valeur: Optional[Decimal]) -> Optional[float | int]:
    """Convertit un `Decimal` en nombre Python pour Excel et les rapports JSON.

    Les valeurs entières sont rendues en `int` (39 200 et non 39200.0) : les
    montants CAMWATER sont en FCFA, sans centimes, et un `.0` parasite rend les
    rapports d'anomalies plus difficiles à relire. `None` est conservé.
    """
    if valeur is None:
        return None
    if valeur == valeur.to_integral_value():
        return int(valeur)
    return float(valeur)


@dataclass
class LigneCalculee:
    """Résultat du calcul d'une ligne d'abonnement.

    Les champs `*_derive` indiquent qu'une valeur illisible sur la facture a été
    reconstruite par formule ; `anomalies` recense les écarts non résolus.
    """

    consommation: Optional[Decimal] = None
    location_compteur: Optional[Decimal] = None
    montant_ht: Optional[Decimal] = None
    tva: Optional[Decimal] = None
    montant_ttc: Optional[Decimal] = None
    index_ancien: Optional[Decimal] = None
    index_nouvel: Optional[Decimal] = None
    champs_derives: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return None not in (
            self.consommation,
            self.montant_ht,
            self.tva,
            self.montant_ttc,
        )


def _tva_theorique(montant_ht: Decimal) -> Decimal:
    return arrondi(montant_ht * TAUX_TVA)


def calculer_ligne(brut: dict) -> LigneCalculee:
    """Applique les formules métier et reconstruit les valeurs manquantes.

    `brut` est le dictionnaire issu de l'extraction : chaque valeur est la chaîne
    telle qu'elle apparaît sur la facture (ou `None` / `ILLISIBLE`).

    Stratégie :

    1. lire toutes les valeurs disponibles ;
    2. reconstruire les manquantes dans l'ordre le plus fiable
       (consommation ← index, HT ← consommation, TVA ← HT, TTC ← HT + TVA,
       et inversement HT ← TTC, consommation ← HT) ;
    3. comparer les valeurs lues aux valeurs théoriques et signaler les écarts
       supérieurs à la tolérance.
    """
    resultat = LigneCalculee(
        consommation=parse_nombre(brut.get("consommation")),
        location_compteur=parse_nombre(brut.get("location_compteur")),
        montant_ht=parse_nombre(brut.get("montant_ht")),
        tva=parse_nombre(brut.get("tva")),
        montant_ttc=parse_nombre(brut.get("montant_ttc")),
        index_ancien=parse_nombre(brut.get("index_ancien")),
        index_nouvel=parse_nombre(brut.get("index_nouvel")),
    )

    # La location compteur absente vaut 0 (cas courant sur les abonnements
    # administratifs) ; on ne la dérive pas, on l'initialise.
    location_absente = resultat.location_compteur is None

    # -- Étape 1 : consommation à partir des index -------------------------- #
    if (
        resultat.consommation is None
        and resultat.index_nouvel is not None
        and resultat.index_ancien is not None
    ):
        resultat.consommation = resultat.index_nouvel - resultat.index_ancien
        resultat.champs_derives.append("consommation")
    elif (
        resultat.consommation is not None
        and resultat.index_nouvel is not None
        and resultat.index_ancien is not None
        and resultat.index_nouvel - resultat.index_ancien != resultat.consommation
    ):
        resultat.anomalies.append(
            "Index nouvel - Index ancien "
            f"({resultat.index_nouvel - resultat.index_ancien}) "
            f"≠ Consommation lue ({resultat.consommation})"
        )

    # -- Étape 2 : consommation à partir des montants ----------------------- #
    if resultat.consommation is None:
        base = resultat.montant_ht
        if base is None and resultat.montant_ttc is not None and resultat.tva is not None:
            base = resultat.montant_ttc - resultat.tva
        if base is not None:
            location = resultat.location_compteur or Decimal(0)
            consommation = (base - location) / PRIX_UNITAIRE
            if consommation == consommation.to_integral_value():
                resultat.consommation = consommation.to_integral_value()
                resultat.champs_derives.append("consommation")
            else:
                resultat.anomalies.append(
                    "Consommation illisible et non reconstructible exactement "
                    f"depuis le montant HT ({base})"
                )

    if location_absente and resultat.consommation is not None:
        resultat.location_compteur = Decimal(0)

    # -- Étape 3 : montant HT ----------------------------------------------- #
    ht_theorique: Optional[Decimal] = None
    if resultat.consommation is not None:
        location = resultat.location_compteur or Decimal(0)
        ht_theorique = resultat.consommation * PRIX_UNITAIRE + location

    if resultat.montant_ht is None:
        if ht_theorique is not None:
            resultat.montant_ht = ht_theorique
            resultat.champs_derives.append("montant_ht")
        elif resultat.montant_ttc is not None and resultat.tva is not None:
            resultat.montant_ht = resultat.montant_ttc - resultat.tva
            resultat.champs_derives.append("montant_ht")
    elif ht_theorique is not None and abs(resultat.montant_ht - ht_theorique) > TOLERANCE_MONTANT:
        resultat.anomalies.append(
            f"Montant HT lu ({resultat.montant_ht}) ≠ calculé ({ht_theorique}) "
            f"[Consommation × {PRIX_UNITAIRE} + Location]"
        )

    # -- Étape 4 : TVA ------------------------------------------------------- #
    if resultat.montant_ht is not None:
        tva_theorique = _tva_theorique(resultat.montant_ht)
        if resultat.tva is None:
            resultat.tva = tva_theorique
            resultat.champs_derives.append("tva")
        elif abs(resultat.tva - tva_theorique) > TOLERANCE_MONTANT:
            resultat.anomalies.append(
                f"TVA lue ({resultat.tva}) ≠ ARRONDI(HT × {TAUX_TVA}) = {tva_theorique}"
            )

    # -- Étape 5 : montant TTC ---------------------------------------------- #
    if resultat.montant_ht is not None and resultat.tva is not None:
        ttc_theorique = resultat.montant_ht + resultat.tva
        if resultat.montant_ttc is None:
            resultat.montant_ttc = ttc_theorique
            resultat.champs_derives.append("montant_ttc")
        elif abs(resultat.montant_ttc - ttc_theorique) > TOLERANCE_MONTANT:
            resultat.anomalies.append(
                f"Montant TTC lu ({resultat.montant_ttc}) ≠ HT + TVA ({ttc_theorique})"
            )

    # -- Étape 6 : index manquant reconstructible --------------------------- #
    if resultat.consommation is not None:
        if resultat.index_nouvel is None and resultat.index_ancien is not None:
            resultat.index_nouvel = resultat.index_ancien + resultat.consommation
            resultat.champs_derives.append("index_nouvel")
        elif resultat.index_ancien is None and resultat.index_nouvel is not None:
            resultat.index_ancien = resultat.index_nouvel - resultat.consommation
            resultat.champs_derives.append("index_ancien")

    if resultat.consommation is not None and resultat.consommation < 0:
        resultat.anomalies.append(
            f"Consommation négative ({resultat.consommation}) — index probablement inversés"
        )

    return resultat
