# Agent TAG

État : **incrément 5** — socle (0), référentiels (1), données journalières et disponibilité (2),
moteur d'allocation (3), calculs persistés, décisions, réservations, API et interface web (4),
choix d'un autre candidat, réouverture, vues des réservations et des réimports, installation
Windows (5).

**Dans le navigateur, sans rien installer : GitHub Codespaces, voir `CODESPACES.md`**
(import dans le dépôt : `IMPORT_GITHUB.md`).
**Installation sous Windows : suivre `INSTALLATION_WINDOWS.md`** (scripts `scripts\windows\*.ps1`).
Décisions métier à trancher avant tout usage réel : `docs/decisions_a_trancher.md`.

> **Application en environnement TEST uniquement.** P1, P2, P3 (D3), l'ordre des priorités (D4),
> les rôles autorisés (D14) et les autres décisions listées dans `docs/registre_decisions.md`
> ne sont pas validés. Les calculs utilisent un profil **provisoire** et chaque décision est
> enregistrée comme « TEST, non valable en réel ». Hors TEST, la base refuse d'activer une
> configuration non validée : aucun calcul ni aucune décision ne sont alors possibles.

## Démarrage rapide (démonstration TEST)

```powershell
python -m agent_tag.cli migrer
python -m agent_tag.cli initialiser-demo
$env:AGENT_TAG_DATABASE_URL = "postgresql://agent_tag_app:app_test@localhost:5433/agent_tag_demo"
python -m agent_tag.api --port 8000      # n'écoute que sur 127.0.0.1 (aucune authentification)
```

Ouvrir ensuite **http://127.0.0.1:8000/** dans le navigateur. Choisir l'utilisateur
« Responsable de démonstration » pour pouvoir confirmer ou refuser ; « Lecteur de
démonstration » permet de consulter et de lancer un calcul, pas de décider.
`initialiser-demo` recrée entièrement la base `agent_tag_demo` (données fictives du classeur de
référence, 12/10/2026). Arrêter l'API avec Ctrl+C. Les utilisateurs `demo.*` ne sont pas des comptes : il n'y a aucun
mot de passe, seulement un sélecteur. Les mots de passe PostgreSQL `*_test` sont publics et réservés au TEST.

## Contenu

```
agent-tag/
├─ migrations/
│  ├─ 0001_environnement.sql           table environment (usage immuable, ligne unique)
│  ├─ 0002_referentiel.sql             utilisateurs, lots d'import, référentiel et contraintes
│  ├─ 0003_donnees_journalieres.sql    affectations, absences, couvertures, version par date
│  └─ 0004_allocation.sql              configuration, calculs, propositions, réservations, décisions
├─ src/agent_tag/
│  ├─ config/settings.py               lecture de la configuration (.env + variables)
│  ├─ config/demarrage.py              contrôles de démarrage (schéma à jour, T94)
│  ├─ domain/disponibilite.py          règles de disponibilité (fonctions pures)
│  ├─ domain/allocation.py             moteur d'allocation et flot maximal (fonctions pures)
│  ├─ persistence/db.py                connexion PostgreSQL (psycopg 3)
│  ├─ persistence/migrations.py        exécuteur de migrations SQL versionnées
│  ├─ persistence/disponibilite.py     lecture des faits en base et calcul de disponibilité
│  ├─ persistence/instantane.py        instantané en lecture seule pour le moteur
│  ├─ imports/classeur.py              lecture du classeur (feuilles, colonnes, lignes)
│  ├─ imports/referentiel.py           contrôles du référentiel, sans écriture
│  ├─ imports/import_referentiel.py    import du référentiel (tout ou rien)
│  ├─ imports/journalier.py            contrôles des feuilles Affectations et Absences
│  ├─ imports/import_journalier.py     import journalier, couvertures, historique
│  ├─ imports/rapport.py               rapport d'import (anomalies, compteurs, couvertures)
│  ├─ services/allocation.py          opérations transactionnelles (lancer, accepter, refuser…)
│  ├─ services/configuration.py       configuration versionnée, profils provisoires
│  ├─ services/integrite.py           vérificateur d'invariants
│  ├─ services/vues.py                lectures pour l'API
│  ├─ api/app.py, api/static/         API FastAPI et interface web (HTML, CSS, JS sans framework)
│  ├─ demo.py                         jeu de démonstration TEST
│  └─ cli.py                           commandes d'administration
├─ donnees/reference/                  classeur de référence (lu, jamais modifié)
├─ tests/unit | db | integration | imports   297 tests (+ parcours navigateur dans tests/navigateur)
├─ docker/init/01_roles_et_base.sql    rôles et base de TEST
├─ docker-compose.yml                  option Docker Desktop
└─ docs/registre_decisions.md, docs/tracabilite.md
```

