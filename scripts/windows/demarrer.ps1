<#
.SYNOPSIS
  Démarre l'API et l'interface d'Agent TAG sur http://127.0.0.1:<Port>/ (base de démonstration
  par défaut) et ouvre le navigateur. Ctrl+C dans cette fenêtre arrête l'application.
#>
param([int]$Port = 8000, [string]$Base = 'agent_tag_demo', [switch]$SansNavigateur)
. "$PSScriptRoot\commun.ps1"
Test-PythonVenv

$url = Get-ValeurEnv 'AGENT_TAG_DATABASE_URL'
if (-not $url) { Stop-Erreur '.env absent ou incomplet : exécutez installer.ps1.' }
$env:AGENT_TAG_DATABASE_URL = Set-BaseDansUrl $url $Base

$occupe = $false
try { $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port); $l.Start(); $l.Stop() } catch { $occupe = $true }
if ($occupe) { Stop-Erreur "le port $Port est déjà utilisé (Agent TAG déjà lancé ?). Utilisez arreter.ps1 ou -Port 8001." }

Write-Etape "Contrôle de démarrage sur la base $Base"
Invoke-Natif $PythonVenv @('-m', 'agent_tag.cli', 'verifier') "contrôle de démarrage refusé (base $Base absente ? lancez initialiser-demo.ps1)"

Write-Etape "Démarrage sur http://127.0.0.1:$Port/  (Ctrl+C pour arrêter)"
Write-Attention 'Démonstration TEST : données fictives, paramètres provisoires, aucune authentification.'
# Le python.exe de .venv est un lanceur qui démarre un second processus : l'API écrit donc
# elle-même son numéro de processus dans .agent_tag_api.pid (utilisé par arreter.ps1).
$api = Start-Process -FilePath $PythonVenv -ArgumentList @('-m', 'agent_tag.api', '--hote', '127.0.0.1', '--port', "$Port", '--fichier-pid', '.agent_tag_api.pid') -NoNewWindow -PassThru
try {
    $pret = $false
    for ($i = 0; $i -lt 30 -and -not $api.HasExited; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$Port/api/etat" | Out-Null; $pret = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $pret) { Stop-Erreur "l'API n'a pas démarré (voir les messages ci-dessus)." }
    Write-Ok "Interface : http://127.0.0.1:$Port/"
    if (-not $SansNavigateur) { Start-Process "http://127.0.0.1:$Port/" }
    Wait-Process -Id $api.Id
} finally {
    Stop-ApiEnregistree | Out-Null
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -ErrorAction SilentlyContinue }
    Write-Host 'Agent TAG arrêté.'
}
