"""Contrôles de cohérence et génération des rapports d'erreur.

Politique « zéro erreur tolérée » : aucune ligne n'est écartée silencieusement.
Une valeur douteuse est soit **reconstruite par formule** (et marquée comme
dérivée), soit **signalée** — jamais devinée.

Trois niveaux de statut par ligne :

* ``OK``          — toutes les colonnes obligatoires présentes et cohérentes ;
* ``À_VÉRIFIER``  — écart de total, ministère indéterminé, valeur dérivée dont
                    la source était douteuse : la ligne est écrite mais signalée ;
* ``ILLISIBLE``   — une donnée obligatoire est absente et non reconstructible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .calculs import arrondi, parse_nombre
from .config import (
    COLONNES_OBLIGATOIRES,
    MARQUEUR_A_VERIFIER,
    MARQUEUR_ILLISIBLE,
    REPORT_DIR,
    TAUX_TVA,
    TOLERANCE_MONTANT,
)
from .mapping import MAPPING_HORS_PERIMETRE
from .models import STATUT_OK, LigneFacture, RapportTraitement

logger = logging.getLogger(__name__)

__all__ = [
    "ControleTotaux",
    "controler_totaux",
    "ecrire_rapport",
    "valider_ligne",
    "valider_rapport",
]

#: Colonnes dont l'absence rend la ligne inexploitable pour le pointage.
_CRITIQUES = frozenset({"Consommation", "Montant HT", "TVA", "Montant TTC"})


def valider_ligne(ligne: LigneFacture) -> LigneFacture:
    """Contrôle une ligne construite et fixe son statut définitif.

    Vérifie : présence des colonnes obligatoires, cohérence interne
    (HT + TVA = TTC, taux de TVA), plausibilité des index et du ministère.
    """
    valeurs = ligne.valeurs

    # 1. Colonnes obligatoires -------------------------------------------- #
    for colonne in COLONNES_OBLIGATOIRES:
        valeur = valeurs.get(colonne)
        vide = valeur is None or (isinstance(valeur, str) and not valeur.strip())
        if not vide:
            continue
        if colonne in _CRITIQUES:
            valeurs[colonne] = MARQUEUR_ILLISIBLE
            ligne.marquer(
                MARQUEUR_ILLISIBLE,
                f"Colonne obligatoire « {colonne} » illisible et non reconstructible",
            )
        else:
            ligne.marquer(
                MARQUEUR_A_VERIFIER,
                f"Colonne obligatoire « {colonne} » absente",
            )

    # 2. Cohérence arithmétique -------------------------------------------- #
    ht = parse_nombre(valeurs.get("Montant HT"))
    tva = parse_nombre(valeurs.get("TVA"))
    ttc = parse_nombre(valeurs.get("Montant TTC"))

    if None not in (ht, tva, ttc):
        if abs((ht + tva) - ttc) > TOLERANCE_MONTANT:
            ligne.marquer(
                MARQUEUR_A_VERIFIER,
                f"HT ({ht}) + TVA ({tva}) = {ht + tva} ≠ TTC ({ttc})",
            )
        tva_attendue = arrondi(ht * TAUX_TVA)
        if abs(tva - tva_attendue) > TOLERANCE_MONTANT:
            ligne.marquer(
                MARQUEUR_A_VERIFIER,
                f"TVA ({tva}) ≠ ARRONDI(HT × {TAUX_TVA}) = {tva_attendue}",
            )

    # 3. Plausibilité des index -------------------------------------------- #
    index_nouvel = parse_nombre(valeurs.get("Index nouvel"))
    index_ancien = parse_nombre(valeurs.get("Index ancien"))
    consommation = parse_nombre(valeurs.get("Consommation"))
    if None not in (index_nouvel, index_ancien, consommation):
        if index_nouvel - index_ancien != consommation:
            ligne.marquer(
                MARQUEUR_A_VERIFIER,
                f"Index nouvel ({index_nouvel}) − Index ancien ({index_ancien}) "
                f"≠ Consommation ({consommation})",
            )
    if consommation is not None and consommation < 0:
        ligne.marquer(MARQUEUR_A_VERIFIER, f"Consommation négative ({consommation})")

    # 4. Ministère ---------------------------------------------------------- #
    ministere = str(valeurs.get("Ministère_2026") or "")
    if ministere in {MARQUEUR_A_VERIFIER, ""}:
        ligne.marquer(
            MARQUEUR_A_VERIFIER,
            "Ministère non déterminé à partir des libellés (affectation manuelle requise)",
        )
    elif ministere == MAPPING_HORS_PERIMETRE:
        ligne.marquer(
            MARQUEUR_A_VERIFIER,
            "Abonné identifié comme entité non gouvernementale (hors périmètre)",
        )

    # 5. Valeurs dérivées ---------------------------------------------------- #
    if ligne.champs_derives:
        derives = ", ".join(sorted(set(ligne.champs_derives)))
        note = f"Valeur(s) reconstruite(s) par formule : {derives}"
        if note not in ligne.anomalies:
            ligne.anomalies.append(note)

    return ligne


@dataclass
class ControleTotaux:
    """Comparaison entre totaux imprimés sur la facture et totaux recalculés."""

    lus: dict[str, Optional[Decimal]] = field(default_factory=dict)
    calcules: dict[str, Decimal] = field(default_factory=dict)
    ecarts: list[str] = field(default_factory=list)

    @property
    def coherent(self) -> bool:
        return not self.ecarts


def controler_totaux(
    lignes: list[LigneFacture],
    total_ht: Optional[str],
    total_tva: Optional[str],
    total_ttc: Optional[str],
) -> ControleTotaux:
    """Somme les lignes et compare aux totaux lus en pied de facture."""
    controle = ControleTotaux()

    somme_ht = sum((ligne.montant("Montant HT") for ligne in lignes), Decimal(0))
    somme_tva = sum((ligne.montant("TVA") for ligne in lignes), Decimal(0))
    somme_ttc = sum((ligne.montant("Montant TTC") for ligne in lignes), Decimal(0))
    controle.calcules = {"HT": somme_ht, "TVA": somme_tva, "TTC": somme_ttc}
    controle.lus = {
        "HT": parse_nombre(total_ht),
        "TVA": parse_nombre(total_tva),
        "TTC": parse_nombre(total_ttc),
    }

    # Une ligne illisible fausse mécaniquement la somme : on le dit plutôt que
    # de conclure à un écart de saisie.
    lignes_illisibles = sum(1 for ligne in lignes if ligne.statut == MARQUEUR_ILLISIBLE)

    for cle, somme in controle.calcules.items():
        lu = controle.lus.get(cle)
        if lu is None:
            continue
        ecart = somme - lu
        if abs(ecart) > TOLERANCE_MONTANT:
            message = (
                f"Total {cle} : somme des lignes = {somme}, "
                f"total imprimé sur la facture = {lu} (écart {ecart})"
            )
            if lignes_illisibles:
                message += f" — {lignes_illisibles} ligne(s) illisible(s) non sommée(s)"
            controle.ecarts.append(message)

    return controle


def valider_rapport(rapport: RapportTraitement) -> RapportTraitement:
    """Valide toutes les lignes, contrôle les totaux et consolide les anomalies."""
    for ligne in rapport.lignes:
        valider_ligne(ligne)

    controle = controler_totaux(
        rapport.lignes,
        rapport.totaux_lus.get("HT"),
        rapport.totaux_lus.get("TVA"),
        rapport.totaux_lus.get("TTC"),
    )
    rapport.totaux_calcules = {cle: str(val) for cle, val in controle.calcules.items()}
    rapport.anomalies.extend(controle.ecarts)

    # Un écart de total est un signal facture, pas ligne : on marque les lignes
    # non encore signalées pour qu'aucun montant douteux ne passe inaperçu.
    if controle.ecarts:
        for ligne in rapport.lignes:
            if ligne.statut == STATUT_OK:
                ligne.marquer(
                    MARQUEUR_A_VERIFIER,
                    "Écart constaté sur les totaux de la facture — contrôle requis",
                )

    for ligne in rapport.lignes:
        for anomalie in ligne.anomalies:
            entree = f"ligne {ligne.numero} : {anomalie}"
            if entree not in rapport.anomalies:
                rapport.anomalies.append(entree)

    if rapport.confiance and rapport.confiance < 0.7:
        rapport.anomalies.append(
            f"Confiance de lecture faible ({rapport.confiance:.2f}) — "
            "relecture humaine recommandée"
        )

    return rapport


def ecrire_rapport(rapport: RapportTraitement, dossier: Optional[Path] = None) -> Path:
    """Écrit le rapport JSON de traitement et retourne son chemin."""
    dossier = dossier or REPORT_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    base = Path(rapport.fichier).stem
    chemin = dossier / f"{base}.rapport.json"

    # Ne jamais écraser un rapport existant : suffixer si nécessaire.
    compteur = 1
    while chemin.exists():
        chemin = dossier / f"{base}.rapport.{compteur}.json"
        compteur += 1

    chemin.write_text(
        json.dumps(rapport.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rapport.chemin_rapport = str(chemin)
    logger.info("Rapport écrit : %s", chemin)
    return chemin
