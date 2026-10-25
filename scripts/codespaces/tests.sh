#!/usr/bin/env bash
# Suite de tests complète. Les tests créent et suppriment leurs propres bases agent_tag_pytest_*.
source "$(dirname "$0")/commun.sh"
exec "$PY" -m pytest -q "$@"
