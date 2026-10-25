#!/usr/bin/env bash
# Arrête Agent TAG lancé par demarrer.sh. PostgreSQL s'arrête avec le Codespace.
source "$(dirname "$0")/commun.sh"
if [ -f "$FICHIER_PID" ] && kill "$(cat "$FICHIER_PID")" 2>/dev/null; then
  for i in $(seq 1 10); do kill -0 "$(cat "$FICHIER_PID" 2>/dev/null || echo 0)" 2>/dev/null || break; sleep 0.5; done
  rm -f "$FICHIER_PID"; echo "Agent TAG arrêté."
else
  rm -f "$FICHIER_PID"; echo "Agent TAG ne tournait pas."
fi
