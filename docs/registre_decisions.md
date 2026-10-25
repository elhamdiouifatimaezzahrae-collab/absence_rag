# Registre des décisions — Agent TAG

Référence : modèle relationnel validé (Phase 4 + 4.1, 4.2, 4.3) ; architecture Phase 5.

Statuts : **Validée** · **Proposition par défaut** (à confirmer) · **Ouverte** · **Hors V1**.
Les « choix provisoires TEST » ne valent qu'en environnement TEST, sont enregistrés comme
*non validés* dans la configuration et affichés avec chaque résultat. Aucun n'est une règle métier.

## Décisions métier

| # | Objet | Statut | Choix provisoire TEST | Bloque l'exploitation | Valideur |
|---|---|---|---|---|---|
| D1 | Réaffectation interne à la chaîne cible | Hors V1 | Interdite | — | Responsable métier |
| D2 | Niveau minimum Coupe | Ouverte | Aucun : besoin Bloqué | Non | Responsable métier |
| D3 | `m_bloc` (P1), `m_alerte` (P2), `p3` (P3) | Ouverte | Profil A : 1 / 2 / 2 · Profil B : 1 / 1 / 10 (valeurs arbitraires de test, codées dans `PROFILS_PROVISOIRES`, `validee = False`) ; la commande `allouer` refuse tout usage hors TEST | **Oui** | Responsable métier |
| D4 | Ordre des priorités des chaînes | Ouverte | Moyenne < Élevée < Très élevée (déduit des libellés) | **Oui** | Responsable métier |
| D5 | Dérogations autorisées | Ouverte | Désactivées | Non | Responsable métier |
| D6 | Remplacement à la journée entière | Proposition par défaut | Appliqué | Non | Responsable métier |
| D7 | Correspondance Coupeur → Coupe | Ouverte | Marquée « déduite » | Non | Responsable métier |
| D8 | Portée d'un refus ; héritage des exclusions | Proposition par défaut | Besoin seul ; héritage désactivé | Non | Responsable métier |
| D9 | Un seul run ouvert par (date, chaîne cible) | Proposition par défaut | Appliqué | Non | Responsable métier |
| D10 | Validation des lots avant application | Ouverte | Désactivée : un lot valide est appliqué immédiatement (incrément 2) | Non | Responsable métier |
| D11 | Affichage de la chaîne d'échanges | Proposition par défaut | Affichée | Non | Responsable métier |
| D12 | Expiration (mode, délai, référence) | Ouverte | MANUELLE | **Oui** | Responsable métier |
| D13 | Criticité dans la couverture maximale | Ouverte | Non | Non | Responsable métier |
| D14 | Utilisateurs, rôles, droits | Ouverte | Un utilisateur de test, tous droits | **Oui** | Responsable métier |
| D15 | Réimport du référentiel | Hors V1 | Import unique | — | — |
| D16 | Portée d'une dérogation | Ouverte | Sans objet (D5 désactivée) | Non | Responsable métier |
| D17 | R-CASCADE | Ouverte | Activée | **Oui** | Responsable métier |
| D18 | Attestation de complétude des absences | Ouverte | Option `--attester-absences` de l'auteur de l'import, pour les (date, chaîne) couverts par les affectations du même fichier ; sans elle, couverture PARTIEL et présents INCONNU. Limite : l'attestation ne peut pas être ajoutée après coup au même fichier (DEJA_IMPORTE) | **Oui** | Responsable métier |
| D19 | Interprétation de `Durée_jours` | Ouverte | Période certaine = [début, début + N − 1] (calendaire) ; fenêtre d'incertitude = les N − 1 jours suivants, état INDETERMINE (borne arbitraire de TEST, sans effet sur le classeur actuel où N = 1) | Non | Responsable métier |
| D20 | Saisie prioritaire | Ouverte | Interdite | Non | Responsable métier |
| ENV | Fuseau horaire de l'environnement | Ouverte | Non renseigné (non requis à l'incrément 0) | **Oui** (avant expiration automatique) | Responsable métier |

## Décisions techniques (Phase 5)

