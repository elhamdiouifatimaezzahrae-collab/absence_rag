<#
.SYNOPSIS
  (Re)crée la base de DÉMONSTRATION agent_tag_demo : données FICTIVES du classeur de référence,
  environnement TEST, paramètres PROVISOIRES non validés. Toute démonstration précédente est effacée.
#>
param([string]$Base = 'agent_tag_demo', [ValidateSet('A', 'B')][string]$Profil = 'A')
. "$PSScriptRoot\commun.ps1"
Test-PythonVenv

if ((Get-ValeurEnv 'AGENT_TAG_USAGE') -ne 'TEST') { Stop-Erreur 'la démonstration ne s''installe qu''avec AGENT_TAG_USAGE=TEST.' }
Write-Etape "Création de la base de démonstration $Base (profil provisoire $Profil)"
Invoke-Natif $PythonVenv @('-m', 'agent_tag.cli', 'initialiser-demo', '--base', $Base, '--profil', $Profil) 'initialisation de la démonstration impossible'

Write-Host ''
Write-Attention 'Utilisateurs de DÉMONSTRATION : demo.responsable (décide) et demo.lecteur (consulte).'
Write-Attention 'Ce ne sont pas des comptes : aucun mot de passe, simple sélecteur dans la page. Rien n''est utilisable en production.'
Write-Host ''
Write-Host 'Démarrage : .\scripts\windows\demarrer.ps1' -ForegroundColor Green