## Prérequis

- Python 3.11 ou plus (vérifié avec 3.13)
- PostgreSQL 16 (vérifié avec 16.15), via **une** des deux options ci-dessous

## Reproduction sous Windows (PowerShell)

### 1. Vérifier les prérequis

```powershell
py --version
psql --version          # option A seulement
docker --version        # option B seulement
```

### 2. PostgreSQL de TEST — option A : installation locale

1. Installer PostgreSQL 16 avec l'installateur officiel (postgresql.org → Download → Windows).
   Retenir le mot de passe du compte `postgres` et le port (5432 par défaut).
2. Créer les rôles et la base :

```powershell
psql -h localhost -p 5432 -U postgres -f docker\init\01_roles_et_base.sql
```

3. Dans le fichier `.env` (étape 4), remplacer le port `5433` par `5432`.

### 2. PostgreSQL de TEST — option B : Docker Desktop

```powershell
docker compose up -d
docker compose ps        # attendre l'état "healthy"
```

Le script `docker/init/01_roles_et_base.sql` est exécuté automatiquement au premier démarrage.
Le port exposé est 5433.

### 3. Environnement Python

```powershell
cd agent-tag
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.lock   # versions figées
python -m pip install --no-deps -e .
```

Si PowerShell refuse l'activation : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 4. Configuration

```powershell
Copy-Item .env.example .env
```

Adapter le port dans `.env` si nécessaire. `AGENT_TAG_USAGE=TEST` est obligatoire.

### 5. Initialiser la base de TEST

```powershell
python -m agent_tag.cli verifier                              # attendu : refus (migrations en attente)
python -m agent_tag.cli migrer                                # attendu : 0001 puis 0002 appliquées
python -m agent_tag.cli init-env --libelle "Agent TAG - TEST local"
python -m agent_tag.cli verifier                              # attendu : OK — ... usage TEST
```

Contrôle du refus T94 :

```powershell
$env:AGENT_TAG_USAGE = "EXPLOITATION"; python -m agent_tag.cli verifier   # attendu : ERREUR
Remove-Item Env:AGENT_TAG_USAGE
```

Le fuseau horaire n'est pas renseigné : c'est une décision ouverte (voir le registre).
Il pourra être fixé plus tard avec `--fuseau` à l'initialisation, ou par une mise à jour du libellé et du fuseau.

### 6. Importer le référentiel (incrément 1)

```powershell
python -m agent_tag.cli creer-utilisateur --identifiant responsable.test --nom "Responsable de test" --role TEST_TOUS_DROITS
python -m agent_tag.cli importer-referentiel donnees\reference\Base_Allocation_Production_150_Ouvriers_v2.xlsx --auteur responsable.test --rapport-json rapport_import.json
python -m agent_tag.cli importer-referentiel donnees\reference\Base_Allocation_Production_150_Ouvriers_v2.xlsx --auteur responsable.test
```

Résultats attendus :
- premier import : `Statut : APPLIQUE (lot 1)` ; 150 ouvriers, 487 compétences détenues,
  5 chaînes, 31 exigences ; 0 anomalie bloquante, 10 décisions humaines, 7 informations ;
- second import du même fichier : `Statut : DEJA_IMPORTE (lot 1)`, rien n'est écrit ;
- un autre fichier de référentiel est rejeté (D15 : import unique en V1) ;
- code de sortie : 0 si appliqué ou déjà importé, 2 si rejeté.

Règles de l'import :
- **tout ou rien** : une seule anomalie bloquante rejette l'import entier ; le rejet est tracé
  (lot `REJETE` avec son rapport) et aucune donnée du référentiel n'est écrite ;
