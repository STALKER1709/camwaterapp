"""Constantes, chemins et paramètres d'environnement de l'application.

Tous les réglages sont surchargeables par variable d'environnement (ou par un
fichier `.env` chargé au démarrage), ce qui permet de déployer la même image sur
plusieurs postes sans modifier le code.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

try:  # chargement optionnel du .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dépendance optionnelle
    pass


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "oui", "on"}


# --------------------------------------------------------------------------- #
# Arborescence
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = _env_path("CAMWATER_DATA_DIR", BASE_DIR / "data")
UPLOAD_DIR = _env_path("CAMWATER_UPLOAD_DIR", DATA_DIR / "uploads")
PROCESSED_DIR = _env_path("CAMWATER_PROCESSED_DIR", DATA_DIR / "processed")
ERROR_DIR = _env_path("CAMWATER_ERROR_DIR", DATA_DIR / "errors")
INBOX_DIR = _env_path("CAMWATER_INBOX_DIR", DATA_DIR / "inbox")
OUTPUT_DIR = _env_path("CAMWATER_OUTPUT_DIR", DATA_DIR / "output")
REPORT_DIR = _env_path("CAMWATER_REPORT_DIR", DATA_DIR / "reports")
LOG_DIR = _env_path("CAMWATER_LOG_DIR", BASE_DIR / "logs")
STATIC_DIR = BASE_DIR / "static"

EXCEL_FILENAME = os.getenv("CAMWATER_EXCEL_FILENAME", "CAMWATER_Pointage_General.xlsx")
EXCEL_PATH = OUTPUT_DIR / EXCEL_FILENAME
EXCEL_LOCK_PATH = OUTPUT_DIR / (EXCEL_FILENAME + ".lock")
LOG_FILE = LOG_DIR / "app.log"

ALL_DIRS = (
    DATA_DIR,
    UPLOAD_DIR,
    PROCESSED_DIR,
    ERROR_DIR,
    INBOX_DIR,
    OUTPUT_DIR,
    REPORT_DIR,
    LOG_DIR,
)


def ensure_directories() -> None:
    """Crée l'ensemble des dossiers de travail s'ils n'existent pas."""
    for directory in ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Fichiers acceptés
# --------------------------------------------------------------------------- #

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}

MAX_UPLOAD_BYTES = _env_int("CAMWATER_MAX_UPLOAD_MB", 50) * 1024 * 1024

#: Rendu des PDF. 300 DPI dépasse volontairement la taille lue par le modèle :
#: on réduit ensuite nous-mêmes en Lanczos (sur-échantillonnage), ce qui rend
#: les traits fins plus nets qu'un rendu direct à la taille cible.
PDF_DPI = _env_int("CAMWATER_PDF_DPI", 300)
MAX_PAGES = _env_int("CAMWATER_MAX_PAGES", 40)

#: Grand côté lu par les modèles haute résolution (Claude Opus 5, Opus 4.7/4.8,
#: Sonnet 5). À 200 DPI, une page A4 ne faisait que 2338 px : 9 % de finesse
#: perdue sur des chiffres déjà masqués par le tampon.
MAX_COTE_LONG = _env_int("CAMWATER_COTE_LONG", 2576)

#: Atténuation du tampon bleu par extraction du canal rouge. Dépend de la teinte
#: réelle du tampon : à valider à l'œil (tools/apercu_pretraitement.py) avant
#: activation.
ATTENUER_TAMPON = _env_bool("CAMWATER_ATTENUER_TAMPON", False)

#: Double lecture indépendante de chaque page, puis comparaison chiffre à
#: chiffre. Double le coût, mais détecte les erreurs de lecture qu'une passe
#: unique rapporte avec assurance.
DOUBLE_LECTURE = _env_bool("CAMWATER_DOUBLE_LECTURE", False)

# --------------------------------------------------------------------------- #
# Modèle LLM (lecture visuelle)
# --------------------------------------------------------------------------- #

