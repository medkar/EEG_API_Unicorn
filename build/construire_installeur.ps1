# Construit l'installeur Windows de « EEG API Unicorn ».
#
# Usage, depuis n'importe quel dossier :
#
#     powershell -ExecutionPolicy Bypass -File build\construire_installeur.ps1
#
# Étapes : vérifier les outils, lire la version, nettoyer, PyInstaller (le dossier du programme),
# poser les avis de licence, vérifier le programme construit, puis Inno Setup (l'installeur).
# Résultat : `build\sortie\EEG-API-Unicorn-Setup-<version>.exe`, et à côté `sources-lgpl.md` (le
# bloc des sources LGPL, pour les notes de la Release). Voir `build\LISEZMOI.md`.
#
# ⚠️ Ce fichier est enregistré en UTF-8 AVEC BOM : sans lui, Windows PowerShell 5.1 lit mal les
# accents.

$ErrorActionPreference = "Stop"

$dossierBuild = $PSScriptRoot
$racine = Split-Path -Parent $dossierBuild
Set-Location $racine

# Le Python qui construit : celui de l'environnement du projet (`.venv`) s'il existe, sinon celui
# du PATH. Sur la machine de construction de GitHub (le workflow de release), il n'y a pas de
# `.venv` : les dépendances sont installées dans le Python de la machine.
$python = Join-Path $racine ".venv\Scripts\python.exe"
$sansVenv = -not (Test-Path $python)
if ($sansVenv) {
    $commande = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $python = if ($commande) { $commande.Source } else { $null }
}
$dossierApp = Join-Path $racine "dist\EEG API Unicorn"
$dossierTravail = Join-Path $dossierBuild "eeg_api_unicorn"     # le brouillon de PyInstaller
$dossierSortie = Join-Path $dossierBuild "sortie"

function Arreter($message, $conseil) {
    Write-Host "ERREUR : $message" -ForegroundColor Red
    if ($conseil) { Write-Host "  $conseil" }
    exit 1
}

# Lance un programme, affiche tout ce qu'il écrit et rend son code de sortie. PyInstaller écrit
# son journal sur la sortie d'erreur : sans le `"$_"`, Windows PowerShell 5.1 présenterait ces
# lignes comme des erreurs en rouge ; c'est le code de sortie qui dit si ça a marché.
function Lancer($programme, [string[]]$arguments) {
    $ErrorActionPreference = "Continue"
    & $programme @arguments 2>&1 | ForEach-Object { "$_" } | Out-Host
    return $LASTEXITCODE
}

function TailleMo($chemin) {
    $octets = (Get-ChildItem $chemin -Recurse -File | Measure-Object -Property Length -Sum).Sum
    return "{0:N0} Mo" -f ($octets / 1MB)
}

Write-Host "=== Installeur EEG API Unicorn ===" -ForegroundColor Cyan
Write-Host "Dépôt : $racine"

# --- 1. Les outils ---------------------------------------------------------------------------
if (-not $python) {
    Arreter "aucun Python : ni environnement .venv à la racine du dépôt, ni python dans le PATH." `
        "Crée l'environnement : python -m venv .venv ; .venv\Scripts\python.exe -m pip install -r requirements.txt -c build\contraintes.txt pyinstaller==6.22.3"
}
Write-Host "  [OK] Python : $python$(if ($sansVenv) { ' (pas de .venv : celui du PATH)' })"
& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Arreter "PyInstaller n'est pas installé dans ce Python ($python)." `
        "Installe-le : `"$python`" -m pip install pyinstaller==6.22.3"
}
Write-Host "  [OK] PyInstaller $(& $python -m PyInstaller --version)"

# Inno Setup s'installe pour tous (Program Files) ou pour soi seul (AppData\Local\Programs).
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Arreter "Inno Setup 6 est introuvable." `
        "Installe-le : winget install --id JRSoftware.InnoSetup -e"
}
Write-Host "  [OK] Inno Setup : $iscc"

# --- 2. La version : écrite à un seul endroit, src\core\version.py ----------------------------
$ligne = Select-String -Path (Join-Path $racine "src\core\version.py") -Pattern '^VERSION = "(.*)"$'
if (-not $ligne) { Arreter "aucune ligne VERSION = ""X.Y.Z"" dans src\core\version.py." }
$version = $ligne.Matches[0].Groups[1].Value
Write-Host "  [OK] version $version"

# --- 3. Nettoyer ce qu'une construction précédente a laissé -----------------------------------
foreach ($d in @($dossierApp, $dossierTravail, $dossierSortie)) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

