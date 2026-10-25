# Décisions métier à trancher avant tout usage réel — Agent TAG

État au 25/10/2026 (incrément 5). Aucune de ces décisions n'est validée. Les valeurs « en TEST »
sont des choix provisoires de démonstration : la base refuse de les activer hors usage TEST, et
toute décision prise avec elles est marquée « TEST, non valable en réel ».

Les huit premières bloquent la production ; les trois dernières peuvent attendre une V2.

---

## 1. Protection des chaînes donneuses — D3 (P1, P2, P3)

- **Question** : combien d'ouvriers doivent rester au minimum sur le poste quitté (P1, blocage) ?
  À partir de quel effectif restant signaler un risque (P2, alerte) ? Combien de transferts au
  plus une chaîne peut-elle céder dans la journée (P3) ?
- **Options** : valeurs fixes pour toutes les chaînes ; valeurs par chaîne ; valeurs par poste
  (un seul Coupeur ne se traite pas comme un Piqueur parmi quatre).
- **Conséquences** : ce sont les paramètres qui pèsent le plus. Avec P3 = 2, sur le scénario du
  12/10, un absent (O005) reste sans candidat et une chaîne L2 en difficulté ne trouve personne ;
  avec P3 = 10, presque tout est couvert, mais les chaînes donneuses peuvent être vidées.
- **En TEST** : profil A (P1 = 1, P2 = 2, P3 = 2) par défaut ; profil B (1 / 1 / 10) pour comparer.
- **À valider** : les trois valeurs et leur portée (globale, par chaîne ou par poste).

## 2. Ordre de priorité des chaînes — D4

- **Question** : la colonne « Priorité » (Moyenne, Élevée, Très élevée) signifie-t-elle bien
  « prendre d'abord chez la chaîne la moins prioritaire » ? Que faire en cas d'égalité ?
- **Options** : ordre des libellés (actuel) ; ordre explicite fourni par le responsable ;
  critère ignoré.
- **Conséquences** : change le candidat classé premier lorsque plusieurs chaînes peuvent céder.
- **En TEST** : Moyenne (1) < Élevée (2) < Très élevée (3), déduit des libellés.
- **À valider** : le sens et l'ordre.

## 3. Exigence des postes de coupe — D2 et D7

- **Question** : quelle compétence et quel niveau minimum exiger pour remplacer un Coupeur ?
  « Coupeur » correspond-il à la compétence « Coupe » ?
- **Options** : Coupe, niveau Intermédiaire ; Coupe, niveau Expert ; pas de remplacement externe.
- **Conséquences** : tant que ce n'est pas défini, tout absent Coupeur est **bloqué** (O004 sur
  le scénario) ; aucun candidat n'est inventé.
- **En TEST** : besoin bloqué « exigence manquante ».
- **À valider** : la compétence et le niveau minimum pour chaque poste qui n'en a pas.

## 4. Remplacements en chaîne — D17 (R-CASCADE)

- **Question** : un ouvrier déjà parti remplacer quelqu'un peut-il faire partir à son tour un
  collègue de sa propre chaîne (effet domino) ?
- **Options** : interdit (actuel) ; autorisé avec un seul niveau ; autorisé sans limite.
- **Conséquences** : l'autoriser augmente la couverture mais rend les mouvements difficiles à
  suivre dans l'atelier.
- **En TEST** : interdit (candidats « CASCADE » écartés).
- **À valider** : le choix.

## 5. Complétude des absences — D18

- **Question** : qui atteste que la liste des absences d'un jour est complète, et comment ?
- **Options** : l'auteur de l'import l'atteste (actuel) ; un responsable valide le lot ; la
  source de pointage fait foi.
- **Conséquences** : sans attestation, les présents sont « inconnus » et aucun calcul n'est
  possible ; avec une attestation erronée, un absent non déclaré peut être proposé comme remplaçant.
- **En TEST** : attestation déclarée à l'import (option `--attester-absences`), utilisée par la
  démonstration.
- **À valider** : le responsable de l'attestation et sa forme.

## 6. Utilisateurs, rôles et authentification — D14

- **Question** : qui peut consulter, lancer un calcul, confirmer, refuser, annuler ?
- **Options** : chef de chaîne / responsable de production / lecteur, ou autre découpage.
- **Conséquences** : sans rôles validés **et** sans authentification réelle, aucune décision ne
  peut être enregistrée hors TEST (l'application le refuse déjà).
- **En TEST** : `demo.responsable` (tous droits) et `demo.lecteur` (consultation). Ce ne sont pas
  des comptes : aucun mot de passe, simple sélection dans la page. L'API n'écoute que sur
  127.0.0.1 pour cette raison.
- **À valider** : les rôles et leurs droits ; le mode d'authentification (annuaire de
  l'entreprise, comptes locaux…) — à développer ensuite.

## 7. Expiration des propositions — D12

- **Question** : une proposition non confirmée doit-elle expirer seule ? Après quel délai, ou à
  quelle heure (début de poste) ?
- **Options** : jamais, clôture manuelle (actuel) ; délai fixe ; heure limite par chaîne.
- **Conséquences** : sans expiration, un ouvrier réservé reste bloqué tant que personne ne décide.
- **En TEST** : expiration manuelle (bouton « Clôturer le calcul »).
- **À valider** : le mode et le délai.

## 8. Durée des absences — D19

- **Question** : « Durée_jours = N » compte-t-il des jours calendaires ou des jours ouvrés ? Que
  vaut l'état d'un ouvrier après la période certaine ?
- **Options** : calendaire ; ouvré (avec calendrier de l'usine) ; date de fin saisie.
- **Conséquences** : sans effet sur le classeur actuel (toutes les absences durent 1 jour) ;
  déterminant dès qu'une absence dure plusieurs jours.
- **En TEST** : jours calendaires ; les N − 1 jours suivants sont « indéterminés ».
- **À valider** : le mode de calcul.

---

## Peuvent attendre (sans effet bloquant sur la démonstration)

| Décision | Question | En TEST |
|---|---|---|
| D8 — portée d'un refus | Un ouvrier refusé pour un besoin l'est-il pour toute la journée ? | Pour ce besoin seulement |
| D10 — validation des lots | Un réimport doit-il être validé avant de s'appliquer ? | Appliqué immédiatement ; ses conséquences sont affichées |
| D20 — saisie manuelle | Peut-on saisir une absence ou un remplaçant hors classeur ? | Interdit : toute donnée passe par un import tracé |

**Saisies manuelles** : non développées volontairement. Le parcours validé n'en a pas besoin
(les absences viennent de l'import ; le remplaçant est choisi parmi les candidats admissibles avec
« Choisir ce candidat »). Les ajouter supposerait de trancher D20 et de définir leur traçabilité.
