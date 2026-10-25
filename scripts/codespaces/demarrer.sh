#!/usr/bin/env bash
# Démarre l'API et l'interface sur 127.0.0.1:8000 (port transféré par Codespaces, privé par défaut).
#   bash scripts/codespaces/demarrer.sh                 au premier plan (Ctrl+C pour arrêter)
#   bash scripts/codespaces/demarrer.sh --arriere-plan  en arrière-plan (journal : .agent_tag_api.log)
source "$(dirname "$0")/commun.sh"

if [ -f "$FICHIER_PID" ] && kill -0 "$(cat "$FICHIER_PID")" 2>/dev/null; then
  echo "Agent TAG tourne déjà (processus $(cat "$FICHIER_PID")). Arrêt : bash scripts/codespaces/arreter.sh"
  exit 0
fi
[ -x "$PY" ] && [ -f .env ] || { echo "ERREUR : lancez d'abord bash scripts/codespaces/installer.sh"; exit 1; }
export AGENT_TAG_DATABASE_URL="$(url_demo)"
"$PY" -m agent_tag.cli verifier >/dev/null || {
  echo "ERREUR : base $BASE_DEMO absente ou refusée. Recréez-la : bash scripts/codespaces/reinitialiser-demo.sh"; exit 1; }

COMMANDE=("$PY" -m agent_tag.api --hote 127.0.0.1 --port "$PORT_API" --fichier-pid "$FICHIER_PID")
if [ "${1:-}" = "--arriere-plan" ]; then
  setsid nohup "${COMMANDE[@]}" >"$JOURNAL" 2>&1 < /dev/null &
  for i in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$PORT_API/api/etat" >/dev/null 2>&1 && break
    sleep 1
  done
  if curl -sf "http://127.0.0.1:$PORT_API/api/etat" >/dev/null 2>&1; then
    echo "Agent TAG démarré : onglet PORTS, port $PORT_API (« Agent TAG (interface) »)."
  else
    echo "ERREUR : Agent TAG n'a pas démarré. Journal : $JOURNAL"; tail -20 "$JOURNAL"; exit 1
  fi
else
  echo "Agent TAG sur le port $PORT_API (onglet PORTS du Codespace). Ctrl+C pour arrêter."
  exec "${COMMANDE[@]}"
fi
