# Fonctions communes aux scripts Windows d'Agent TAG (chargé par « . "$PSScriptRoot\commun.ps1" »).
# Compatible Windows PowerShell 5.1 et PowerShell 7. Aucune action n'est faite au chargement,
# sauf se placer à la racine du projet (le fichier .env y est lu).

$ErrorActionPreference = 'Stop'
$Script:Racine = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $Script:Racine
$env:PYTHONUTF8 = '1'          # E/S Python en UTF-8 (console Windows en cp1252/cp850)
$env:PYTHONIOENCODING = 'utf-8'
$Script:PythonVenv = Join-Path $Script:Racine '.venv\Scripts\python.exe'

function Write-Etape([string]$texte) { Write-Host ''; Write-Host "==> $texte" -ForegroundColor Cyan }
function Write-Ok([string]$texte) { Write-Host "    OK  $texte" -ForegroundColor Green }
function Write-Attention([string]$texte) { Write-Host "    !!  $texte" -ForegroundColor Yellow }

function Stop-Erreur([string]$texte) {
    Write-Host ''
    Write-Host "ERREUR : $texte" -ForegroundColor Red
    exit 1
}

function Invoke-Natif {
    # Exécute une commande externe et s'arrête si son code de retour n'est pas 0.
    param([string]$Commande, [string[]]$Arguments, [string]$Echec)
    & $Commande @Arguments
    if ($LASTEXITCODE -ne 0) { Stop-Erreur "$Echec (code $LASTEXITCODE)" }
}

function Invoke-Silencieux {
    # Exécute une commande externe en ignorant sa sortie d'erreur. Sous Windows PowerShell 5.1,
    # « 2>$null » avec ErrorActionPreference=Stop transforme toute ligne d'erreur en arrêt.
    param([string]$Commande, [string[]]$Arguments)
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Commande @Arguments 2>$null } finally { $ErrorActionPreference = $ancien }
}

function Stop-ApiEnregistree {
    # Arrête le processus Python de l'API dont le numéro est dans .agent_tag_api.pid.
    $fichier = Join-Path $Script:Racine '.agent_tag_api.pid'
    if (-not (Test-Path -LiteralPath $fichier)) { return $false }
    $id = [int]((Get-Content -LiteralPath $fichier -TotalCount 1).Trim())
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    $arrete = $false
    if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $id -ErrorAction SilentlyContinue; $arrete = $true }
    Remove-Item -Force -LiteralPath $fichier -ErrorAction SilentlyContinue
    return $arrete
}

function Test-PythonVenv {
    if (-not (Test-Path -LiteralPath $Script:PythonVenv)) {
        Stop-Erreur "environnement Python absent. Exécutez d'abord : .\scripts\windows\installer.ps1"
    }
}

function Get-ValeurEnv([string]$nom) {
    # Lit une variable dans .env (les variables déjà définies dans la session ont priorité,
    # comme dans l'application).
    $deja = [Environment]::GetEnvironmentVariable($nom, 'Process')
    if ($deja) { return $deja }
    $fichier = Join-Path $Script:Racine '.env'
    if (-not (Test-Path -LiteralPath $fichier)) { return $null }
    foreach ($ligne in Get-Content -LiteralPath $fichier -Encoding UTF8) {
        if ($ligne -match "^\s*$([regex]::Escape($nom))\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Set-BaseDansUrl([string]$url, [string]$base) {
    # postgresql://role:mdp@hote:port/ancienne_base -> .../base
    if ($url -notmatch '^(postgres(ql)?://[^/]+)/[^/?]+(\?.*)?$') {
        Stop-Erreur "AGENT_TAG_DATABASE_URL n'a pas la forme attendue postgresql://role:mot_de_passe@hote:port/base"
    }
    return "$($Matches[1])/$base$($Matches[3])"
}
