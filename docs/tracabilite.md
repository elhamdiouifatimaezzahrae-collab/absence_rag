# Traçabilité exigences ↔ tests

Seuls les tests **exécutés** sont marqués « vérifié », avec la date d'exécution.

## Incrément 0

| Exigence | Test(s) | Statut |
|---|---|---|
| Connexion avec le rôle applicatif, PostgreSQL ≥ 16 | `tests/db/test_connexion.py::test_connexion_role_applicatif_et_version` | Vérifié 2026-10-24 |
| Le rôle applicatif ne peut pas modifier le schéma | `test_role_applicatif_ne_peut_pas_modifier_le_schema` | Vérifié 2026-10-24 |
| Le rôle applicatif ne peut pas écrire l'environnement | `test_role_applicatif_ne_peut_pas_ecrire_l_environnement` | Vérifié 2026-10-24 |
| Migrations : application tracée, idempotence, empreinte, tout ou rien, verrou | `tests/db/test_migrations.py` (6 tests) | Vérifié 2026-10-24 |
| Environnement : ligne unique, usage valide | `tests/db/test_environnement.py` | Vérifié 2026-10-24 |
| T67 — usage immuable ; identifiant immuable ; suppression interdite | `test_T67_usage_immuable`, `test_identifiant_immuable`, `test_suppression_interdite` | Vérifié 2026-10-24 |
| Fuseau horaire : facultatif, jamais deviné, validé s'il est renseigné | `test_fuseau_facultatif_mais_valide_si_renseigne` | Vérifié 2026-10-24 |
| T94 — refus de démarrer si l'usage déclaré diffère | `tests/integration/test_demarrage.py::test_T94_demarrage_refuse_si_usage_different` + commande `verifier` | Vérifié 2026-10-24 |
| Refus de démarrer : schéma non migré, migration en attente, environnement absent | `tests/integration/test_demarrage.py` | Vérifié 2026-10-24 |
| Configuration : aucune valeur supposée | `tests/unit/test_settings.py` (6 tests) | Vérifié 2026-10-24 |
| X1 — FK composite, toutes colonnes obligatoires (`MATCH FULL`) | `tests/db/test_prerequis_postgres.py::test_X1_*` | Vérifié 2026-10-24 (sonde) |
| X2 — unicité restreinte à un statut | `test_X2_*` | Vérifié 2026-10-24 (sonde) |
| X3 — verrou consultatif sur clé logique, attente et libération au COMMIT | `test_X3_*` (2 tests, deux sessions réelles) | Vérifié 2026-10-24 (sonde) |
| X4 — instantané cohérent (REPEATABLE READ) | `test_X4_*` | Vérifié 2026-10-24 (sonde) |
| X5 — contrôle différé en fin de transaction | `test_X5_*` | Vérifié 2026-10-24 (sonde) |
| X6 — non-chevauchement d'intervalles (btree_gist) | `test_X6_*` | Vérifié 2026-10-24 (sonde) |

« Sonde » : le mécanisme PostgreSQL est vérifié sur des tables minimales. Son application aux
tables métier sera vérifiée par les tests des incréments suivants.

## Non vérifié à l'incrément 0

| Élément | Raison |
|---|---|
| T95 — clonage d'une base sans réinitialisation de l'environnement | Procédure de réinitialisation non encore écrite (prévue avec la procédure de clonage) |
| `docker-compose.yml` | Démon Docker indisponible dans l'environnement d'exécution |
| Exécution sur le poste Windows | Aucun terminal disponible sur le poste depuis cette session |

## Incrément 1 — référentiel et import Excel

Fichiers de test : `tests/imports/test_import_referentiel.py` (classeurs artificiels générés par
`tests/imports/fabrique.py`), `tests/imports/test_classeur_reference.py`,
`tests/db/test_referentiel_contraintes.py`. Tous exécutés le 2026-10-24.

