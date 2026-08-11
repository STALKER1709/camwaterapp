"""Application d'extraction automatique de factures CAMWATER.

Modules principaux :
    config          constantes, chemins, paramètres d'environnement
    calculs         parsing des nombres et formules de facturation
    mapping         affectation du ministère à partir des libellés
    extraction      lecture visuelle des factures via le LLM (Claude)
    validation      contrôles de cohérence et rapports d'erreur
    excel_manager   écriture transactionnelle dans l'Excel général
    pipeline        orchestration du traitement d'une facture
    api             interface HTTP (FastAPI) + page d'upload
    watcher         surveillance d'un dossier partagé (mode sans frontend)
"""

__version__ = "1.0.0"
