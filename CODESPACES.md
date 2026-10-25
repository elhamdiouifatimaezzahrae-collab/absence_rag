# Agent TAG dans GitHub Codespaces (démonstration TEST)

> **Démonstration uniquement.** Le Codespace contient :
> - les données **fictives** du classeur de référence ;
> - des paramètres d'allocation **provisoires non validés** ;
> - des utilisateurs de démonstration **sans mot de passe** ;
> - des mots de passe PostgreSQL de TEST, publics et présents dans ce dépôt.
>
> Rien n'est utilisable pour de vrais remplacements. Voir `docs/decisions_a_trancher.md`.
>
> **État de vérification (25/10/2026).** La configuration n'a **pas encore été démarrée dans un
> vrai Codespace** : l'environnement de préparation n'avait ni moteur Docker ni accès aux
> registres d'images. Ce qui a été vérifié :
> - la syntaxe de `devcontainer.json` ;
> - le fichier compose, validé par `docker compose config` ;
> - le cycle complet des scripts, rejoué hors conteneur sur une copie vierge avec un
>   PostgreSQL 16 neuf : installation, démonstration, démarrage, parcours navigateur complet,
>   réimport simulé, réinitialisation, arrêt, puis 308 tests réussis.

## Ce que fait le Codespace

| Élément | Détail |
|---|---|
| Conteneur `app` | Python 3.13 (image officielle devcontainers), dépôt monté dans `/workspaces/agent-rag` |
| Conteneur `db` | PostgreSQL 16. **Aucun port publié** : joignable seulement depuis le Codespace (`localhost:5432`). Rôles et base de TEST créés au premier démarrage par `docker/init/01_roles_et_base.sql` |
| À la création (`postCreateCommand`) | `scripts/codespaces/installer.sh` : environnement `.venv`, dépendances figées (`requirements-dev.lock`), `.env` créé depuis `.env.example`, migrations, base de démonstration `agent_tag_demo` |
| À chaque démarrage (`postStartCommand`) | `scripts/codespaces/demarrer.sh --arriere-plan` : l'application écoute sur `127.0.0.1:8000` |
| Port 8000 | Transféré par Codespaces, **privé** par défaut : accessible seulement par vous, connecté(e) à GitHub. Le navigateur s'ouvre automatiquement |

## Ouvrir l'application

1. Sur la page du dépôt : **Code → Codespaces → Create codespace on main**. La première création
   prend environ 5 à 10 minutes (téléchargement des images, installation).
2. À la fin, un onglet du navigateur s'ouvre sur l'application. Sinon, ouvrez l'onglet **PORTS** en
   bas de l'éditeur, puis cliquez sur l'icône globe de la ligne « Agent TAG (interface) » (port 8000).
3. Si l'adresse est refusée ou vide, l'application n'est pas démarrée : dans le **Terminal**, lancez
   `bash scripts/codespaces/demarrer.sh`.

**Ne passez pas le port en « Public »**, ni le 8000 ni le 5432. L'application n'a pas
d'authentification.

## Commandes (Terminal du Codespace)

| Action | Commande |
|---|---|
| Installer / réinstaller (dépendances, `.env`, migrations, démonstration) | `bash scripts/codespaces/installer.sh` |
| Démarrer au premier plan (Ctrl+C pour arrêter) | `bash scripts/codespaces/demarrer.sh` |
| Démarrer en arrière-plan | `bash scripts/codespaces/demarrer.sh --arriere-plan` (journal : `.agent_tag_api.log`) |
| Arrêter | `bash scripts/codespaces/arreter.sh` |
| Repartir d'une démonstration vierge | `bash scripts/codespaces/reinitialiser-demo.sh` |
| Simuler un réimport (ex. O130 absent) | `bash scripts/codespaces/simuler-reimport.sh O130`, puis recharger la page |
| Lancer les tests (308 attendus) | `bash scripts/codespaces/tests.sh` |
| Appliquer les migrations seulement | `.venv/bin/python -m agent_tag.cli migrer` |

Le Codespace s'arrête de lui-même après 30 minutes d'inactivité (réglage GitHub par défaut). Les
données de démonstration sont conservées tant que le Codespace n'est pas supprimé.

## Parcours de démonstration

1. « Agir en tant que » : **Responsable de démonstration**. Le lecteur peut consulter et lancer un
   calcul, mais pas décider.
2. Date **12/10/2026**, chaîne **L1**, puis **Lancer le calcul des remplacements**.
3. Sur un besoin, vous pouvez :
   - confirmer la proposition ;
   - la refuser (motif obligatoire) ;
   - **choisir ce candidat** sur un autre candidat admissible (motif obligatoire) ;
   - laisser le besoin non pourvu, puis le rouvrir.
4. Consultez les panneaux **Ouvriers réservés et engagés**, **Données importées** et **Historique**.
5. Simulez un réimport (`simuler-reimport.sh O130`), puis rechargez la page : le bandeau rouge et le
   statut « à revoir » apparaissent.

## Variables d'environnement

`.env` est créé automatiquement à partir de `.env.example`. Il n'est pas versionné.

| Variable | Valeur dans le Codespace |
|---|---|
| `AGENT_TAG_USAGE` | `TEST` |
| `AGENT_TAG_DATABASE_URL` | `postgresql://agent_tag_app:app_test@localhost:5432/agent_tag_test` ; les scripts remplacent la base par `agent_tag_demo` |
| `AGENT_TAG_OWNER_URL` | `postgresql://agent_tag_owner:owner_test@localhost:5432/agent_tag_test` (migrations et tests) |
| `AGENT_TAG_ARCHIVES` | `archives` (copies des fichiers importés, non versionnées) |

Aucun secret réel n'est nécessaire, et aucun ne doit être ajouté au dépôt.

## En cas de problème

| Symptôme | Action |
|---|---|
| La création s'arrête sur une erreur dans « postCreateCommand » | Terminal : `bash scripts/codespaces/installer.sh` et lire le message |
| Port 8000 absent ou page vide | `bash scripts/codespaces/demarrer.sh`, puis voir `.agent_tag_api.log` |
| « base agent_tag_demo absente » | `bash scripts/codespaces/reinitialiser-demo.sh` |
| PostgreSQL injoignable | Menu de commandes (F1) → « Codespaces: Rebuild Container » |
| Erreur 401/404 sur l'adresse du port | Ouvrez le lien depuis l'onglet PORTS, dans le navigateur où vous êtes connecté(e) à GitHub |