| Exigence de l'incrément 1 | Test(s) | Statut |
|---|---|---|
| Import valide | `test_import_valide` | Vérifié |
| Fichier absent / non lisible ; auteur inconnu | `test_fichier_introuvable`, `test_fichier_non_excel`, `test_auteur_inconnu` | Vérifié |
| Feuille obligatoire manquante (4 feuilles) ; feuille journalière manquante non bloquante | `test_feuille_obligatoire_manquante[…]`, `test_feuille_journaliere_manquante_non_bloquante` | Vérifié |
| Colonnes manquantes (4 cas) | `test_colonne_manquante[…]` | Vérifié |
| Identifiants dupliqués (4 feuilles) ; homonymes acceptés | `test_identifiant_duplique[…]`, `test_homonymes_acceptes_identification_par_id` | Vérifié |
| Références orphelines (4 cas) | `test_reference_orpheline[…]` | Vérifié |
| Niveaux hors nomenclature (3 cas, dont la casse) | `test_niveau_invalide[…]` | Vérifié + contre-épreuve (contrôle neutralisé → 3 échecs) |
| Valeurs obligatoires absentes (6 cas) | `test_valeur_obligatoire_absente[…]` | Vérifié |
| Autres contrôles bloquants (principale, nom, produit, horaire, années, certification) | `test_autres_controles_bloquants[…]` | Vérifié |
| Compteurs lues / importées / rejetées | `test_compteurs_de_lignes_rejetees`, `test_import_valide` | Vérifié |
| Réimport du même fichier sans doublon | `test_reimport_du_meme_fichier_sans_doublon` | Vérifié |
| Retour arrière complet en cas d'échec d'écriture (erreur PostgreSQL réelle) | `test_retour_arriere_complet_si_l_ecriture_echoue` | Vérifié |
| Retour arrière par contrôle différé de la base | `test_retour_arriere_si_controle_differe_echoue` | Vérifié (cause confirmée : « 0 compétence principale ») |
| Conservation des données validées après un import invalide | `test_import_invalide_apres_import_valide_ne_modifie_rien`, `test_autre_referentiel_refuse_D15_et_donnees_conservees` | Vérifié |
| Import valide après un rejet | `test_import_valide_possible_apres_un_rejet` | Vérifié |
| D15 sous concurrence : deux imports simultanés → un seul appliqué | `test_deux_imports_concurrents_un_seul_applique` | Vérifié |
| Exigences incomplètes signalées, non corrigées (Coupeur, niveau minimum absent) | `test_import_valide`, `test_niveau_minimum_absent_signale_et_non_complete`, `test_import_du_classeur_de_reference` | Vérifié |
| Classeur de référence : volumes, 9 exigences absentes, homonymes, fichier non modifié | `test_import_du_classeur_de_reference` | Vérifié |
| Contraintes portées par la base (principale unique et obligatoire, niveau, exigence active unique, D15, droits) | `tests/db/test_referentiel_contraintes.py` (14 tests) | Vérifié |

## Non vérifié à l'incrément 1

| Élément | Raison |
|---|---|
| Import des absences et affectations | Hors périmètre (incrément 2) ; seule la structure des feuilles est contrôlée |
| Exécution sur le poste Windows | Poste non joignable au moment des vérifications |
| Classeurs volumineux (performance) | Non mesuré ; 150 ouvriers importés en moins d'une seconde dans les tests |

## Incrément 2 — données journalières et disponibilité

Fichiers de test : `tests/unit/test_disponibilite_regles.py`, `tests/imports/test_import_journalier.py`,
`tests/imports/test_disponibilite.py`, `tests/imports/test_classeur_reference.py` (second test).
Données ARTIFICIELLES générées par `tests/imports/fabrique.py` (`journalier()`), sauf le test du
classeur de référence (lu, empreinte vérifiée inchangée). Tous exécutés le 2026-10-24.

