#!/usr/bin/env bash
# Exécuté automatiquement à la création du Codespace (postCreateCommand).
# Installe les dépendances figées, crée .env (valeurs de TEST), applique les migrations et
# (re)crée la base de démonstration agent_tag_demo. Relançable sans risque.
source "$(dirname "$0")/commun.sh"

echo "==> Environnement Python (.venv)"
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -q --disable-pip-version-check -r requirements-dev.lock
"$PY" -m pip install -q --disable-pip-version-check --no-deps -e .

echo "==> Fichier .env"
if [ -f .env ]; then
  echo "    .env existe déjà : conservé"
else
  sed "s#@localhost:5433/#@localhost:${PORT_PG}/#" .env.example > .env
  echo "    .env créé depuis .env.example (usage TEST, PostgreSQL sur localhost:${PORT_PG})"
fi

echo "==> Attente de PostgreSQL"
for i in $(seq 1 60); do
  if "$PY" -c "import psycopg; from agent_tag.config import settings; psycopg.connect(settings.charger().owner_url, connect_timeout=3).close()" 2>/dev/null; then
    ok=1; break
  fi
  sleep 2
done
[ "${ok:-}" = 1 ] || { echo "ERREUR : PostgreSQL injoignable sur localhost:${PORT_PG}"; exit 1; }

echo "==> Migrations de la base de TEST"
"$PY" -m agent_tag.cli migrer
echo "==> Base de démonstration"
"$PY" -m agent_tag.cli initialiser-demo --base "$BASE_DEMO"

cat <<FIN

Installation terminée.
  Démarrer   : bash scripts/codespaces/demarrer.sh   (automatique à chaque démarrage du Codespace)
  Arrêter    : bash scripts/codespaces/arreter.sh
  Tests      : bash scripts/codespaces/tests.sh
Données FICTIVES, paramètres PROVISOIRES non validés, utilisateurs de démonstration sans mot de passe.
FIN