| # | Objet | Statut | Choix |
|---|---|---|---|
| TECH-1 | Pile technique | Validée | Python + PostgreSQL + FastAPI ; SQL explicite ; pytest ; migrations versionnées |
| TECH-2 | Outil de migrations | Choisi à l'incrément 0 | Scripts SQL numérotés + exécuteur interne (empreinte SHA-256, une transaction par migration, verrou consultatif). Alternative écartée : Alembic, inutile sans ORM. |
| TECH-3 | Séparation des rôles PostgreSQL | Choisi à l'incrément 0 | `agent_tag_owner` (schéma, migrations) ; `agent_tag_app` (données, sans droit sur le schéma) |
| TECH-4 | Isolation des tests | Choisi à l'incrément 0 | Base jetable par test (`agent_tag_pytest_*`), supprimée ensuite. Nécessite CREATEDB pour le propriétaire, **en TEST uniquement**. |
| T1 | Clés de `skill` et `position` | Choisi à l'incrément 1 | Code ASCII majuscule dérivé du libellé (ex. `CONTROLE_QUALITE`, `PIQUEUR_PIQUEUSE`) ; libellé d'origine conservé et unique ; deux libellés donnant le même code → import rejeté |
| TECH-5 | Granularité du rejet d'import | Choisi à l'incrément 1 | Tout ou rien : une anomalie bloquante rejette tout l'import (exigence « pas d'état partiel ») |
| TECH-6 | Catalogue des compétences | Choisi à l'incrément 1 | Compétences de la feuille Competences ∪ compétences requises de Besoins_Postes ; une compétence critique hors catalogue est une référence orpheline |
| TECH-7 | Correspondance poste → compétence | Choisi à l'incrément 1 | Lue dans Besoins_Postes (validée) ; à défaut, déduite seulement si tous les titulaires du poste ont la même compétence principale, marquée non validée (D7) ; sinon laissée vide |
| TECH-8 | Séparation des imports | Choisi aux incréments 1–2 | `importer-referentiel` lit les feuilles du référentiel (structure des feuilles journalières contrôlée) ; `importer-journalier` lit Affectations et Absences, les autres feuilles sont ignorées |
| TECH-9 | Couverture des affectations | Choisi à l'incrément 2 | Par (date, chaîne d'origine de l'ouvrier) ; créée seulement si le fichier contient au moins une affectation pour ce couple ; COMPLET si tous les ouvriers de la chaîne ont une affectation |
| TECH-10 | Absences prises en compte pour une date | Choisi à l'incrément 2 | Si une couverture ABSENCES est courante pour (date, chaîne), seules les absences de ce lot ; sinon celles de tous les lots appliqués |
| TECH-11 | Format des dates | Choisi à l'incrément 2 | Cellules date Excel uniquement ; texte, nombre brut ou heure non nulle refusés (aucun format deviné) |
| TECH-12 | Valeurs reconnues | Choisi à l'incrément 2 | `Statut_affectation` ∈ {Présent, Absent} ; `Statut_absence` = Absent (seule valeur observée, toute autre refusée faute de sens défini) |
| T2–T9 | Autres choix techniques de la Phase 5 | À mettre en œuvre aux incréments 2 à 6 | Voir Phase 5, section 3 (T7 archivage : réalisé à l'incrément 1) |

## Choix d'implémentation de l'incrément 3 (moteur d'allocation)

| # | Objet | Choix |
|---|---|---|
| TECH-13 | Poste quitté et chaîne donneuse | Ceux de l'affectation du jour (DailyAssignment fait foi, Phase 3) |
| TECH-14 | Candidats évalués | Tous les détenteurs de la compétence requise, y compris sur la chaîne cible (rejetés par R7, pour rendre D1 visible) |
| TECH-15 | R9 horaire | Compatible si l'horaire du candidat couvre celui de l'absent ; horaire inconnu → refusé |
| TECH-16 | Criticité d'un poste quitté sans compétence associée | Risque ÉLEVÉ (cause `CRITIQUE_INCONNUE`), par prudence ; une correspondance déduite (Coupeur, D7) est signalée dans l'explication |
| TECH-17 | Ordre de « premier échec » affiché | R4, R5, R6, R7, R9, R8, S0, CASCADE, P3, P1 (tous les contrôles restent enregistrés) |
| TECH-18 | « Moins de candidats » (ordre des besoins) | Nombre d'éligibles calculé avant toute réservation |
| TECH-19 | Statut d'un besoin calculé | PROPOSITION (qualité RISQUE_FAIBLE / AVEC_ALERTE), AUCUN_CANDIDAT (cause agrégée), BLOQUE ; jamais « pourvu » sans décision humaine |
| TECH-20 | Flot maximal | networkx 3.4 ; vérifié contre une énumération exhaustive sur 40 instances aléatoires |
| TECH-21 | Persistance | Aucune à l'incrément 3 : runs, itérations, évaluations et réservations persistés à l'incrément 4 ; S0 et chaînes interdites (R-CASCADE) vides |

## Choix provisoires et limites de l'incrément 4

| # | Objet | Choix provisoire TEST |
|---|---|---|
| D14 | Utilisateurs, rôles, authentification | Identification par l'en-tête `X-Utilisateur`, sans mot de passe ; seul le rôle `TEST_TOUS_DROITS` peut décider, en TEST ; hors TEST, aucune décision possible. Tout utilisateur actif peut lancer, recalculer ou clôturer un calcul |
| D3/D4/D12/D17 | Configuration | Profil provisoire A installé par `config-provisoire` ; tous les indicateurs « validé » à faux ; expiration MANUELLE ; la base refuse l'activation hors TEST |
| D5/D16 | Dérogation | Désactivée par contrainte de base ; aucune opération de dérogation |
| D8 | Refus | Exclusion pour le besoin concerné uniquement (y compris après annulation avec exclusion) |
| D9 | Calculs ouverts | Un seul calcul non clos par (date, chaîne) |
| D10 | Validation des lots | Non activée : un réimport s'applique immédiatement et déclenche ses effets |

| # | Choix d'implémentation | Détail |
|---|---|---|
| TECH-22 | Interface | Une page HTML/CSS/JS sans framework, servie par FastAPI ; police Archivo (Google Fonts) avec repli système hors ligne |
| TECH-23 | Verrous | Verrous consultatifs de transaction : (10, date), (30, calcul), (20, hash date|chaîne), (40, hash date|ouvrier), pris dans cet ordre |
| TECH-24 | Calcul en deux phases | Lecture REPEATABLE READ READ ONLY, puis validation sous verrous (version du calcul, version des données de la date, créneaux courants) ; 3 essais, sinon `CALCUL_EN_ECHEC` |
| TECH-25 | Besoin « sans candidat » | Statut NON_POURVU avec cause `AUCUN_CANDIDAT` : réévalué à chaque recalcul (contrairement à un « laissé non pourvu » décidé) |
| TECH-26 | Non implémenté à ce stade | Choisir un autre candidat que la proposition (CHOISIR_AUTRE), dérogation, saisies manuelles, expiration automatique, ROUVRIR |

## Incrément 5 (installation Windows et fin du parcours)

| # | Choix d'implémentation | Détail |
|---|---|---|
| TECH-26 (mis à jour) | Implémenté | CHOISIR_AUTRE (migration 0005) : parmi les candidats ÉLIGIBLES de la dernière itération, motif obligatoire, mêmes contrôles P1/P3 qu'à la proposition ; la proposition remplacée est annulée (SUBSTITUTION) ; si le candidat était réservé par un autre besoin du même calcul, cette réservation est reprise (CANDIDAT_REPRIS) et ce besoin recalculé ; s'il est réservé par un autre calcul ou déjà engagé, refus. ROUVRIR : un besoin laissé non pourvu d'un calcul ouvert redevient à traiter (motif obligatoire) |
| TECH-27 | Restant non implémenté | Dérogation (D5), saisies manuelles (D20), expiration automatique (D12) |
| TECH-28 | Lancement local uniquement | `python -m agent_tag.api` refuse toute adresse autre que 127.0.0.1 / localhost / ::1 : l'API n'a pas d'authentification (D14) |
| TECH-29 | Dépendances figées | `requirements.lock` (exécution) et `requirements-dev.lock` (tests), produits par pip freeze dans un environnement neuf ; colorama et tzdata ajoutés avec marqueurs Windows ; résolution vérifiée pour Windows 64 bits, Python 3.11 à 3.13 |
| TECH-30 | Bases créées depuis `template0` en UTF-8 | Indépendant de l'encodage par défaut d'une installation PostgreSQL Windows |
| TECH-31 | Scripts Windows | `scripts/windows/*.ps1`, compatibles Windows PowerShell 5.1 (UTF-8 avec BOM) ; l'API écrit son propre numéro de processus (`--fichier-pid`), car le `python.exe` d'un environnement virtuel Windows est un lanceur |
| TECH-32 | Simulation de réimport | Commande `simuler-reimport` (usage TEST) : copie du classeur où un ouvrier devient absent le 12/10, importée avec attestation ; le classeur de référence n'est jamais modifié |

Liste courte des décisions à trancher : `docs/decisions_a_trancher.md`.

## Préparation GitHub Codespaces (25/10/2026)

| # | Choix | Détail |
|---|---|---|
| TECH-33 | Devcontainer à deux conteneurs | `app` (Python 3.13, image officielle devcontainers) partage le réseau de `db` (postgres:16) ; aucun port PostgreSQL publié ; port 8000 transféré, privé par défaut ; installation à la création, démarrage à chaque reprise |
| TECH-34 | Import sans accès de Claude au dépôt | Aucun compte GitHub relié à la session : archive + `scripts/importer-dans-depot.sh` (branche séparée, arrêt en cas de fichier existant, aucun push automatique) |
