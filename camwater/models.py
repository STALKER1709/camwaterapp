"""Structures de données partagées entre les modules du pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .config import (
    COLONNES,
    MARQUEUR_A_VERIFIER,
    MARQUEUR_ECARTEE,
    MARQUEUR_ILLISIBLE,
)

__all__ = ["STATUT_OK", "LigneFacture", "RapportTraitement"]

STATUT_OK = "OK"


@dataclass
class LigneFacture:
    """Une ligne prête à être écrite dans l'Excel général.

    `valeurs` contient exactement les 17 colonnes standard. `statut` vaut
    ``OK``, ``À_VÉRIFIER`` ou ``ILLISIBLE`` ; `anomalies` détaille les écarts et
    `champs_derives` les valeurs reconstruites par formule.
    """

    valeurs: dict[str, Any] = field(default_factory=dict)
    statut: str = STATUT_OK
    anomalies: list[str] = field(default_factory=list)
    champs_derives: list[str] = field(default_factory=list)
    numero: int = 0

    @property
    def est_ok(self) -> bool:
        return self.statut == STATUT_OK

    @property
    def administration(self) -> str:
        return str(self.valeurs.get("Ministère_2026") or MARQUEUR_A_VERIFIER)

    def montant(self, colonne: str) -> Decimal:
        """Montant d'une colonne, `0` si la valeur est absente ou illisible."""
        valeur = self.valeurs.get(colonne)
        if valeur is None or isinstance(valeur, str):
            return Decimal(0)
        montant = Decimal(str(valeur))
        # Évite les « 74078.0 » dans les rapports quand la valeur est entière.
        return montant.to_integral_value() if montant == montant.to_integral_value() else montant

    @property
    def est_ecartee(self) -> bool:
        """Ligne nulle, exclue du pointage (mais conservée pour contrôle)."""
        return self.statut == MARQUEUR_ECARTEE

    def marquer(self, statut: str, anomalie: Optional[str] = None) -> None:
        """Dégrade le statut (OK → À_VÉRIFIER → ILLISIBLE → ÉCARTÉE).

        `ÉCARTÉE` est terminal : une ligne nulle le reste, quels que soient les
        contrôles ultérieurs.
        """
        ordre = {
            STATUT_OK: 0,
            MARQUEUR_A_VERIFIER: 1,
            MARQUEUR_ILLISIBLE: 2,
            MARQUEUR_ECARTEE: 3,
        }
        if ordre.get(statut, 0) > ordre.get(self.statut, 0):
            self.statut = statut
        if anomalie and anomalie not in self.anomalies:
            self.anomalies.append(anomalie)

    def as_row(self) -> list[Any]:
        """Les 17 valeurs dans l'ordre des colonnes."""
        return [self.valeurs.get(colonne) for colonne in COLONNES]

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "statut": self.statut,
            "valeurs": self.valeurs,
            "anomalies": self.anomalies,
            "champs_derives": self.champs_derives,
        }


@dataclass
class RapportTraitement:
    """Compte rendu complet du traitement d'une facture."""

    fichier: str
    empreinte: str = ""
    succes: bool = False
    horodatage: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )
    pages: int = 0
    confiance: float = 0.0
    lignes: list[LigneFacture] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)
    totaux_lus: dict[str, Optional[str]] = field(default_factory=dict)
    totaux_calcules: dict[str, Optional[str]] = field(default_factory=dict)
    erreur: Optional[str] = None
    lignes_ecrites: int = 0
    chemin_archive: Optional[str] = None
    chemin_rapport: Optional[str] = None
    duree_secondes: float = 0.0

    # -- Statistiques dérivées --------------------------------------------- #

    @property
    def nb_lignes(self) -> int:
        return len(self.lignes)

    @property
    def nb_ok(self) -> int:
        return sum(1 for ligne in self.lignes if ligne.statut == STATUT_OK)

    @property
    def nb_a_verifier(self) -> int:
        return sum(1 for ligne in self.lignes if ligne.statut == MARQUEUR_A_VERIFIER)

    @property
    def nb_illisibles(self) -> int:
        return sum(1 for ligne in self.lignes if ligne.statut == MARQUEUR_ILLISIBLE)

    @property
    def nb_ecartees(self) -> int:
        """Lignes nulles (sans numéro de compte), exclues du pointage."""
        return sum(1 for ligne in self.lignes if ligne.statut == MARQUEUR_ECARTEE)

    @property
    def lignes_retenues(self) -> list["LigneFacture"]:
        """Lignes effectivement intégrées au pointage."""
        return [ligne for ligne in self.lignes if ligne.statut != MARQUEUR_ECARTEE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fichier": self.fichier,
            "empreinte_sha256": self.empreinte,
            "succes": self.succes,
            "horodatage": self.horodatage,
            "duree_secondes": round(self.duree_secondes, 2),
            "pages": self.pages,
            "confiance_lecture": round(self.confiance, 3),
            "statistiques": {
                "lignes_extraites": self.nb_lignes,
                "lignes_ecrites": self.lignes_ecrites,
                "lignes_ok": self.nb_ok,
                "lignes_a_verifier": self.nb_a_verifier,
                "lignes_illisibles": self.nb_illisibles,
                "lignes_ecartees": self.nb_ecartees,
            },
            "totaux_lus": self.totaux_lus,
            "totaux_calcules": self.totaux_calcules,
            "anomalies": self.anomalies,
            "remarques": self.remarques,
            "erreur": self.erreur,
            "chemin_archive": self.chemin_archive,
            "chemin_rapport": self.chemin_rapport,
            "lignes": [ligne.to_dict() for ligne in self.lignes],
        }

    def resume(self) -> str:
        if not self.succes:
            return f"ÉCHEC — {self.fichier} : {self.erreur}"
        resume = (
            f"OK — {self.fichier} : {self.lignes_ecrites} ligne(s) écrite(s) "
            f"({self.nb_ok} conformes, {self.nb_a_verifier} à vérifier, "
            f"{self.nb_illisibles} illisibles)"
        )
        if self.nb_ecartees:
            resume += f", {self.nb_ecartees} écartée(s) sans numéro de compte"
        return resume
