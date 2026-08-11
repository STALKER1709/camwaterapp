"""Génère un exemple de fichier Excel général, sans appeler le modèle.

Sert à visualiser la structure exacte du livrable (feuilles, colonnes, couleurs,
onglet Résumé, onglet Anomalies, onglet Journal) avant tout traitement réel ::

    python tools/generer_exemple_excel.py            # -> docs/exemple_...xlsx
    python tools/generer_exemple_excel.py mon.xlsx

Les données sont fictives mais parfaitement représentatives : une facture
cohérente, une ligne dont la TVA est reconstruite par formule, et une ligne
partiellement illisible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camwater.excel_manager import ExcelManager  # noqa: E402
from camwater.extraction import FactureExtraite  # noqa: E402
from camwater.logging_setup import configurer_logs  # noqa: E402
from camwater.models import RapportTraitement  # noqa: E402
from camwater.pipeline import construire_lignes  # noqa: E402
from camwater.validation import valider_rapport  # noqa: E402

ENTETE = {
    "dr": "DR CENTRE",
    "agence": "0231",
    "periode": "MARS 2026",
    "compte_client": "0012345678",
    "nom_client": "MINISTERE DE LA SANTE PUBLIQUE",
    "ville": "YAOUNDE",
}

LIGNES = [
    {  # ligne parfaitement lisible et cohérente
        "code_abonnement": "PL-4455",
        "nom_abonne": "HOPITAL CENTRAL DE YAOUNDE",
        "numero_compteur": "A123456",
        "index_nouvel": "1 350",
        "index_ancien": "1 250",
        "consommation": "100",
        "location_compteur": "1 000",
        "tva": "7 546",
        "montant_ht": "39 200",
        "montant_ttc": "46 746",
    },
    {  # TVA et TTC masqués par le tampon : reconstruits par formule
        "code_abonnement": "PL-4456",
        "nom_abonne": "CENTRE DE SANTE INTEGRE DE NKOLBISSON",
        "numero_compteur": "B778899",
        "index_nouvel": "560",
        "index_ancien": "500",
        "consommation": "60",
        "location_compteur": "0",
        "tva": "",
        "montant_ht": "22 920",
        "montant_ttc": "",
    },
    {  # abonné relevant d'un autre ministère que le client
        "code_abonnement": "PL-7781",
        "nom_abonne": "LYCEE DE NGOA EKELLE",
        "numero_compteur": "C445566",
        "index_nouvel": "2 480",
        "index_ancien": "2 300",
        "consommation": "180",
        "location_compteur": "1 500",
        "tva": "13 526",
        "montant_ht": "70 260",
        "montant_ttc": "83 786",
    },
    {  # colonne tronquée à l'impression : ligne marquée ILLISIBLE
        "code_abonnement": "PL-9002",
        "nom_abonne": "COMMISSARIAT CENTRAL N 1",
        "numero_compteur": "D998877",
        "index_nouvel": "ILLISIBLE",
        "index_ancien": "ILLISIBLE",
        "consommation": "ILLISIBLE",
        "location_compteur": "",
        "tva": "ILLISIBLE",
        "montant_ht": "ILLISIBLE",
        "montant_ttc": "ILLISIBLE",
    },
]


def main() -> int:
    configurer_logs()
    cible = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "docs" / "exemple_CAMWATER_Pointage_General.xlsx"
    )
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.unlink(missing_ok=True)

    facture = FactureExtraite(
        entete=dict(ENTETE),
        lignes=[dict(ligne) for ligne in LIGNES],
        total_ht="132 380",
        total_tva="25 484",
        total_ttc="157 864",
        confiance=0.93,
        pages=2,
    )

    rapport = RapportTraitement(fichier="exemple-facture-mars-2026.pdf", confiance=facture.confiance)
    rapport.lignes = construire_lignes(facture)
    rapport.totaux_lus = {"HT": facture.total_ht, "TVA": facture.total_tva, "TTC": facture.total_ttc}
    valider_rapport(rapport)

    gestionnaire = ExcelManager(cible)
    ecrites = gestionnaire.ajouter_lignes(
        rapport.lignes,
        fichier=rapport.fichier,
        empreinte="exemple-sha256-0000",
        utilisateur="poste-demo",
        pages=facture.pages,
        confiance=facture.confiance,
    )

    print(f"\nFichier d'exemple généré : {cible}")
    print(f"  lignes écrites   : {ecrites}")
    print(f"  conformes        : {rapport.nb_ok}")
    print(f"  à vérifier       : {rapport.nb_a_verifier}")
    print(f"  illisibles       : {rapport.nb_illisibles}")
    stats = gestionnaire.statistiques()
    print("  feuilles         : " + ", ".join(f"{f['nom']} ({f['lignes']})" for f in stats["feuilles"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