| Exigence de l'incrément 2 | Test(s) | Statut |
|---|---|---|
| Table de décision de la disponibilité (12 combinaisons) ; donnée manquante jamais « disponible » ; besoin seulement si affectation Absent + absence certaine | `test_table_de_decision[…]`, `test_une_donnee_manquante_…`, `test_besoin_uniquement_…` | Vérifié |
| Import valide des affectations et absences, couvertures, version de date | `test_import_valide_affectations_et_absences` | Vérifié |
| Absences non attestées → couverture PARTIEL, présents INCONNU | `test_absences_non_attestees_couverture_partielle`, `test_sans_attestation_aucun_present_n_est_disponible` | Vérifié |
| Feuille ou colonnes obligatoires manquantes | `test_feuille_obligatoire_manquante[…]`, `test_colonne_manquante[…]` | Vérifié |
| Dates invalides (texte, nombre, heure, vide, formule sans valeur) | `test_date_invalide[…]`, `test_date_par_formule_sans_valeur_calculee` | Vérifié |
| Durées invalides (0, négative, décimale, texte, vide) ; durée > 1 signalée (D19) | `test_duree_invalide[…]`, `test_duree_superieure_a_un_jour_signalee_D19` | Vérifié |
| Identifiants inconnus (ouvrier, chaîne, poste) ; incohérences (nom, produit, statuts, horaire) | `test_identifiants_inconnus[…]`, `test_valeurs_incoherentes[…]` | Vérifié |
| Doublons d'affectation ; absences chevauchantes (code et base) | `test_doublon_d_affectation`, `test_absences_chevauchantes[…]`, `test_base_refuse_absences_chevauchantes_dans_un_lot` | Vérifié |
| Absences couvrant la date demandée (durée 3, fenêtre D19, absence antérieure) | `test_absence_de_plusieurs_jours_couvre_la_date_demandee`, `test_absence_anterieure_ne_couvre_pas_la_date` | Vérifié |
| Ouvriers sans affectation journalière ; absence sans affectation | `test_ouvrier_sans_affectation_couverture_partielle`, `test_ouvrier_sans_affectation_inconnu`, `test_absence_sans_affectation_absent_sans_besoin` | Vérifié |
| Contradictions : signalées à l'import, résolues en INDETERMINE | `test_contradictions_signalees_et_import_applique`, `test_contradictions_resolues_en_indetermine` | Vérifié |
| Date sans données → INCONNU (rien n'est généré) | `test_date_sans_donnees_tous_inconnus` | Vérifié |
| `Ouvriers.Statut` jamais utilisé | `test_statut_du_referentiel_jamais_utilise` | Vérifié |
| Imports répétés : même fichier sans doublon ; nouveau fichier remplace la couverture | `test_reimport_du_meme_fichier_sans_doublon`, `test_nouveau_fichier_remplace_…`, `test_deux_imports_concurrents_pour_la_meme_date` | Vérifié |
| Retour arrière complet (erreur PostgreSQL réelle) ; données validées préservées | `test_retour_arriere_si_l_ecriture_echoue`, `test_import_invalide_ne_modifie_pas_…`, `test_lot_rejete_sans_effet_sur_la_disponibilite` | Vérifié |
| Conservation de l'historique : lignes conservées, état passé relu à un instant donné | `test_nouveau_fichier_remplace_…`, `test_historique_relu_a_un_instant_passe` | Vérifié + contre-épreuves (2 mutations détectées) |
| Droits et garde de la base (lignes importées non modifiables, transition de couverture) | `test_role_applicatif_ne_modifie_pas_…`, `test_couverture_seule_transition_…` | Vérifié |
| Classeur de référence : 150 affectations, 16 absences, 0 contradiction, 134 DISPONIBLE / 16 ABSENT, O001–O010 absents sur L1 | `test_import_journalier_du_classeur_de_reference` | Vérifié |

## Non vérifié à l'incrément 2

| Élément | Raison |
|---|---|
| Saisies manuelles (complément, correction, saisie prioritaire D20) | Hors périmètre de cet incrément ; colonne `source` prévue, aucune commande |
| Effet d'un réimport sur des runs ou remplacements | Ces objets n'existent pas encore (incréments 4–5) |
| Exécution sur le poste Windows | Poste non joignable depuis cette session au moment des vérifications |

## Incrément 3 — moteur d'allocation

Fichiers de test : `tests/unit/test_allocation.py` (instantanés ARTIFICIELS de
`tests/unit/fabrique_allocation.py`), `tests/imports/test_allocation_base.py`. Exécutés le 2026-10-24.

| Exigence de l'incrément 3 | Test(s) | Statut |
|---|---|---|
| Compétence principale ou secondaire (R4) | `test_competence_secondaire_admise`, `test_detenteurs_sans_la_competence_non_evalues` | Vérifié |
| Niveau minimum (R5) | `test_niveau_inferieur_refuse_superieur_admis` | Vérifié |
| Candidats indisponibles (R6 : ABSENT, INDETERMINE, INCONNU) | `test_candidat_non_disponible_refuse[…]`, `test_candidat_absent_ou_inconnu_jamais_propose` | Vérifié |
| Chaîne cible exclue (R7, D1) ; horaire (R9) ; engagés ailleurs (S0) ; R-CASCADE | `test_chaine_cible_exclue_D1`, `test_horaire_incompatible_refuse`, `test_engage_ailleurs_S0_et_cascade_refuses` | Vérifié |
| Risques donneurs : P1, P2, P3, compétence critique, criticité inconnue, poste quitté, absences de la donneuse | `test_P1_…`, `test_risque_mesure_sur_le_poste_quitte_…`, `test_absences_de_la_donneuse_…`, `test_P2_…`, `test_criticite_inconnue_…`, `test_P3_…` | Vérifié |
| Classement R14 (risque, priorité, niveau juste suffisant, type, années, identifiant ; ex æquo ; certification sans effet) | `test_classement_…`, `test_risque_faible_passe_avant_…`, `test_departage_…`, `test_certification_sans_effet_…` | Vérifié + contre-épreuve |
| Besoins bloqués (exigence absente, niveau minimum absent, correspondance déduite sans effet) | `test_besoin_bloque_…`, `test_correspondance_deduite_ne_debloque_pas_le_poste` | Vérifié |
| Besoin seulement pour une absence confirmée ; écarts signalés | `test_besoin_seulement_pour_une_absence_confirmee` | Vérifié |
| Cas sans solution (aucun détenteur, P3, P1, vivier épuisé) | `test_aucun_detenteur`, `test_P3_…`, `test_scenario_artificiel_…`, `test_scenario_reference_L1` | Vérifié |
| Allocation séquentielle : ordre des besoins, unicité, risque recalculé, déterminisme | `test_ordre_…`, `test_un_ouvrier_n_est_propose_qu_une_fois_…`, `test_calcul_deterministe` | Vérifié + contre-épreuve |
| Couverture maximale : exemple de la Phase 3C (3 vs 2, alerte), P3, besoins bloqués ignorés | `test_flot_exemple_3C_…`, `test_flot_respecte_P3`, `test_flot_ignore_les_besoins_bloques` | Vérifié |
| Flot = optimum exact ; séquentiel ≤ maximum (I15) | `test_propriete_…[0-39]` (40 instances aléatoires, comparaison à une énumération exhaustive) | Vérifié + contre-épreuve |
| Configuration incohérente refusée ; profils provisoires non validés | `test_configuration_incoherente_refusee`, `test_profils_provisoires_non_valides`, `test_commande_allouer_refusee_hors_TEST` | Vérifié |
| Le calcul ne modifie pas les données (instantané en mémoire, base entière, transaction READ ONLY) | `test_moteur_ne_modifie_pas_l_instantane`, `test_scenario_reference_L1`, `test_commande_allouer_en_lecture_seule`, `test_lecture_dans_une_transaction_en_lecture_seule` | Vérifié |
| Scénario de référence 12/10/2026 L1 (profils A et B) | `test_scenario_reference_L1` | Vérifié |

## Non vérifié à l'incrément 3

| Élément | Raison |
|---|---|
| Runs, itérations, propositions, réservations et décisions persistés ; concurrence entre runs | Incrément 4 |
| Valeurs réelles de P1, P2, P3 et des priorités | Décisions D3, D4 ouvertes |
| Exécution sur le poste Windows | Aucun terminal disponible sur le poste depuis cette session |

## Incrément 4 — calculs persistés, décisions, réservations, API, interface

Fichiers : `tests/imports/test_services_allocation.py` (29), `tests/imports/test_api.py` (4),
`tests/unit/test_allocation.py` (exclusions), `tests/navigateur/parcours_demo.py` (navigateur).
Exécutés le 2026-10-25 dans l'espace de travail cloud (PostgreSQL 16.15, Python 3.13, Chromium).

| Exigence | Test(s) | Statut |
|---|---|---|
| Enregistrer chaque calcul (run, itération, besoins, évaluations, justifications) ; aucune affectation créée par un calcul | `test_lancer_enregistre_le_calcul_sans_aucune_affectation` | Vérifié |
| Lancement refusé : calcul déjà ouvert, données incomplètes (I10), configuration absente | `test_lancer_refuse_…` (2) | Vérifié |
| Confirmation explicite : remplacement, engagement, décision tracée et marquée TEST | `test_accepter_cree_le_remplacement_et_engage_l_ouvrier` | Vérifié |
| Pas de double confirmation | `test_double_acceptation_refusee`, `test_concurrence_deux_acceptations_…` (×3) | Vérifié |
| Refus : motif obligatoire, exclusion, recalcul, propositions précédentes annulées et conservées | `test_refuser_…` | Vérifié + contre-épreuve |
| Utilisateur autorisé uniquement | `test_utilisateur_non_autorise_ou_inconnu`, `test_api` | Vérifié |
| Données modifiées depuis le calcul ; revérification P1/P3 | `test_acceptation_refusee_si_les_donnees_ont_change`, `test_acceptation_revalide_P1_et_P3[…]` | Vérifié |
| Laisser non pourvu ; annuler un remplacement (exclusion, annulation unique) ; clôture ; nouveau calcul sans recréer les besoins pourvus (I11) | `test_laisser_non_pourvu`, `test_annuler_…`, `test_cloture_puis_…` | Vérifié + contre-épreuve |
| Réimport : calcul à recalculer, propositions annulées, remplacement à revoir (jamais annulé), confirmation refusée si non conforme, remplacement conforme maintenu | `test_reimport_…` (2) | Vérifié |
| Concurrence : acceptations simultanées, acceptation contre refus, calculs simultanés sur deux chaînes, lancements simultanés, acceptations pendant un import | `test_concurrence_…` (5 tests, 11 exécutions) | Vérifié |
| Historique non modifiable ; configuration active immuable ; aucune activation hors TEST d'une configuration non validée | `test_lignes_d_historique_…`, `test_configuration_…`, `test_hors_TEST_…` | Vérifié |
| Invariants I1, I2, I3, I6, I13, I14, I16, I21, I23 et unicités après chaque opération | `sain()` dans chaque test + `verifier-integrite` | Vérifié |
| API : parcours complet, codes d'erreur, interface servie, refus de démarrer si l'usage diffère | `tests/imports/test_api.py` | Vérifié |
| Interface réelle contre le backend : affichage, lancement, droits, confirmation, refus, besoin bloqué, rejets, historique, mobile | `tests/navigateur/parcours_demo.py` (Chromium/Playwright) | Vérifié (captures dans `docs/captures/`) |

## Non vérifié à l'incrément 4

| Élément | Raison |
|---|---|
| Exécution sur le poste Windows | Aucun terminal disponible sur le poste depuis cette session |
| Police Archivo | Non chargée dans l'environnement de test (pas d'accès Internet) : la police de repli a été utilisée |
| CHOISIR_AUTRE, dérogation, saisies, expiration automatique | Non implémentés |
| Charge et performance au-delà de 150 ouvriers | Non mesurées |

