#!/usr/bin/env bash
# Copie le projet Agent TAG (dossier extrait de l'archive) dans le dépôt git COURANT, sur une
# nouvelle branche, et prépare un commit. Ne pousse rien : la commande git push est affichée.
#
#   cd /workspaces/agent-rag                       # racine de VOTRE dépôt
#   bash /tmp/import/agent-tag/scripts/importer-dans-depot.sh [--remplacer] [--branche NOM]
#
# Sécurités : refuse si le dépôt a des modifications non commitées ; liste les fichiers qui
# existent déjà et s'arrête, sauf --remplacer (les versions précédentes restent dans l'historique
# git) ; ne modifie jamais la branche courante (travail sur une branche séparée).
set -euo pipefail
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCHE="import-agent-tag"; REMPLACER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --remplacer) REMPLACER=1 ;;
    --branche) BRANCHE="$2"; shift ;;
    *) echo "option inconnue : $1"; exit 2 ;;
  esac; shift
done

CIBLE="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "ERREUR : lancez ce script depuis la racine de votre dépôt git."; exit 2; }
[ "$CIBLE" != "$SOURCE" ] || { echo "ERREUR : la source et le dépôt cible sont le même dossier."; exit 2; }
cd "$CIBLE"
[ -z "$(git status --porcelain)" ] || { echo "ERREUR : le dépôt a des modifications non commitées :"; git status --short; exit 2; }
if git show-ref --verify --quiet "refs/heads/$BRANCHE"; then echo "ERREUR : la branche $BRANCHE existe déjà."; exit 2; fi

mapfile -d '' FICHIERS < <(cd "$SOURCE" && find . -type f -print0)
CONFLITS=()
for f in "${FICHIERS[@]}"; do [ -e "$CIBLE/${f#./}" ] && CONFLITS+=("${f#./}"); done
if [ ${#CONFLITS[@]} -gt 0 ]; then
  echo "Fichiers déjà présents dans le dépôt (${#CONFLITS[@]}) :"; printf '  %s\n' "${CONFLITS[@]}"
  if [ $REMPLACER -eq 0 ]; then
    echo "Rien n'a été modifié. Relancez avec --remplacer pour les remplacer (anciennes versions conservées dans l'historique git)."
    exit 3
  fi
fi

echo "Dépôt : $CIBLE ($(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'sans commit'))"
git checkout -q -b "$BRANCHE"
(cd "$SOURCE" && tar -cf - .) | tar -xf - -C "$CIBLE"
(cd "$CIBLE" && printf '%s\0' "${FICHIERS[@]}" | xargs -0 git add --)
git commit -q -m "Import du projet Agent TAG (incrément 5) et configuration Codespaces"
echo "Commit créé sur la branche $BRANCHE : $(git rev-parse --short HEAD), ${#FICHIERS[@]} fichiers."
echo "Vérifiez avec : git show --stat HEAD | head -40"
echo "Puis publiez la branche (rien n'a été poussé) : git push -u origin $BRANCHE"
