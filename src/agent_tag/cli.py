"""Commandes d'administration : `python -m agent_tag.cli <commande>`.

  migrer                      applique les migrations en attente (rôle propriétaire)
  init-env --libelle TEXTE    crée la ligne d'environnement avec l'usage déclaré
            [--fuseau ZONE]   (rôle propriétaire ; fuseau facultatif, jamais déduit)
  verifier                    contrôles de démarrage avec le rôle applicatif
  creer-utilisateur --identifiant ID --nom NOM --role ROLE
                              crée un utilisateur (rôle propriétaire ; rôles : D14 ouverte)
  importer-referentiel FICHIER --auteur ID [--rapport-json CHEMIN]
                              importe le référentiel du classeur (rôle applicatif)
  importer-journalier FICHIER --auteur ID [--attester-absences] [--rapport-json CHEMIN]
                              importe les feuilles Affectations et Absences (rôle applicatif)
  disponibilite --date AAAA-MM-JJ [--ouvrier ID ...] [--chaine ID] [--instant ISO]
                [--etat ETAT] [--json CHEMIN]
                              disponibilité des ouvriers pour une date (lecture seule)
  allouer --date AAAA-MM-JJ --chaine ID --profil A|B [--candidats N] [--detail] [--json CHEMIN]
                              recommandations de remplaçants (calcul en lecture seule,
                              paramètres PROVISOIRES de TEST, non validés)
  config-provisoire --profil A|B --auteur ID
                              installe et active un profil PROVISOIRE (TEST, rôle propriétaire)
  initialiser-demo [--base agent_tag_demo] [--profil A]
                              (re)crée une base de DÉMONSTRATION TEST avec les données fictives
  verifier-integrite          contrôle les invariants (lecture seule)
  simuler-reimport --ouvrier ID [--auteur ID]
                              DÉMONSTRATION TEST : réimporte le 12/10 avec cet ouvrier absent
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import psycopg

from agent_tag.config import demarrage, settings
from agent_tag.domain import allocation
from agent_tag.services.allocation import RefusMetier
from agent_tag.imports import import_journalier, import_referentiel
from agent_tag.imports import rapport as r
from agent_tag import demo
from agent_tag.persistence import db, disponibilite, instantane, migrations
from agent_tag.services import configuration, integrite


def _exiger_owner(conf: settings.Settings) -> str:
    if not conf.owner_url:
        raise settings.ConfigurationInvalide("AGENT_TAG_OWNER_URL n'est pas défini")
    return conf.owner_url


def cmd_migrer(conf: settings.Settings, _args) -> int:
    faites = migrations.migrer(_exiger_owner(conf))
    if faites:
        for m in faites:
            print(f"appliquée : {m.version:04d}_{m.nom}")
    else:
        print("aucune migration en attente")
    return 0


def cmd_init_env(conf: settings.Settings, args) -> int:
    with db.connecter(_exiger_owner(conf)) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO environment (usage, libelle, fuseau_horaire) VALUES (%s, %s, %s) "
            "RETURNING id_environnement",
            (conf.usage, args.libelle, args.fuseau),
        )
        print(f"environnement créé : {cur.fetchone()[0]} (usage {conf.usage})")
    return 0


def cmd_verifier(conf: settings.Settings, _args) -> int:
    with db.connecter(conf.database_url) as conn:
        etat = demarrage.verifier(conn, conf.usage)
    fuseau = etat.fuseau_horaire or "non renseigné"
    print(f"OK — environnement {etat.id_environnement}, usage {etat.usage}, fuseau {fuseau}")
    return 0


def cmd_creer_utilisateur(conf: settings.Settings, args) -> int:
    with db.connecter(_exiger_owner(conf)) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_user (identifiant, nom, role) VALUES (%s, %s, %s) RETURNING id",
            (args.identifiant, args.nom, args.role),
        )
        print(f"utilisateur créé : {args.identifiant} (id {cur.fetchone()[0]}, rôle {args.role})")
    return 0


def cmd_importer_referentiel(conf: settings.Settings, args) -> int:
    with db.connecter(conf.database_url) as conn:
        demarrage.verifier(conn, conf.usage)
    rap = import_referentiel.importer(conf.database_url, Path(args.fichier), args.auteur,
                                      conf.dossier_archives)
    print(rap.en_texte())
    if args.rapport_json:
        Path(args.rapport_json).write_text(
            json.dumps(rap.en_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nrapport JSON écrit : {args.rapport_json}")
    return 0 if rap.statut in (r.APPLIQUE, r.DEJA_IMPORTE) else 2


def cmd_importer_journalier(conf: settings.Settings, args) -> int:
    with db.connecter(conf.database_url) as conn:
        demarrage.verifier(conn, conf.usage)
    rap = import_journalier.importer(conf.database_url, Path(args.fichier), args.auteur,
                                     conf.dossier_archives, args.attester_absences)
    print(rap.en_texte())
    if args.rapport_json:
        Path(args.rapport_json).write_text(
            json.dumps(rap.en_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nrapport JSON écrit : {args.rapport_json}")
    return 0 if rap.statut in (r.APPLIQUE, r.DEJA_IMPORTE) else 2


def cmd_disponibilite(conf: settings.Settings, args) -> int:
    jour = date.fromisoformat(args.date)
    instant = datetime.fromisoformat(args.instant) if args.instant else None
    with db.connecter(conf.database_url, autocommit=True) as conn:
        demarrage.verifier(conn, conf.usage)
        resultats = disponibilite.consulter(conn, jour, instant, args.ouvrier, args.chaine)
    if args.etat:
        resultats = [x for x in resultats if x.etat == args.etat]

    print(f"Disponibilité au {jour.isoformat()}"
          + (f" (état des données à {instant.isoformat()})" if instant else "")
          + f" — {len(resultats)} ouvrier(s)\n")
    print(f"{'Ouvrier':<8}{'Nom':<24}{'Chaîne':<8}{'État':<13}{'Besoin':<8}{'Cause':<36}"
          f"{'Couv. aff.':<12}{'Couv. abs.':<12}")
    for x in resultats:
        print(f"{x.id_ouvrier:<8}{x.nom[:23]:<24}{x.id_chaine:<8}{x.etat:<13}"
              f"{'oui' if x.besoin_creable else '-':<8}{x.cause:<36}"
              f"{(x.couverture_affectations or 'aucune'):<12}"
              f"{(x.couverture_absences or 'aucune'):<12}")
    print("\nSynthèse : " + ", ".join(
        f"{e} {n}" for e, n in sorted(Counter(x.etat for x in resultats).items())))
    if args.json:
        Path(args.json).write_text(json.dumps(
            [asdict(x) for x in resultats], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON écrit : {args.json}")
    return 0


AVERTISSEMENT_PROVISOIRE = (
    "PARAMÈTRES PROVISOIRES DE TEST — NON VALIDÉS (D3 : P1, P2, P3 ; D4 : priorités).\n"
    "Résultat non utilisable pour une décision réelle. Toute affectation reste soumise à une "
    "validation humaine.")


def cmd_allouer(conf: settings.Settings, args) -> int:
    if conf.usage != "TEST":
        raise settings.ConfigurationInvalide(
            "aucune configuration validée n'existe : le calcul n'est autorisé qu'en usage TEST")
    cfg = allocation.PROFILS_PROVISOIRES[args.profil]
    jour = date.fromisoformat(args.date)
    with db.connecter(conf.database_url, autocommit=True) as conn:
        demarrage.verifier(conn, conf.usage)
        inst = instantane.lire(conn, jour)
    res = allocation.allouer(inst, cfg, args.chaine)

    print("=" * 100 + "\n" + AVERTISSEMENT_PROVISOIRE + "\n" + "=" * 100)
    print(f"Date {jour.isoformat()} — chaîne cible {args.chaine} — données lues à {res.lecture}")
    print(f"{cfg.libelle} : m_bloc (P1) = {cfg.m_bloc}, m_alerte (P2) = {cfg.m_alerte}, "
          f"p3 (P3) = {cfg.p3} ; rangs de priorité {cfg.rangs_priorite}\n")
    print(f"{'Ordre':<6}{'Absent':<8}{'Poste':<32}{'Crit.':<7}{'Statut':<16}{'Qualité':<15}"
          f"{'Proposé':<9}{'Donneuse':<9}")
    for b in sorted(res.besoins, key=lambda b: (b.rang_traitement or 999, b.id_ouvrier_absent)):
        p = b.proposition
        print(f"{str(b.rang_traitement or '-'):<6}{b.id_ouvrier_absent:<8}{b.poste:<32}"
              f"{'oui' if b.critique else '-':<7}{b.statut:<16}{b.qualite or '-':<15}"
              f"{p.id_ouvrier if p else '-':<9}{p.chaine_donneuse if p else '-':<9}")

    for b in sorted(res.besoins, key=lambda b: (b.rang_traitement or 999, b.id_ouvrier_absent)):
        print(f"\n— {b.id_ouvrier_absent} {b.nom_absent}, {b.poste} : {b.statut}")
        if b.statut == allocation.BLOQUE or not b.evaluations:
            print(f"   {b.cause}")
            continue
        exigence = (f"   exigence : {inst.libelles_competence.get(b.competence)} niveau ≥ "
                    f"{inst.niveaux.get(b.code_niveau_min)} ; candidats éligibles au départ : "
                    f"{b.nb_eligibles_initial} ; détenteurs évalués : {len(b.evaluations)}")
        print(exigence)
        if b.statut == allocation.AUCUN_CANDIDAT:
            print(f"   {b.cause}")
        eligibles = [e for e in b.evaluations if e.eligible]
        montres = eligibles if args.detail else eligibles[:args.candidats]
        for e in montres:
            print(f"   {e.id_ouvrier} : {e.explication}")
        if len(eligibles) > len(montres):
            print(f"   … {len(eligibles) - len(montres)} autre(s) éligible(s) (--detail)")
        rejets = Counter(e.premier_echec for e in b.evaluations if not e.eligible)
        if rejets:
            print("   rejetés : " + ", ".join(f"{k} ×{n} ({allocation.LIBELLE_CONTROLE[k]})"
                                              for k, n in sorted(rejets.items())))
        if args.detail:
            for e in b.evaluations:
                if not e.eligible:
                    print(f"   {e.id_ouvrier} : {e.explication}")

    print(f"\nCouverture : séquentielle {res.couverture_sequentielle} / maximale "
          f"{res.couverture_maximale} (flot maximal, contraintes strictes) sur "
          f"{res.besoins_consideres} besoin(s) traitable(s) ; "
          f"{sum(b.statut == allocation.BLOQUE for b in res.besoins)} bloqué(s)")
    if res.alerte_combinaison:
        print("ALERTE : une meilleure combinaison existe (à réarbitrer par le responsable). "
              "Combinaison atteignant le maximum : " + ", ".join(
                  f"{k}←{v}" for k, v in sorted(res.combinaison_maximale.items())))
    for e in res.ecarts:
        print(f"Écart sans besoin créé : {e.id_ouvrier} {e.etat} ({e.cause})")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"avertissement": AVERTISSEMENT_PROVISOIRE, "utilisable_en_production": False,
             "resultat": asdict(res)}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"JSON écrit : {args.json}")
    return 0


def cmd_config_provisoire(conf: settings.Settings, args) -> int:
    version = configuration.installer_profil_provisoire(_exiger_owner(conf), args.profil,
                                                        args.auteur)
    print(f"configuration {version} active : profil {args.profil} PROVISOIRE (non validé)")
    return 0


def cmd_initialiser_demo(conf: settings.Settings, args) -> int:
    if conf.usage != "TEST":
        raise settings.ConfigurationInvalide("la démonstration ne s'installe qu'en usage TEST")
    res = demo.initialiser(_exiger_owner(conf), conf.database_url, args.base,
                           conf.dossier_archives, args.profil)
    print(f"base de démonstration {res['base']} prête : référentiel {res['referentiel']}, "
          f"données journalières {res['journalier']}, configuration provisoire "
          f"{res['configuration']}")
    print("Pour l'utiliser, définir avant de lancer l'API :")
    print(f"  AGENT_TAG_DATABASE_URL={res['url_application']}")
    return 0


def cmd_simuler_reimport(conf: settings.Settings, args) -> int:
    if conf.usage != "TEST":
        raise settings.ConfigurationInvalide("simulation réservée à l'usage TEST")
    with db.connecter(conf.database_url) as conn:
        demarrage.verifier(conn, conf.usage)
    rap = demo.simuler_reimport(conf.database_url, args.auteur, args.ouvrier,
                                conf.dossier_archives, conf.dossier_archives / "simulations")
    print(rap.en_texte())
    return 0 if rap.statut in (r.APPLIQUE, r.DEJA_IMPORTE) else 2


def cmd_verifier_integrite(conf: settings.Settings, _args) -> int:
    with db.connecter(conf.database_url) as conn:
        violations = integrite.verifier(conn)
    if not violations:
        print(f"OK — {len(integrite.CONTROLES)} invariants vérifiés, aucune violation")
        return 0
    for nom, lignes in violations.items():
        print(f"VIOLATION {nom} : {lignes[:20]}")
    return 3


def _console_robuste() -> None:
    """Sous Windows, une sortie redirigée peut utiliser cp1252 : les caractères non
    représentables (≥, →…) sont remplacés au lieu de faire échouer la commande."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _console_robuste()
    parser = argparse.ArgumentParser(prog="agent_tag.cli")
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("migrer")
    p_env = sous.add_parser("init-env")
    p_env.add_argument("--libelle", required=True)
    p_env.add_argument("--fuseau", default=None)
    sous.add_parser("verifier")
    p_user = sous.add_parser("creer-utilisateur")
    p_user.add_argument("--identifiant", required=True)
    p_user.add_argument("--nom", required=True)
    p_user.add_argument("--role", required=True)
    p_imp = sous.add_parser("importer-referentiel")
    p_imp.add_argument("fichier")
    p_imp.add_argument("--auteur", required=True)
    p_imp.add_argument("--rapport-json", default=None)
    p_jour = sous.add_parser("importer-journalier")
    p_jour.add_argument("fichier")
    p_jour.add_argument("--auteur", required=True)
    p_jour.add_argument("--attester-absences", action="store_true",
                        help="atteste que la feuille Absences est complète pour les dates et "
                             "chaînes couvertes par les affectations du fichier (D18, choix TEST)")
    p_jour.add_argument("--rapport-json", default=None)
    p_dispo = sous.add_parser("disponibilite")
    p_dispo.add_argument("--date", required=True)
    p_dispo.add_argument("--ouvrier", nargs="*", default=None)
    p_dispo.add_argument("--chaine", default=None)
    p_dispo.add_argument("--instant", default=None,
                         help="relire l'état des données à cet instant (ISO 8601, avec fuseau)")
    p_dispo.add_argument("--etat", default=None,
                         choices=["DISPONIBLE", "ABSENT", "INDETERMINE", "INCONNU"])
    p_dispo.add_argument("--json", default=None)
    p_all = sous.add_parser("allouer")
    p_all.add_argument("--date", required=True)
    p_all.add_argument("--chaine", required=True)
    p_all.add_argument("--profil", required=True, choices=sorted(allocation.PROFILS_PROVISOIRES),
                       help="jeu de paramètres PROVISOIRES de test (aucun n'est validé)")
    p_all.add_argument("--candidats", type=int, default=3)
    p_all.add_argument("--detail", action="store_true")
    p_all.add_argument("--json", default=None)
    p_cfg = sous.add_parser("config-provisoire")
    p_cfg.add_argument("--profil", required=True, choices=sorted(allocation.PROFILS_PROVISOIRES))
    p_cfg.add_argument("--auteur", required=True)
    p_demo = sous.add_parser("initialiser-demo")
    p_demo.add_argument("--base", default="agent_tag_demo")
    p_demo.add_argument("--profil", default="A", choices=sorted(allocation.PROFILS_PROVISOIRES))
    sous.add_parser("verifier-integrite")
    p_sim = sous.add_parser("simuler-reimport")
    p_sim.add_argument("--ouvrier", required=True)
    p_sim.add_argument("--auteur", default="demo.responsable")
    args = parser.parse_args(argv)

    actions = {
        "migrer": cmd_migrer,
        "init-env": cmd_init_env,
        "verifier": cmd_verifier,
        "creer-utilisateur": cmd_creer_utilisateur,
        "importer-referentiel": cmd_importer_referentiel,
        "importer-journalier": cmd_importer_journalier,
        "disponibilite": cmd_disponibilite,
        "allouer": cmd_allouer,
        "config-provisoire": cmd_config_provisoire,
        "initialiser-demo": cmd_initialiser_demo,
        "verifier-integrite": cmd_verifier_integrite,
        "simuler-reimport": cmd_simuler_reimport,
    }
    try:
        conf = settings.charger()
        return actions[args.commande](conf, args)
    except (
        settings.ConfigurationInvalide,
        demarrage.DemarrageRefuse,
        migrations.ErreurMigration,
        import_referentiel.ImportImpossible,
        psycopg.Error,
        ValueError,   # date ou instant mal formés, chaîne inconnue
        allocation.ConfigurationInvalide,
        RefusMetier,
    ) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
