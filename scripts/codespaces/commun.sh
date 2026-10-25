# Variables communes aux scripts Codespaces (chargé par « source »).
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RACINE"
PY="$RACINE/.venv/bin/python"
PORT_PG="${AGENT_TAG_PG_PORT:-5432}"          # PostgreSQL du conteneur « db »
PORT_API="${AGENT_TAG_PORT:-8000}"
BASE_DEMO="${AGENT_TAG_BASE_DEMO:-agent_tag_demo}"
FICHIER_PID="$RACINE/.agent_tag_api.pid"
JOURNAL="$RACINE/.agent_tag_api.log"
export PYTHONUTF8=1

url_demo() {
  # URL applicative de .env, avec la base de démonstration
  local url
  url="$(grep -E '^AGENT_TAG_DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
  echo "${url%/*}/$BASE_DEMO"
}