# --- 4. PyInstaller : le dossier du programme --------------------------------------------------
Write-Host "PyInstaller (quelques minutes)…" -ForegroundColor Yellow
$codePyInstaller = Lancer $python @("-m", "PyInstaller", (Join-Path $dossierBuild "eeg_api_unicorn.spec"),
    "--noconfirm", "--distpath", (Join-Path $racine "dist"), "--workpath", $dossierBuild)
if ($codePyInstaller -ne 0) { Arreter "PyInstaller a échoué (code $codePyInstaller)." }
foreach ($exe in @("EEG API Unicorn.exe", "eeg-api-unicorn-cli.exe")) {
    if (-not (Test-Path (Join-Path $dossierApp $exe))) { Arreter "$exe manque dans $dossierApp." }
}
Write-Host "  [OK] $dossierApp : $(TailleMo $dossierApp)"

# --- 5. Les avis de licence --------------------------------------------------------------------
# À côté des exécutables : LICENSE (la licence MIT du programme) et THIRD-PARTY-NOTICES.txt, la
# licence de tout ce que le programme embarque. `licences_tierces.py` l'écrit avec le Python qui
# vient de construire, donc pour les versions réellement embarquées, et REFUSE s'il manque la
# licence d'un composant.
#
# Puis, à côté de l'installeur, `sources-lgpl.md` : la version et l'adresse du code source de
# chaque composant sous LGPL (Qt, PySide6, FFmpeg, pygame). Le workflow de release le recopie
# dans les notes de la Release ; le script REFUSE si un composant sous LGPL du programme n'y est
# pas, ou si sa version n'est pas celle des adresses relevées.
Write-Host "Avis de licence…" -ForegroundColor Yellow
Copy-Item (Join-Path $racine "LICENSE") $dossierApp
$codeAvis = Lancer $python @((Join-Path $dossierBuild "licences_tierces.py"), $dossierApp)
if ($codeAvis -ne 0) { Arreter "les avis de licence ne sont pas écrits (code $codeAvis) : voir l'ÉCHEC ci-dessus." }
foreach ($avis in @("LICENSE", "THIRD-PARTY-NOTICES.txt")) {
    if (-not (Test-Path (Join-Path $dossierApp $avis))) { Arreter "$avis manque dans $dossierApp." }
}
New-Item -ItemType Directory -Force $dossierSortie | Out-Null
$sourcesLgpl = Join-Path $dossierSortie "sources-lgpl.md"
$codeSources = Lancer $python @((Join-Path $dossierBuild "licences_tierces.py"), "--sources-lgpl", $dossierApp, $sourcesLgpl)
if ($codeSources -ne 0) { Arreter "les sources LGPL ne sont pas écrites (code $codeSources) : voir l'ÉCHEC ci-dessus." }
if (-not (Test-Path $sourcesLgpl)) { Arreter "$sourcesLgpl manque." }
Write-Host "  [OK] LICENSE, THIRD-PARTY-NOTICES.txt, sources-lgpl.md"

# --- 6. Le programme construit charge-t-il tout ce dont il a besoin ? --------------------------
# `--verifier-modules` importe les bibliothèques, vérifie qu'il n'y a que les DLL de BrainFlow
# voulues, fait servir chaque DLL (le board de test, un filtre, le SDK du casque, LSL), puis
# entraîne, enregistre et relit un petit modèle de chaque sorte (dans un dossier temporaire). Un
# module oublié par PyInstaller se voit ici, pas chez l'utilisateur.
Write-Host "Vérification du programme construit…" -ForegroundColor Yellow
$codeVerif = Lancer (Join-Path $dossierApp "eeg-api-unicorn-cli.exe") @("--verifier-modules")
if ($codeVerif -ne 0) { Arreter "le programme construit est incomplet (code $codeVerif) : voir la ligne ÉCHEC ci-dessus." }
Write-Host "  [OK] modules, DLL et modèles"

# --- 7. Inno Setup : l'installeur ---------------------------------------------------------------
Write-Host "Inno Setup (compression, quelques minutes)…" -ForegroundColor Yellow
$codeIscc = Lancer $iscc @("/Q", "/DVersionApp=$version", (Join-Path $dossierBuild "installeur.iss"))
if ($codeIscc -ne 0) { Arreter "Inno Setup a échoué (code $codeIscc)." }
$installeur = Join-Path $dossierSortie "EEG-API-Unicorn-Setup-$version.exe"
if (-not (Test-Path $installeur)) { Arreter "$installeur introuvable après Inno Setup." }

Write-Host ""
Write-Host "=== Terminé ===" -ForegroundColor Green
Write-Host "Programme   : $dossierApp ($(TailleMo $dossierApp))"
Write-Host "Installeur  : $installeur ($(TailleMo $installeur))"
Write-Host "Sources LGPL: $sourcesLgpl (pour les notes de la Release)"
