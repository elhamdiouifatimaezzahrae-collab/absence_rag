<#
.SYNOPSIS
  Prépare PostgreSQL pour Agent TAG en usage TEST : rôles agent_tag_owner / agent_tag_app et base
  agent_tag_test (script docker\init\01_roles_et_base.sql).
.PARAMETER Mode
  Docker : démarre le conteneur de docker-compose.yml (PostgreSQL 16, port 5433).
  Local  : utilise un PostgreSQL installé sur le poste (installateur Windows), via psql et le
           compte superutilisateur « postgres » dont le mot de passe est demandé.
.PARAMETER Port
  Port du PostgreSQL local (Mode Local), 5432 par défaut.
#>
param([Parameter(Mandatory = $true)][ValidateSet('Docker', 'Local')][string]$Mode, [int]$Port = 5432)
. "$PSScriptRoot\commun.ps1"

if ($Mode -eq 'Docker') {
    Write-Etape 'Docker'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-Erreur 'docker introuvable. Installez et démarrez Docker Desktop, ou utilisez -Mode Local.'
    }
    Invoke-Natif docker @('compose', 'up', '-d') 'docker compose up a échoué (Docker Desktop est-il démarré ?)'
    Write-Host '    attente de PostgreSQL (90 s au plus)...'
    $etat = ''
    for ($i = 0; $i -lt 45; $i++) {
        $etat = Invoke-Silencieux docker @('inspect', '-f', '{{.State.Health.Status}}', 'agent_tag_postgres_test')
        if ("$etat".Trim() -eq 'healthy') { break }
        Start-Sleep -Seconds 2
    }
    if ("$etat".Trim() -ne 'healthy') { Stop-Erreur "le conteneur n'est pas prêt (état : $etat). Voir : docker logs agent_tag_postgres_test" }
    Write-Ok 'PostgreSQL 16 prêt sur le port 5433 ; rôles et base de TEST créés au premier démarrage du conteneur'
    exit 0
}

Write-Etape 'PostgreSQL local'
$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) {
    $psql = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.FullName -replace '^.*PostgreSQL\\(\d+).*$', '$1') } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $psql) { Stop-Erreur 'psql introuvable. Installez PostgreSQL 16 (https://www.postgresql.org/download/windows/) ou ajoutez son dossier bin au PATH.' }
Write-Ok "psql : $psql"

$secret = Read-Host "Mot de passe du superutilisateur « postgres » (port $Port)" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret))
$env:PGCLIENTENCODING = 'UTF8'
try {
    $version = & $psql -h localhost -p $Port -U postgres -d postgres -Atc 'SHOW server_version_num'
    if ($LASTEXITCODE -ne 0) { Stop-Erreur "connexion à PostgreSQL impossible sur le port $Port (mot de passe, port ou service arrêté ?)" }
    if ([int]$version -lt 160000) { Write-Attention "PostgreSQL $version : seule la version 16 a été testée." } else { Write-Ok "serveur $version" }
    $existe = & $psql -h localhost -p $Port -U postgres -d postgres -Atc "SELECT count(*) FROM pg_roles WHERE rolname IN ('agent_tag_owner','agent_tag_app')"
    if ("$existe".Trim() -ne '0') {
        Write-Attention 'les rôles Agent TAG existent déjà : rien n''est recréé.'
    } else {
        Invoke-Natif $psql @('-h', 'localhost', '-p', "$Port", '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', 'docker\init\01_roles_et_base.sql') 'création des rôles et de la base de TEST impossible'
        Write-Ok 'rôles agent_tag_owner, agent_tag_app et base agent_tag_test créés (mots de passe de TEST)'
    }
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
if ($Port -ne 5433) {
    Write-Attention "vérifiez que .env utilise le port $Port (installer.ps1 -PortPostgres $Port le fait à la création de .env)."
}
