#!/usr/bin/env bash
# DÉMONSTRATION TEST : réimporte le 12/10/2026 avec l'ouvrier indiqué absent (ex. O130).
# Le classeur de référence n'est pas modifié (copie dans archives/simulations).
source "$(dirname "$0")/commun.sh"
[ -n "${1:-}" ] || { echo "usage : bash scripts/codespaces/simuler-reimport.sh ID_OUVRIER"; exit 2; }
AGENT_TAG_DATABASE_URL="$(url_demo)" "$PY" -m agent_tag.cli simuler-reimport --ouvrier "$1"