## Incrément 5

| Exigence | Vérification |
|---|---|
| Choisir un autre candidat admissible, motif obligatoire, historique affichant le candidat choisi | `tests/imports/test_choix_et_reouverture.py::test_choisir_autre_cas_nominal`, `test_api.py::test_choix_reouverture_engagements_et_imports_par_l_api`, parcours navigateur étape 7 |
| Reprise d'un candidat réservé par un autre besoin du même calcul | `test_choisir_autre_reprend_un_candidat_reserve_dans_le_meme_calcul` |
| Refus sans effet : motif absent, même candidat, non évalué, non éligible, lecteur, engagé, réservé par un autre calcul | `test_choisir_autre_refus_sans_effet`, `test_choisir_autre_refuse_un_candidat_engage`, `test_choisir_autre_refuse_un_candidat_reserve_par_un_autre_calcul` |
| Laisser non pourvu puis rouvrir ; refus hors NON_POURVU et après clôture | `test_rouvrir_un_besoin_laisse_non_pourvu`, `test_rouvrir_refuse_hors_non_pourvu_et_apres_cloture`, parcours étape 8 |
| Réservations et engagements visibles | `test_vue_engagements_distingue_reserve_et_engage`, parcours étape 9 |
| Conséquences d'un réimport visibles, remplacement confirmé jamais annulé seul | `test_simulation_de_reimport_rend_les_consequences_visibles`, parcours étape 11 |
| Invariant CHOISIR_AUTRE (remplacement créé, proposition substituée annulée) | `services/integrite.py`, vérifié après chaque test et en fin de parcours |
| API limitée à la boucle locale | `tests/unit/test_lanceur_api.py` |
| Installation reproductible | installation propre depuis l'archive (environnement neuf, `requirements-dev.lock`, PostgreSQL 16 neuf initialisé par `docker/init/01_roles_et_base.sql`) : 308 tests réussis, parcours navigateur réussi |
| Scripts Windows | analyse syntaxique PowerShell, fonctions communes exécutées avec PowerShell 7 sous Linux ; **non exécutés sous Windows** |
| Configuration Codespaces | `devcontainer.json` (JSON valide), compose validé par `docker compose config` ; scripts `scripts/codespaces/*.sh` rejoués hors conteneur sur une copie vierge avec PostgreSQL 16 neuf initialisé par `docker/init` : installation, démarrage, double démarrage, parcours navigateur, réimport simulé, réinitialisation, arrêt, réinstallation, 308 tests. **Non démarrée dans un vrai Codespace** |
| Import dans le dépôt | `scripts/importer-dans-depot.sh` testé sur trois dépôts fictifs : fichier existant (arrêt sans modification), `--remplacer` (branche séparée, `main` intact), modification non commitée (refus) |
