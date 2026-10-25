<#
.SYNOPSIS
  Installe Agent TAG sur ce poste Windows (environnement Python et fichier .env). Usage TEST.
.DESCRIPTION
  1. vérifie Python (3.11 ou plus, 64 bits) ;
  2. crée l'environnement virtuel .venv et y installe les dépendances figées (requirements.lock) ;
  3. installe Agent TAG lui-même en mode éditable ;
  4. crée .env à partir de .env.example s'il n'existe pas (port PostgreSQL ajusté) ;
  5. vérifie la présence du classeur de référence et, si possible, la connexion PostgreSQL.
  Ne crée ni rôle ni base PostgreSQL : voir preparer-postgres.ps1.
.PARAMETER PortPostgres
  5433 avec Docker (docker-compose.yml) ; en général 5432 avec l'installateur PostgreSQL Windows.
.PARAMETER AvecTests
  Installe aussi pytest et httpx (requirements-dev.lock) pour lancer-tests.ps1.
#>
param([int]$PortPostgres = 5433, [switch]$AvecTests)
. "$PSScriptRoot\commun.ps1"

Write-Etape "Dossier du projet : $Racine"
if ($Racine -match 'OneDrive') {
    Write-Attention "le projet est dans OneDrive : la synchronisation peut verrouiller .venv. Un dossier local (ex. C:\agent-tag) est préférable."
}

Write-Etape 'Python'
$python = $null
foreach ($candidat in @(@('py', '-3'), @('python'))) {
    $cmd = Get-Command $candidat[0] -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    if ($cmd.Source -like '*\WindowsApps\*') { continue }   # alias du Microsoft Store, pas un vrai Python
    $args0 = @($candidat | Select-Object -Skip 1)
    $sortie = Invoke-Silencieux $candidat[0] ($args0 + @('-c', "import sys,struct;print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"))
    if ($LASTEXITCODE -eq 0 -and $sortie) { $python = $candidat; break }
}
if (-not $python) {
    Stop-Erreur "Python introuvable. Installez Python 3.12 ou 3.13 (64 bits) depuis https://www.python.org/downloads/windows/ en cochant « Add python.exe to PATH », puis rouvrez PowerShell."
}
$version, $bits = "$sortie".Trim().Split(' ')
$maj, $min = $version.Split('.') | ForEach-Object { [int]$_ }
if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 11)) { Stop-Erreur "Python $version trouvé ; 3.11 ou plus est requis." }
if ($bits -ne '64') { Stop-Erreur "Python $version $bits bits : la version 64 bits est requise (pilote PostgreSQL)." }
Write-Ok "Python $version, $bits bits ($($python -join ' '))"

Write-Etape 'Environnement virtuel .venv'
if (Test-Path -LiteralPath $PythonVenv) {
    Write-Ok '.venv existe déjà (réutilisé)'
} else {
    $argsVenv = @($python | Select-Object -Skip 1) + @('-m', 'venv', '.venv')
    Invoke-Natif $python[0] $argsVenv 'création de .venv impossible'
    Write-Ok '.venv créé'
}

Write-Etape 'Dépendances (versions figées)'
$verrou = if ($AvecTests) { 'requirements-dev.lock' } else { 'requirements.lock' }
Invoke-Natif $PythonVenv @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $verrou) "installation de $verrou impossible"
Invoke-Natif $PythonVenv @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '-e', '.') "installation d'Agent TAG impossible"
Invoke-Natif $PythonVenv @('-c', 'import agent_tag.api.app, psycopg, openpyxl, networkx; print("    import OK, psycopg", psycopg.__version__)') 'les modules ne se chargent pas'
Write-Ok "dépendances installées depuis $verrou"

Write-Etape 'Fichier .env'
$env_ = Join-Path $Racine '.env'
if (Test-Path -LiteralPath $env_) {
    Write-Attention '.env existe déjà : il est conservé tel quel (vérifiez le port et les mots de passe).'
} else {
    $texte = Get-Content -LiteralPath (Join-Path $Racine '.env.example') -Raw -Encoding UTF8
    $texte = $texte -replace '@localhost:5433/', "@localhost:$PortPostgres/"
    [IO.File]::WriteAllText($env_, $texte, (New-Object Text.UTF8Encoding($false)))
    Write-Ok ".env créé (usage TEST, PostgreSQL sur le port $PortPostgres)"
}
Write-Attention 'Les mots de passe de .env (owner_test, app_test) sont des valeurs de TEST publiées : jamais en production.'

Write-Etape 'Classeur de référence'
$classeur = Join-Path $Racine 'donnees\reference\Base_Allocation_Production_150_Ouvriers_v2.xlsx'
if (Test-Path -LiteralPath $classeur) { Write-Ok 'présent' } else { Stop-Erreur "classeur absent : $classeur" }

Write-Etape 'Connexion PostgreSQL (rôle propriétaire de TEST)'
Invoke-Silencieux $PythonVenv @('-c', 'import psycopg; from agent_tag.config import settings; c = settings.charger(); psycopg.connect(c.owner_url, connect_timeout=5).close()') | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Ok 'connexion réussie'
} else {
    Write-Attention "connexion impossible pour l'instant : préparez PostgreSQL avec .\scripts\windows\preparer-postgres.ps1"
}

Write-Host ''
Write-Host 'Installation terminée. Étapes suivantes :' -ForegroundColor Green
Write-Host '  .\scripts\windows\preparer-postgres.ps1 -Mode Docker   (ou -Mode Local -Port 5432)'
Write-Host '  .\scripts\windows\initialiser-demo.ps1'
Write-Host '  .\scripts\windows\demarrer.ps1'
