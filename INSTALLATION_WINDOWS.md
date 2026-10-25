# Installer et démarrer Agent TAG sous Windows (démonstration TEST)

> **À lire d'abord.** Cette procédure installe une **démonstration** : données fictives du
> classeur de référence, paramètres d'allocation **provisoires non validés**, utilisateurs de
> démonstration **sans mot de passe**. Les mots de passe PostgreSQL utilisés (`owner_test`,
> `app_test`, `pg_admin_test`) sont publiés dans ce dossier : ils ne protègent rien et ne doivent
> jamais servir en production. L'application n'est pas prête pour un usage réel
> (voir `docs/decisions_a_trancher.md`).
>
> **État de vérification.** Ces scripts ont été écrits pour Windows PowerShell 5.1 et
> PowerShell 7. Leur syntaxe a été analysée et leurs fonctions communes exécutées avec
> PowerShell 7 **sous Linux**. **Ils n'ont pas encore été exécutés sous Windows** : signalez-moi
> tout message d'erreur, en le copiant tel quel.

Durée : 15 à 30 minutes. Toutes les commandes se tapent dans **PowerShell** (menu Démarrer →
« PowerShell »), sans droits administrateur, sauf mention contraire.

---

## Étape 0 — Prérequis

| Logiciel | Version | Où le trouver |
|---|---|---|
| Python | 3.11, 3.12 ou 3.13, **64 bits** | https://www.python.org/downloads/windows/ — cocher **« Add python.exe to PATH »** |
| PostgreSQL | **16** (seule version testée) | Au choix : **Docker Desktop** (option A) ou l'installateur Windows https://www.postgresql.org/download/windows/ (option B) |
| Navigateur | Edge, Chrome ou Firefox récents | — |

Vérifiez Python :

```powershell
py -3 --version        # ou : python --version
```

Si PowerShell refuse d'exécuter les scripts (« l'exécution de scripts est désactivée »),
autorisez-les **pour cette fenêtre seulement** :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

