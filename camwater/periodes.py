"""Manipulation des périodes de facturation au format `MMM-AAAA`.

Isolé dans son propre module parce que deux modules qui ne peuvent pas
s'importer mutuellement en ont besoin : `pipeline` (normalisation à
l'extraction) et `excel_manager` (détection des mois manquants dans le Résumé).
"""

from __future__ import annotations

from typing import Iterable, Optional

from .config import MOIS_FR

__all__ = [
    "cle_vers_periode",
    "periode_vers_cle",
    "serie_de_mois",
    "mois_manquants",
]


def periode_vers_cle(periode: Optional[str]) -> Optional[tuple[int, int]]:
    """« mars-2026 » → `(2026, 3)`. Retourne `None` si la période est illisible.

    >>> periode_vers_cle("mars-2026")
    (2026, 3)
    >>> periode_vers_cle("ILLISIBLE") is None
    True
    """
    if not periode:
        return None
    texte = str(periode).strip().lower()
    if "-" not in texte:
        return None
    mois_texte, _, annee_texte = texte.rpartition("-")
    mois_texte = mois_texte.strip()
    try:
        annee = int(annee_texte.strip())
    except ValueError:
        return None
    for index, abrege in enumerate(MOIS_FR, start=1):
        if mois_texte == abrege:
            return (annee, index)
    return None


def cle_vers_periode(annee: int, mois: int) -> str:
    """`(2026, 3)` → « mars-2026 »."""
    return f"{MOIS_FR[mois - 1]}-{annee}"


def serie_de_mois(debut: tuple[int, int], fin: tuple[int, int]) -> list[str]:
    """Tous les mois de `debut` à `fin` inclus, dans l'ordre chronologique.

    >>> serie_de_mois((2025, 11), (2026, 2))
    ['nov-2025', 'déc-2025', 'janv-2026', 'févr-2026']
    """
    if debut > fin:
        return []
    mois = []
    annee, index = debut
    while (annee, index) <= fin:
        mois.append(cle_vers_periode(annee, index))
        index += 1
        if index > 12:
            annee, index = annee + 1, 1
    return mois


def mois_manquants(periodes: Iterable[str]) -> list[str]:
    """Mois absents entre la plus ancienne et la plus récente période fournie.

    Les périodes illisibles sont ignorées (elles ne peuvent pas borner l'étendue).

    >>> mois_manquants(["janv-2026", "mars-2026"])
    ['févr-2026']
    """
    cles = sorted(c for c in (periode_vers_cle(p) for p in periodes) if c is not None)
    if len(cles) < 2:
        return []
    presentes = set(cles)
    return [
        periode
        for periode in serie_de_mois(cles[0], cles[-1])
        if periode_vers_cle(periode) not in presentes
    ]
