<#
.SYNOPSIS
  Arrête Agent TAG lancé par demarrer.ps1 (si la fenêtre est encore ouverte, Ctrl+C suffit).
.PARAMETER Postgres
  Docker : arrête aussi le conteneur PostgreSQL (les données sont conservées dans le volume).
  Le service PostgreSQL d'une installation locale n'est pas arrêté par ce script (droits
  administrateur) : Stop-Service postgresql-x64-16 dans un PowerShell administrateur.
#>
param([ValidateSet('Aucun', 'Docker')][string]$Postgres = 'Aucun')
. "$PSScriptRoot\commun.ps1"

if (Stop-ApiEnregistree) { Write-Ok 'Agent TAG arrêté' }
else { Write-Attention 'aucune instance d''Agent TAG lancée par demarrer.ps1 ne tourne.' }
if ($Postgres -eq 'Docker') {
    Invoke-Natif docker @('compose', 'stop') 'arrêt du conteneur impossible'
    Write-Ok 'conteneur PostgreSQL arrêté (données conservées)'
}
