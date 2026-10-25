#!/usr/bin/env bash
# Efface et recrée la base de démonstration (données fictives du 12/10/2026), puis redémarre l'API.
source "$(dirname "$0")/commun.sh"
bash "$RACINE/scripts/codespaces/arreter.sh"
"$PY" -m agent_tag.cli initialiser-demo --base "$BASE_DEMO"
bash "$RACINE/scripts/codespaces/demarrer.sh" --arriere-plan