À refaire à chaque nouvelle fenêtre PowerShell (rien n'est modifié durablement).

## Étape 1 — Extraire l'archive

Extrayez `agent-tag-increment5.zip` dans un dossier **local**, de préférence sans espace et hors
OneDrive, par exemple `C:\agent-tag`. Puis :

```powershell
cd C:\agent-tag
Get-ChildItem -Recurse -Filter *.ps1 | Unblock-File    # fichiers téléchargés : lever le blocage Windows
```

## Étape 2 — PostgreSQL

**Option A — Docker Desktop** (port 5433, rien d'autre à installer) : démarrez Docker Desktop, puis

```powershell
.\scripts\windows\preparer-postgres.ps1 -Mode Docker
```

**Option B — PostgreSQL installé sur le poste** (port 5432 en général). Le mot de passe du compte
`postgres`, choisi pendant l'installation de PostgreSQL, vous sera demandé une fois :

```powershell
.\scripts\windows\preparer-postgres.ps1 -Mode Local -Port 5432
```

Les deux options créent les rôles `agent_tag_owner` et `agent_tag_app`, ainsi que la base
`agent_tag_test` (script `docker\init\01_roles_et_base.sql`).

## Étape 3 — Installer Agent TAG

Utilisez le même port qu'à l'étape 2 : **5433** pour Docker, **5432** pour une installation locale.

```powershell
.\scripts\windows\installer.ps1 -PortPostgres 5433
# ajoutez -AvecTests pour pouvoir lancer la suite de tests (étape 6)
```

Le script :
- vérifie Python ;
- crée l'environnement virtuel `.venv` ;
- installe les versions figées de `requirements.lock` ;
- crée `.env` (usage TEST) ;
- vérifie le classeur de référence et la connexion à PostgreSQL.

Si `.env` existe déjà, il n'est pas modifié.

## Étape 4 — Créer la base de démonstration

```powershell
.\scripts\windows\initialiser-demo.ps1
```

Le script crée (ou **recrée**, en effaçant la démonstration précédente) la base `agent_tag_demo` :
- import du référentiel et des données du 12/10/2026, avec les absences attestées ;
- installation du profil **provisoire** A.

Relancez-le pour repartir de zéro.

## Étape 5 — Démarrer, utiliser, arrêter

```powershell
.\scripts\windows\demarrer.ps1
```

- Le navigateur s'ouvre sur **http://127.0.0.1:8000/**. Sinon, ouvrez cette adresse vous-même.
- L'application n'est accessible que depuis ce PC : elle refuse toute autre adresse d'écoute.
- **Arrêter** : `Ctrl+C` dans la fenêtre PowerShell. Si la fenêtre a été fermée :

  ```powershell
  .\scripts\windows\arreter.ps1                    # arrête Agent TAG
  .\scripts\windows\arreter.ps1 -Postgres Docker   # et le conteneur PostgreSQL (données conservées)
  ```

  Avec l'option B, le service PostgreSQL reste démarré. Pour l'arrêter, ouvrez PowerShell en
  administrateur et lancez `Stop-Service postgresql-x64-16`.
- **Port déjà utilisé** : `.\scripts\windows\demarrer.ps1 -Port 8001`.

### Parcours de démonstration conseillé

1. En haut, « Agir en tant que » : choisissez **Responsable de démonstration**. Le lecteur peut
   consulter et lancer un calcul, mais pas décider.
2. Choisissez la date **12/10/2026**, la chaîne **L1**, puis cliquez sur **Lancer le calcul des remplacements**.
3. Cliquez sur un besoin. Vous pouvez alors :
   - confirmer la proposition ;
   - la refuser (motif obligatoire) ;
   - **choisir un autre candidat** de la liste (motif obligatoire) ;
   - laisser le besoin non pourvu, puis le rouvrir.
4. Consultez les panneaux **Ouvriers réservés et engagés**, **Données importées** et **Historique**.
5. Pour voir l'effet d'un réimport, simulez l'absence du remplaçant confirmé, par exemple O130,
   dans une **seconde** fenêtre PowerShell :

   ```powershell
   cd C:\agent-tag
   $env:AGENT_TAG_DATABASE_URL = 'postgresql://agent_tag_app:app_test@localhost:5433/agent_tag_demo'   # adaptez le port
   .\.venv\Scripts\python.exe -m agent_tag.cli simuler-reimport --ouvrier O130
   ```

   Rechargez ensuite la page : le bandeau rouge, le statut « à revoir » et le lot 3 apparaissent.
   Le classeur de référence n'est pas modifié : une copie est écrite dans `archives\simulations`.

## Étape 6 — (Facultatif) Lancer les tests

Nécessite `installer.ps1 -AvecTests`. Les tests créent puis suppriment leurs propres bases
`agent_tag_pytest_*` :

```powershell
.\scripts\windows\lancer-tests.ps1
```

Résultat attendu : 308 tests réussis (résultat obtenu sous Linux), en 2 à 5 minutes.

---

## En cas de problème

| Message | Cause probable | Solution |
|---|---|---|
| `Python introuvable` | Python absent, ou seul l'alias du Microsoft Store est présent | Installer Python depuis python.org avec « Add python.exe to PATH », rouvrir PowerShell |
| `connexion impossible` | PostgreSQL arrêté, mauvais port dans `.env` | Démarrer Docker Desktop / le service ; vérifier `AGENT_TAG_*_URL` dans `.env` |
| `password authentication failed` | Rôles non créés | Refaire l'étape 2 |
| `contrôle de démarrage refusé` | Base de démonstration absente | Refaire l'étape 4 |
| `le port 8000 est déjà utilisé` | Agent TAG déjà lancé | `arreter.ps1`, ou `demarrer.ps1 -Port 8001` |
| Caractères accentués illisibles dans la console | Police ou page de codes de la console | Sans effet sur les données ; utiliser Windows Terminal |
| Police différente dans la page | Pas d'accès à Google Fonts | Sans effet : police système de repli |

## Ce que font les scripts (pour relecture)

| Script | Action |
|---|---|
| `scripts\windows\commun.ps1` | Fonctions partagées. Se place à la racine du projet et force l'UTF-8 pour Python |
| `installer.ps1` | Vérifie Python ; crée `.venv` ; installe les dépendances en `pip install -r requirements.lock` puis `pip install --no-deps -e .` ; crée `.env` ; vérifie la connexion |
| `preparer-postgres.ps1` | Docker : `docker compose up -d`, puis attente que le conteneur soit prêt. Local : `psql -f docker\init\01_roles_et_base.sql`, si les rôles n'existent pas encore |
| `initialiser-demo.ps1` | `python -m agent_tag.cli initialiser-demo` |
| `demarrer.ps1` | Contrôle de démarrage ; `python -m agent_tag.api --hote 127.0.0.1` ; ouverture du navigateur |
| `arreter.ps1` | Arrête le processus enregistré dans `.agent_tag_api.pid` ; `docker compose stop` en option |
| `lancer-tests.ps1` | `python -m pytest -q` |

Commandes manuelles équivalentes (sans les scripts), depuis `C:\agent-tag` :

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env        # puis ajuster le port si PostgreSQL est sur 5432
.\.venv\Scripts\python.exe -m agent_tag.cli initialiser-demo
$env:AGENT_TAG_DATABASE_URL = 'postgresql://agent_tag_app:app_test@localhost:5433/agent_tag_demo'
.\.venv\Scripts\python.exe -m agent_tag.api --hote 127.0.0.1 --port 8000
```