- gravités : `BLOQUANTE` (rejet), `DECISION` (importé, décision humaine attendue — ex. exigences
  absentes, correspondance Coupeur → Coupe déduite), `AVERTISSEMENT`, `INFORMATION` ;
- aucune valeur manquante n'est complétée ; l'identité d'un ouvrier est son `ID_Ouvrier` ;
- le fichier source est archivé intact dans `archives/<empreinte SHA-256>.xlsx`.

Si le serveur PostgreSQL a été arrêté (redémarrage du poste), le relancer avant ces commandes.

### 7. Importer les données journalières et consulter la disponibilité (incrément 2)

```powershell
python -m agent_tag.cli migrer        # applique 0003_donnees_journalieres
python -m agent_tag.cli importer-journalier donnees\reference\Base_Allocation_Production_150_Ouvriers_v2.xlsx --auteur responsable.test --attester-absences --rapport-json rapport_journalier.json
python -m agent_tag.cli disponibilite --date 2026-10-12 --chaine L1
python -m agent_tag.cli disponibilite --date 2026-10-12 --ouvrier O001 O011
python -m agent_tag.cli disponibilite --date 2026-10-12 --etat ABSENT --json dispo.json
python -m agent_tag.cli disponibilite --date 2026-10-12 --instant 2026-10-24T22:00:00+00:00
```