# Le modèle par défaut est le plus capable disponible : la lecture visuelle de
# scans tramés (watermark bleu) est la partie la plus critique du pipeline.
LLM_MODEL = os.getenv("CAMWATER_MODEL", "claude-opus-5")
LLM_EFFORT = os.getenv("CAMWATER_EFFORT", "high")  # low | medium | high | xhigh | max
LLM_MAX_TOKENS = _env_int("CAMWATER_MAX_TOKENS", 32000)
LLM_MAX_RETRIES = _env_int("CAMWATER_LLM_RETRIES", 3)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --------------------------------------------------------------------------- #
# Règles métier
# --------------------------------------------------------------------------- #

PRIX_UNITAIRE = Decimal(os.getenv("CAMWATER_PRIX_UNITAIRE", "382"))
TAUX_TVA = Decimal(os.getenv("CAMWATER_TAUX_TVA", "0.1925"))

#: Écart absolu (en FCFA) toléré entre un total lu sur la facture et le total
#: recalculé. Au-delà, la ligne / la facture est marquée `À_VÉRIFIER`.
TOLERANCE_MONTANT = Decimal(os.getenv("CAMWATER_TOLERANCE", "1"))

#: Marqueurs normalisés utilisés dans l'Excel et les rapports.
MARQUEUR_ILLISIBLE = "ILLISIBLE"
MARQUEUR_A_VERIFIER = "À_VÉRIFIER"

#: Ligne écartée du pointage : sans numéro de compte client, une ligne de
#: facture est nulle. Elle n'est ni comptabilisée ni intégrée aux feuilles par
#: ministère, mais conservée à part pour contrôle (jamais supprimée).
MARQUEUR_ECARTEE = "ÉCARTÉE"

#: Les 17 colonnes standard, dans l'ordre exact du fichier de pointage.
COLONNES = (
    "DR",
    "Agence",
    "Période",
    "Compte client",
    "Nom du client",
    "Ville",
    "Code abonnement (PL)",
    "Nom abonné",
    "N° compteur",
    "Index nouvel",
    "Index ancien",
    "Consommation",
    "Location compteur",
    "TVA",
    "Montant HT",
    "Ministère_2026",
    "Montant TTC",
)

#: Colonnes numériques (formatées en nombre dans l'Excel).
COLONNES_NUMERIQUES = frozenset(
    {
        "Index nouvel",
        "Index ancien",
        "Consommation",
        "Location compteur",
        "TVA",
        "Montant HT",
        "Montant TTC",
    }
)

#: Colonnes obligatoirement renseignées pour qu'une ligne soit considérée saine.
COLONNES_OBLIGATOIRES = (
    "Agence",
    "Période",
    "Compte client",
    "Nom du client",
    "Code abonnement (PL)",
    "Nom abonné",
    "Consommation",
    "Montant HT",
    "TVA",
    "Montant TTC",
    "Ministère_2026",
)

FEUILLE_RESUME = "Résumé"
FEUILLE_ANOMALIES = "Anomalies"
FEUILLE_JOURNAL = "Journal"
FEUILLE_ECARTEES = "Lignes écartées"

#: Colonne identifiant une facture au sens métier : deux factures partageant le
#: même compte client et la même période sont un doublon, même si les fichiers
#: scannés diffèrent (re-scan, recadrage, autre nom de fichier).
CLE_FACTURE = ("Compte client", "Période")

#: Compléter le Résumé avec les mois sans facture, entre la plus ancienne et la
#: plus récente période présente, pour rendre les manques visibles.
COMPLETER_MOIS_MANQUANTS = _env_bool("CAMWATER_COMPLETER_MOIS", True)

#: Feuille unique si l'on ne veut pas ventiler par administration.
FEUILLE_UNIQUE = os.getenv("CAMWATER_FEUILLE_UNIQUE", "").strip()

#: Refuser deux fois le même fichier (même empreinte SHA-256).
REJETER_DOUBLONS = _env_bool("CAMWATER_REJETER_DOUBLONS", True)

MOIS_FR = (
    "janv",
    "févr",
    "mars",
    "avr",
    "mai",
    "juin",
    "juil",
    "août",
    "sept",
    "oct",
    "nov",
    "déc",
)
