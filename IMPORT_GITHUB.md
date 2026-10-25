# Importer Agent TAG dans le dépôt privé `agent-rag`

Dépôt cible : https://github.com/elhamdiouifatimaezzahrae-collab/agent-rag (privé).

Toute l'opération se fait **dans le navigateur**, avec votre propre session GitHub. Aucun mot de
passe ni jeton n'est à saisir ou à transmettre. Le projet est déposé sur une **branche séparée**
(`import-agent-tag`) : la branche `main` et son historique ne sont pas modifiés avant que vous
validiez la fusion.

Durée : environ 15 minutes, plus 5 à 10 minutes pour la première création du Codespace de l'application.

---

## Étape 1 — Vérifier l'archive (sur votre PC)

Fichier : `agent-tag-codespaces.zip`. Il contient un dossier `agent-tag/` : le code, les
migrations, les tests, la documentation, le classeur fictif de référence, ainsi que
`.devcontainer/` et `scripts/`.

Vous pouvez contrôler l'empreinte SHA-256, indiquée dans le message de livraison. Dans PowerShell :

```powershell
Get-FileHash .\agent-tag-codespaces.zip -Algorithm SHA256
```

L'archive ne contient ni `.env`, ni `.venv`, ni fichiers importés, ni caches.

## Étape 2 — Ouvrir un Codespace temporaire sur votre dépôt

1. Ouvrez la page du dépôt `agent-rag`.
2. **Si le dépôt est vide** (page « Quick setup », sans bouton Codespaces) : cliquez sur
   **creating a new file**, nommez-le `LISEZMOI-import.txt`, écrivez une ligne, puis
   **Commit changes**. Le dépôt a ainsi une branche `main` sur laquelle ouvrir un Codespace.
3. **Code → Codespaces → Create codespace on main**. L'éditeur s'ouvre dans le navigateur.

## Étape 3 — Déposer l'archive

Faites glisser `agent-tag-codespaces.zip` depuis votre PC dans le panneau **Explorer** (à gauche),
à la racine du dépôt.

## Étape 4 — Importer (Terminal du Codespace)

Ouvrez le terminal (menu ☰ → Terminal → New Terminal), puis copiez ces commandes une par une :

```bash
mv agent-tag-codespaces.zip /tmp/              # l'archive ne doit pas être versionnée
unzip -q /tmp/agent-tag-codespaces.zip -d /tmp/import
git status && git log --oneline -5             # état actuel du dépôt, à regarder
bash /tmp/import/agent-tag/scripts/importer-dans-depot.sh
```

Le script :
- **refuse** de travailler si le dépôt contient des modifications non enregistrées ;
- **liste les fichiers déjà présents** dans le dépôt, puis **s'arrête sans rien modifier**. Par
  exemple, un `README.md` créé avec le dépôt entre en conflit avec celui d'Agent TAG ;
- sinon, crée la branche `import-agent-tag` et y enregistre un commit contenant tout le projet.

**Si des fichiers sont listés** : décidez s'ils peuvent être remplacés. L'ancienne version reste
dans l'historique git de `main`. Si oui :

```bash
bash /tmp/import/agent-tag/scripts/importer-dans-depot.sh --remplacer
```

Sinon, renommez-les d'abord (exemple : `git mv README.md README_origine.md && git commit -m "Renomme le README d'origine"`), puis relancez la première commande.

Vérifiez le commit, puis publiez la branche. C'est la seule commande qui écrit sur GitHub :

```bash
git show --stat HEAD | head -40
git push -u origin import-agent-tag
```

## Étape 5 — Fusionner dans `main`

Sur la page du dépôt :
1. Cliquez sur **Compare & pull request**, ou ouvrez l'onglet **Pull requests → New** et choisissez
   `import-agent-tag` → `main`.
2. Relisez la liste des fichiers.
3. Cliquez sur **Create pull request**, puis sur **Merge pull request**.

Rien n'est écrasé : la fusion ajoute un commit par-dessus l'historique existant.

## Étape 6 — Supprimer le Codespace temporaire

Allez sur https://github.com/codespaces, puis menu « … » du Codespace temporaire → **Delete**.
Il a été créé sans la configuration Agent TAG et ne sert plus.

## Étape 7 — Lancer Agent TAG

Retournez sur le dépôt, puis **Code → Codespaces → Create codespace on main**. Le Codespace est
construit avec `.devcontainer/` : Python, PostgreSQL 16 et la base de démonstration. L'application
s'ouvre ensuite sur le port 8000, en mode **privé**. Pour la suite, voir `CODESPACES.md`.

---

## Ce qui reste sous votre contrôle

- La seule écriture sur GitHub est `git push` (étape 4), suivie de la fusion (étape 5) que vous
  validez vous-même.
- Le dépôt reste privé. Ne passez pas le port 8000 en « Public » : l'application n'a pas
  d'authentification.
- Le quota gratuit de Codespaces est limité (heures et stockage mensuels). Arrêtez ou supprimez
  les Codespaces inutilisés.