Résultats attendus sur le classeur de référence (avec `--attester-absences`) :
lot APPLIQUE, 150 affectations et 16 absences, 10 couvertures COMPLET (5 chaînes × 2 types) ;
disponibilité au 12/10/2026 : 134 DISPONIBLE, 16 ABSENT (dont O001–O010 sur L1) ;
au 13/10/2026 : 150 INCONNU (aucune donnée pour cette date ; rien n'est généré).

États de disponibilité :

| Affectation du jour | Absence certaine | Absences attestées | État | Besoin créable |
|---|---|---|---|---|
| Présent | non | oui | DISPONIBLE | non |
| Présent | non | non | INCONNU | non |
| Présent | oui | — | INDETERMINE (contradiction) | non |
| Absent | oui | — | ABSENT | **oui** |
| Absent | non | — | INDETERMINE (contradiction) | non |
| aucune | oui | — | ABSENT | non |
| aucune | non | — | INCONNU | non |

Une date suivant une absence de N > 1 jours (fenêtre de N − 1 jours) rend un ouvrier « Présent »
ou « Absent » INDETERMINE tant que D19 n'est pas tranchée. `Ouvriers.Statut` n'est jamais utilisé.

Règles de l'import journalier :
- feuilles Affectations et Absences obligatoires ; dates Excel uniquement (texte refusé) ;
- tout ou rien ; rejet tracé ; même fichier → DEJA_IMPORTE ;
- un nouveau fichier remplace la couverture courante des (date, chaîne, type) qu'il couvre :
  l'ancienne passe à REMPLACE avec sa période de validité, toutes les lignes sont conservées ;
- `--attester-absences` (choix provisoire D18) atteste que la feuille Absences est complète pour
  les (date, chaîne) couverts par les affectations du fichier ; sans attestation, aucun ouvrier
  présent n'est DISPONIBLE (état INCONNU).

### 8. Calculer des recommandations de remplaçants (incrément 3)

```powershell
python -m agent_tag.cli allouer --date 2026-10-12 --chaine L1 --profil A
python -m agent_tag.cli allouer --date 2026-10-12 --chaine L1 --profil B --detail --json allocation.json
```

- Calcul **en lecture seule** : une seule transaction `REPEATABLE READ READ ONLY` ; rien n'est
  écrit (aucun run, aucune réservation à ce stade).
- Autorisé uniquement en usage TEST, avec un profil **provisoire** (valeurs arbitraires, non validées) :

| Profil | m_bloc (P1) | m_alerte (P2) | p3 (P3) | Priorités (D4) |
|---|---|---|---|---|
| A — prudent | 1 | 2 | 2 | Moyenne 1 < Élevée 2 < Très élevée 3 |
| B — permissif | 1 | 1 | 10 | idem |

- Résultat attendu au 12/10/2026 sur L1 : profil A → 8 propositions, couverture maximale 8,
  O005 (Repasseur) sans candidat à cause du plafond P3, O004 (Coupeur) BLOQUÉ ; profil B →
  9 propositions sur 9, O004 BLOQUÉ.
- Chaque besoin affiche l'exigence, les candidats classés avec leur justification et le
  décompte des rejets par règle ; `--detail` liste tous les candidats, y compris rejetés.

Règles : besoins = ouvriers ABSENT (absence certaine) de la chaîne cible ; R4 compétence
(principale ou secondaire), R5 niveau ≥ minimum, R6 DISPONIBLE, R7 hors chaîne cible, R8 un
ouvrier par besoin, R9 horaire couvrant celui de l'absent ; risque sur le poste QUITTÉ :
P1/P3 bloquants, P2 et compétence critique de la donneuse → risque ÉLEVÉ ; classement :
risque, priorité de la donneuse, niveau le plus proche du minimum, principale, années,
identifiant ; ordre des besoins : critiques, moins de candidats, identifiant ; contrôle par
flot maximal (alerte si une meilleure couverture est possible).

### 9. Calculs persistés, décisions et interface (incrément 4)

Commandes :
```powershell
python -m agent_tag.cli migrer                               # applique 0004_allocation
python -m agent_tag.cli config-provisoire --profil A --auteur responsable.test
python -m agent_tag.cli verifier-integrite                   # 12 invariants, lecture seule
python -m agent_tag.api --port 8000                          # API + interface : http://127.0.0.1:8000/
```

Parcours dans l'interface : choisir la date et la chaîne → la bande de chaîne montre chaque
ouvrier par poste et son état → « Lancer le calcul des remplacements » → choisir un besoin →
lire la proposition, sa justification, les candidats classés et les candidats écartés →
« Confirmer le remplacement » ou « Refuser la proposition » (motif obligatoire, recalcul
automatique) → l'historique des décisions se met à jour.

Règles appliquées :
- une proposition réserve l'ouvrier pour la journée mais **n'est pas une affectation** ; seule la
  confirmation explicite d'un utilisateur autorisé crée un remplacement ;
- un ouvrier ne peut être réservé ou engagé qu'une fois par jour, tous calculs confondus
  (index unique en base) ; verrous dans l'ordre date → calcul → chaîne donneuse → ouvrier ;
- à la confirmation : proposition encore active, calcul ouvert, données inchangées depuis le
  calcul, P1 et P3 revérifiés avec les engagements actuels ;
- un refus exclut l'ouvrier pour ce besoin (D8, proposition par défaut) et relance le calcul ;
- un réimport annule les propositions (calcul « à recalculer ») et met « à revoir » les
  remplacements devenus non conformes, sans jamais les annuler automatiquement ;
- décisions, évaluations et itérations ne peuvent être ni modifiées ni supprimées.

API (identification par l'en-tête `X-Utilisateur`, sans authentification — D14 ouverte) :
`GET /api/etat`, `GET /api/effectifs?date&chaine`, `GET|POST /api/runs`, `GET /api/runs/{id}`,
`POST /api/runs/{id}/recalculer|cloturer`, `POST /api/propositions/{id}/accepter|refuser`,
`POST /api/besoins/{id}/laisser-non-pourvu`, `POST /api/remplacements/{id}/annuler|confirmer-apres-reimport`,
`GET /api/decisions`, `GET /api/integrite`. Documentation interactive : http://127.0.0.1:8000/docs.

### 10. Lancer les tests

```powershell
python -m pytest -v
```

Les tests de base de données créent puis suppriment des bases `agent_tag_pytest_*` et ne
modifient jamais `agent_tag_test`. Sans `.env` valide, ces tests sont **ignorés (skipped)**,
pas réussis : vérifier le résumé affiché par pytest.

## Conventions

- Une migration appliquée n'est jamais modifiée : on ajoute un nouveau fichier `NNNN_nom.sql`.
- Le rôle `agent_tag_app` n'a aucun droit sur le schéma ; les migrations passent par `agent_tag_owner`.
- Les mots de passe fournis sont **réservés au TEST**.
