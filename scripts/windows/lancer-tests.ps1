<#
.SYNOPSIS
  Lance la suite de tests (nécessite installer.ps1 -AvecTests et PostgreSQL préparé).
  Les tests créent puis suppriment des bases jetables agent_tag_pytest_* ; ils ne touchent ni
  agent_tag_test ni agent_tag_demo.
#>
. "$PSScriptRoot\commun.ps1"
Test-PythonVenv
Invoke-Silencieux $PythonVenv @('-c', 'import pytest') | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Erreur 'pytest absent : relancez installer.ps1 -AvecTests' }
& $PythonVenv -m pytest -q @args
exit $LASTEXITCODE
