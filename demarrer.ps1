<#
    Démarrage de l'application CAMWATER sous Windows.

    Enchaîne : détection de Python, création du venv, installation des
    dépendances, saisie de la clé API si besoin, puis lancement du serveur.

    Utilisation :
        clic droit sur demarrer.bat  ->  Ouvrir
    ou, depuis PowerShell :
        .\demarrer.ps1
        .\demarrer.ps1 -Tests        (lance la suite de tests, sans clé API)
#>

param(
    [switch]$Tests,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Ecrire($texte, $couleur = "Gray") { Write-Host $texte -ForegroundColor $couleur }

Ecrire "=== CAMWATER - extraction automatique de factures ===" "Cyan"
Ecrire ""

# --- 1. Trouver un interpréteur Python -------------------------------------
# Détection volontairement tolérante : sous PowerShell 5.1, « 2>&1 » combiné à
# ErrorActionPreference = Stop transforme la moindre sortie d'erreur d'un
# programme externe en erreur bloquante — ce que produit justement l'alias
# Microsoft Store. On relâche le réglage le temps de la détection.
$python = $null
$anciennePreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
foreach ($candidat in @("py", "python3", "python")) {
    try {
        $version = & $candidat --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$version" -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 10) {
                $python = $candidat
                Ecrire "Python detecte : $version (commande '$candidat')" "Green"
                break
            }
            Ecrire "Ignore : $version (3.10 minimum requis)" "DarkYellow"
        }
    } catch { }
}
$ErrorActionPreference = $anciennePreference

if (-not $python) {
    Ecrire "Python 3.10+ est introuvable." "Red"
    Ecrire ""
    Ecrire "Installez-le avec :   winget install --id Python.Python.3.12 -e"
    Ecrire "puis FERMEZ et ROUVREZ cette fenetre."
    Ecrire ""
    Ecrire "Si 'python' ouvre le Microsoft Store, desactivez l'alias :"
    Ecrire "  Parametres > Applications > Parametres avances des applications"
    Ecrire "  > Alias d'execution d'application > desactiver python.exe"
    Read-Host "`nAppuyez sur Entree pour fermer"
    exit 1
}

# --- 2. Créer l'environnement virtuel si absent -----------------------------
$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Ecrire "Creation de l'environnement virtuel (venv)..." "Yellow"
    & $python -m venv venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        Ecrire "Echec de la creation du venv." "Red"
        Ecrire "Verifiez l'espace disque libre :  Get-PSDrive C | Select-Object Used, Free"
        Read-Host "`nAppuyez sur Entree pour fermer"
        exit 1
    }
    Ecrire "Environnement virtuel cree." "Green"
} else {
    Ecrire "Environnement virtuel deja present." "Green"
}

# --- 3. Installer les dépendances (seulement si nécessaire) -----------------
# L'empreinte de requirements.txt evite de reinstaller a chaque lancement.
$empreinteFichier = Join-Path $PSScriptRoot "venv\.requirements.sha256"
$empreinte = (Get-FileHash -LiteralPath "requirements.txt" -Algorithm SHA256).Hash
$dejaInstalle = (Test-Path -LiteralPath $empreinteFichier) -and
                ((Get-Content -LiteralPath $empreinteFichier -Raw).Trim() -eq $empreinte)

if (-not $dejaInstalle) {
    Ecrire "Installation des dependances (quelques minutes la premiere fois)..." "Yellow"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Ecrire "Echec de l'installation des dependances." "Red"
        Read-Host "`nAppuyez sur Entree pour fermer"
        exit 1
    }
    Set-Content -LiteralPath $empreinteFichier -Value $empreinte -Encoding ASCII
    Ecrire "Dependances installees." "Green"
} else {
    Ecrire "Dependances deja a jour." "Green"
}

# --- 4. Mode tests ----------------------------------------------------------
if ($Tests) {
    Ecrire ""
    Ecrire "Execution de la suite de tests (aucune cle API necessaire)..." "Cyan"
    & $venvPython -m pytest tests -q
    Read-Host "`nAppuyez sur Entree pour fermer"
    exit $LASTEXITCODE
}

# --- 5. Clé API -------------------------------------------------------------
$fichierEnv = Join-Path $PSScriptRoot ".env"
if (-not $env:ANTHROPIC_API_KEY -and -not (Test-Path -LiteralPath $fichierEnv)) {
    Ecrire ""
    Ecrire "Aucune cle API Anthropic detectee." "Yellow"
    Ecrire "Elle est necessaire a la lecture visuelle des factures."
    $cle = Read-Host "Collez votre cle (sk-ant-...) puis Entree, ou Entree seul pour ignorer"
    if ($cle.Trim()) {
        # ASCII volontaire : -Encoding UTF8 ajoute un BOM sous PowerShell 5.1, et
        # python-dotenv lirait alors la variable sous le nom "\ufeffANTHROPIC_API_KEY".
        Set-Content -LiteralPath $fichierEnv -Value "ANTHROPIC_API_KEY=$($cle.Trim())" -Encoding ASCII
        Ecrire "Cle enregistree dans .env (fichier ignore par git)." "Green"
    } else {
        Ecrire "Demarrage sans cle : l'interface s'ouvrira mais l'extraction echouera." "DarkYellow"
    }
}

# --- 6. Lancement -----------------------------------------------------------
Ecrire ""
Ecrire "  Ouvrez votre navigateur sur :  http://localhost:$Port/" "Cyan"
Ecrire "Laissez cette fenetre ouverte. Ctrl+C pour arreter." "DarkGray"
Ecrire ""
& $venvPython app.py --port $Port

Read-Host "`nServeur arrete. Appuyez sur Entree pour fermer"
