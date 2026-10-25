"""Opérations transactionnelles de l'allocation (Phase 4 B7, 4.1 à 4.3).

Principes :
- une proposition n'est JAMAIS une affectation ; seul ACCEPTER, décision humaine explicite,
  crée un remplacement (replacement_assignment) ;
- ordre global des verrous : S_D (date) → S3 (run) → S2 (date, chaîne donneuse) → S1 (date,
  ouvrier), chaque niveau trié (I25) ; verrous consultatifs de transaction ;
- calcul en deux phases (R-SNAP) : lecture d'un instantané en lecture seule, puis validation sous
  verrous (version du run, version des données de la date, créneaux) et écriture ; en cas de
  conflit, le calcul est abandonné sans écriture et relancé (3 essais) ;
- toute opération s'exécute en une transaction : en cas d'échec, rien n'est écrit.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date

import psycopg

from agent_tag.domain import allocation as a
from agent_tag.persistence import disponibilite, instantane
from agent_tag.services import configuration

NS_DATE, NS_CHAINE, NS_RUN, NS_OUVRIER = 10, 20, 30, 40
ROLES_DECISION_TEST = {"TEST_TOUS_DROITS"}   # D14 ouverte : rôle provisoire de TEST
ESSAIS_CALCUL = 3
STATUTS_VIVANTS = ("BLOQUE", "A_TRAITER", "EN_ATTENTE")


class RefusMetier(Exception):
    """Opération refusée par une règle métier ou un contrôle de cohérence (aucune écriture)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code} : {message}")
        self.code, self.message = code, message


class Interdit(RefusMetier):
    pass


class NonTrouve(RefusMetier):
    pass


class _Conflit(Exception):
    """Conflit de concurrence pendant la validation d'un calcul : nouvel essai."""


# --- Outils -----------------------------------------------------------------------------------

def _verrous(conn, *, dates=(), runs=(), chaines=(), ouvriers=()) -> None:
    """Ordre global : S_D → S3 → S2 → S1, chaque niveau trié."""
    for d in sorted(set(dates)):
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (NS_DATE, d.toordinal()))
    for r in sorted(set(runs)):
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (NS_RUN, r))
    for d, ch in sorted(set(chaines)):
        conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (NS_CHAINE, f"{d}|{ch}"))
    for d, o in sorted(set(ouvriers)):
        conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (NS_OUVRIER, f"{d}|{o}"))


def _acteur(conn, identifiant: str | None):
    if not identifiant:
        raise Interdit("UTILISATEUR_REQUIS", "utilisateur non indiqué")
    ligne = conn.execute("SELECT id, role, actif FROM app_user WHERE identifiant = %s",
                         (identifiant,)).fetchone()
    if ligne is None or not ligne[2]:
        raise Interdit("UTILISATEUR_INCONNU", f"utilisateur inconnu ou inactif : {identifiant}")
    return ligne[0], ligne[1]


def _usage(conn) -> str:
    ligne = conn.execute("SELECT usage FROM environment").fetchone()
    if not ligne:
        raise RefusMetier("ENVIRONNEMENT", "environnement non initialisé")
    return ligne[0]


def _autoriser_decision(conn, identifiant: str, version_config: int):
    """Une décision n'est permise que si la configuration et l'utilisateur l'autorisent :
    - TEST : rôle de test autorisé ; la décision est marquée TEST (non valable en réel) ;
    - EXPLOITATION : refusée tant que la configuration n'est pas entièrement validée et que les
      rôles autorisés ne sont pas définis (D3, D4, D14)."""
    id_acteur, role = _acteur(conn, identifiant)
    usage = _usage(conn)
    cfg = configuration.charger(conn, version_config)
    if usage != "TEST":
        if not cfg.validee:
            raise RefusMetier("CONFIGURATION_NON_VALIDEE",
                              "paramètres non validés (D3, D4…) : aucune décision réelle possible")
        raise Interdit("ROLES_NON_DEFINIS", "aucun rôle autorisé à décider n'est défini (D14)")
    if role not in ROLES_DECISION_TEST:
        raise Interdit("ROLE_NON_AUTORISE", f"le rôle {role} ne peut pas décider")
    return id_acteur, usage, cfg


def _version_donnees(conn, jour: date) -> int:
    ligne = conn.execute("SELECT version FROM data_version WHERE date = %s", (jour,)).fetchone()
    return ligne[0] if ligne else 0


def _run(conn, id_run: int, verrou=False):
    ligne = conn.execute(
        "SELECT id, date_run, id_chaine_cible, version_config, statut, version "
        "FROM allocation_run WHERE id = %s" + (" FOR UPDATE" if verrou else ""),
        (id_run,)).fetchone()
    if ligne is None:
        raise NonTrouve("RUN_INCONNU", f"calcul {id_run} inconnu")
    return dict(zip(("id", "date", "chaine", "version_config", "statut", "version"), ligne))


def _derniere_iteration(conn, id_run: int) -> int:
    return conn.execute("SELECT coalesce(max(numero), 0) FROM allocation_iteration "
                        "WHERE id_run = %s", (id_run,)).fetchone()[0]


def _recalcul_requis(conn, id_run: int, cause: str, id_decision=None, id_lot=None,
                     motif="RECALCUL") -> None:
    """R-RECALC : annule les propositions actives des besoins non tranchés, ferme leurs créneaux,
    remet les besoins EN_ATTENTE à A_TRAITER, et passe le run à A_RECALCULER (I23)."""
    actives = conn.execute(
        "SELECT p.id FROM proposal p WHERE p.id_run = %s AND p.statut = 'ACTIVE'",
        (id_run,)).fetchall()
    for (id_p,) in actives:
        conn.execute(
            "UPDATE proposal SET statut = 'ANNULEE', motif_annulation = %s, "
            "id_decision_cause = %s, id_lot_cause = %s, date_fin = now() WHERE id = %s",
            (motif, id_decision, id_lot, id_p))
        conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                     "motif_fermeture = %s WHERE id_proposal = %s AND statut = 'COURANT'",
                     (motif, id_p))
    conn.execute("UPDATE replacement_request SET statut_cycle = 'A_TRAITER', cause_statut = %s "
                 "WHERE id_run = %s AND statut_cycle = 'EN_ATTENTE'", (cause, id_run))
    conn.execute("UPDATE allocation_run SET statut = 'A_RECALCULER', cause_statut = %s, "
                 "version = version + 1 WHERE id = %s", (cause, id_run))


def _restants_actuels(conn, jour, chaine, poste, id_proposal_exclue=None):
    """Présents DISPONIBLES sur (chaîne, poste) et engagements courants (tous runs), hors la ou
    les propositions considérées (identifiant ou liste). Retourne (présents, engagés sur le
    poste, engagés depuis la chaîne)."""
    exclues = ([] if id_proposal_exclue is None else list(id_proposal_exclue)
               if isinstance(id_proposal_exclue, (list, tuple, set)) else [id_proposal_exclue])
    etats = disponibilite.lire(conn, jour, chaine=None)
    ids = [d.id_affectation for d in etats if d.etat == "DISPONIBLE" and d.id_affectation]
    presents = 0
    if ids:
        presents = conn.execute(
            "SELECT count(*) FROM daily_assignment WHERE id = ANY(%s) AND id_chaine = %s "
            "AND code_poste = %s", (ids, chaine, poste)).fetchone()[0]
    poste_eng, chaine_eng = conn.execute(
        "SELECT count(*) FILTER (WHERE e.poste_quitte = %s), count(*) "
        "FROM worker_day_slot s JOIN proposal p ON p.id = s.id_proposal "
        "JOIN candidate_evaluation e ON e.id = p.id_evaluation "
        "WHERE s.date = %s AND s.statut = 'COURANT' AND e.chaine_donneuse = %s "
        "AND NOT (s.id_proposal = ANY(%s))",
        (poste, jour, chaine, exclues)).fetchone()
    return presents, poste_eng, chaine_eng


def _decision(conn, *, id_besoin, id_run, type_, auteur, usage, cfg_validee, numero=None,
              id_proposal=None, id_remplacement=None, exclure=None, motif=None,
              id_proposal_substituee=None) -> int:
    return conn.execute(
        "INSERT INTO allocation_decision (id_besoin, id_run, numero, type, id_proposal, "
        "id_remplacement, exclure_ouvrier, motif, auteur, usage_environnement, "
        "configuration_validee, id_proposal_substituee) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (id_besoin, id_run, numero, type_, id_proposal, id_remplacement, exclure, motif, auteur,
         usage, cfg_validee, id_proposal_substituee)).fetchone()[0]


# --- Lancement et calcul ----------------------------------------------------------------------

def lancer(url: str, jour: date, chaine: str, identifiant: str) -> int:
    """Crée un run (I10) puis calcule la première itération. Retourne l'identifiant du run."""
    with psycopg.connect(url) as conn:
        id_acteur, _ = _acteur(conn, identifiant)
        cfg = configuration.active(conn)
        if cfg is None:
            raise RefusMetier("CONFIGURATION_ABSENTE", "aucune configuration active")
        if not conn.execute("SELECT 1 FROM production_line WHERE id_chaine = %s",
                            (chaine,)).fetchone():
            raise NonTrouve("CHAINE_INCONNUE", f"chaîne {chaine} inconnue")
        etats = dict(conn.execute(
            "SELECT type_donnee, etat FROM batch_coverage WHERE date = %s AND id_chaine = %s "
            "AND statut = 'COURANT' AND source = 'IMPORT'", (jour, chaine)))
        if etats.get("AFFECTATIONS") != "COMPLET" or etats.get("ABSENCES") != "COMPLET":
            raise RefusMetier(
                "DONNEES_INCOMPLETES",
                f"{chaine} le {jour.isoformat()} : affectations "
                f"{etats.get('AFFECTATIONS', 'INCONNUES')}, absences "
                f"{etats.get('ABSENCES', 'INCONNUES')} — calcul impossible (I10)")
        try:
            id_run = conn.execute(
                "INSERT INTO allocation_run (date_run, id_chaine_cible, version_config, statut, "
                "cause_statut, cree_par) VALUES (%s, %s, %s, 'A_RECALCULER', 'INITIAL', %s) "
                "RETURNING id", (jour, chaine, cfg.version, id_acteur)).fetchone()[0]
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            existant = conn.execute(
                "SELECT id FROM allocation_run WHERE date_run = %s AND id_chaine_cible = %s "
                "AND statut <> 'CLOS'", (jour, chaine)).fetchone()
            raise RefusMetier("RUN_DEJA_OUVERT",
                              f"un calcul est déjà ouvert pour {chaine} le {jour.isoformat()} "
                              f"(run {existant[0] if existant else '?'})") from None
    calculer(url, id_run, "INITIAL")
    return id_run


def recalculer(url: str, id_run: int, identifiant: str) -> None:
    """Relance demandée par un utilisateur : si le run est OUVERT, R-RECALC puis calcul."""
    with psycopg.connect(url) as conn:
        _acteur(conn, identifiant)
        run = _run(conn, id_run)
        _verrous(conn, runs=[id_run], ouvriers=[
            (run["date"], o) for (o,) in conn.execute(
                "SELECT id_ouvrier FROM proposal WHERE id_run = %s AND statut = 'ACTIVE'",
                (id_run,))])
        run = _run(conn, id_run, verrou=True)
        if run["statut"] == "CLOS":
            raise RefusMetier("RUN_CLOS", "calcul clos")
        if run["statut"] == "OUVERT":
            _recalcul_requis(conn, id_run, "DEMANDE_UTILISATEUR")
        conn.commit()
    calculer(url, id_run, "DEMANDE_UTILISATEUR")


def calculer(url: str, id_run: int, declencheur: str) -> int:
    """Calcule une nouvelle itération d'un run A_RECALCULER. Retourne son numéro."""
    for _ in range(ESSAIS_CALCUL):
        try:
            return _calculer_une_fois(url, id_run, declencheur)
        except (_Conflit, psycopg.errors.UniqueViolation, psycopg.errors.SerializationFailure):
            continue
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE allocation_run SET cause_statut = 'CALCUL_EN_ECHEC', "
                     "version = version + 1 WHERE id = %s AND statut = 'A_RECALCULER'", (id_run,))
        conn.commit()
    raise RefusMetier("CALCUL_EN_ECHEC",
                      f"conflits répétés pendant le calcul du run {id_run} : relancer le calcul")


def _calculer_une_fois(url: str, id_run: int, declencheur: str) -> int:
    # Phase 1 : instantané cohérent, en lecture seule.
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            run = _run(conn, id_run)
            if run["statut"] != "A_RECALCULER":
                raise RefusMetier("RUN_NON_A_RECALCULER",
                                  f"le run {id_run} est {run['statut']} : rien à calculer")
            cfg = configuration.charger(conn, run["version_config"])
            inst = instantane.lire_dans_transaction(conn, run["date"])
            version_donnees = _version_donnees(conn, run["date"])
            creneaux = frozenset(o for (o,) in conn.execute(
                "SELECT id_ouvrier FROM worker_day_slot WHERE date = %s AND statut = 'COURANT'",
                (run["date"],)))
            interdites = frozenset(c for (c,) in conn.execute(
                "SELECT id_chaine_cible FROM allocation_run WHERE date_run = %s "
                "AND statut <> 'CLOS' AND id <> %s", (run["date"], id_run)))
            besoins_existants = {o: (i, s, c) for i, o, s, c in conn.execute(
                "SELECT id, id_ouvrier_absent, statut_cycle, cause_statut "
                "FROM replacement_request WHERE id_run = %s", (id_run,))}
            # I11 : une journée d'absence déjà traitée dans un autre run n'est pas recréée.
            traites_ailleurs = frozenset(o for (o,) in conn.execute(
                "SELECT id_ouvrier_absent FROM replacement_request WHERE date = %s "
                "AND id_run <> %s AND statut_cycle IN ('BLOQUE', 'A_TRAITER', 'EN_ATTENTE', "
                "'POURVU')", (run["date"], id_run)))
            exclusions = {}
            for absent, ouvrier in conn.execute(
                    "SELECT r.id_ouvrier_absent, p.id_ouvrier FROM allocation_decision d "
                    "JOIN replacement_request r ON r.id = d.id_besoin "
                    "JOIN proposal p ON p.id = d.id_proposal "
                    "WHERE d.id_run = %s AND d.type = 'REFUSER' "
                    "UNION SELECT r.id_ouvrier_absent, ra.id_ouvrier FROM allocation_decision d "
                    "JOIN replacement_request r ON r.id = d.id_besoin "
                    "JOIN replacement_assignment ra ON ra.id = d.id_remplacement "
                    "WHERE d.id_run = %s AND d.type = 'ANNULER_REMPLACEMENT' "
                    "AND d.exclure_ouvrier", (id_run, id_run)):
                exclusions.setdefault(absent, set()).add(ouvrier)

    inst.engages = creneaux
    inst.chaines_interdites = interdites if cfg.domaine.regle_cascade else frozenset()
    inst.exclusions = {k: frozenset(v) for k, v in exclusions.items()}
    inst.besoins_exclus = traites_ailleurs | frozenset(
        o for o, (_, s, c) in besoins_existants.items()
        if s == "POURVU" or (s == "NON_POURVU" and (c or "").startswith("DECISION")))
    res = a.allouer(inst, cfg.domaine, run["chaine"])

    # Phase 2 : validation et écriture sous verrous.
    proposes = [(b, b.proposition) for b in res.besoins if b.proposition]
    with psycopg.connect(url) as conn:
        _verrous(conn, runs=[id_run],
                 chaines=[(run["date"], p.chaine_donneuse) for _, p in proposes],
                 ouvriers=[(run["date"], p.id_ouvrier) for _, p in proposes])
        actuel = _run(conn, id_run, verrou=True)
        if actuel["statut"] != "A_RECALCULER" or actuel["version"] != run["version"]:
            raise _Conflit()
        if _version_donnees(conn, run["date"]) != version_donnees:
            raise _Conflit()
        if frozenset(o for (o,) in conn.execute(
                "SELECT id_ouvrier FROM worker_day_slot WHERE date = %s AND statut = 'COURANT'",
                (run["date"],))) != creneaux:
            raise _Conflit()

        numero = _derniere_iteration(conn, id_run) + 1
        conn.execute(
            "INSERT INTO allocation_iteration (id_run, numero, declencheur, instant_lecture, "
            "version_donnees, nb_besoins_consideres, couverture_sequentielle, "
            "couverture_maximale, alerte_combinaison, combinaison_maximale) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (id_run, numero, declencheur, inst.lecture, version_donnees, res.besoins_consideres,
             res.couverture_sequentielle, res.couverture_maximale, res.alerte_combinaison,
             json.dumps(res.combinaison_maximale)))

        vus = set()
        for b in res.besoins:
            vus.add(b.id_ouvrier_absent)
            if b.statut == a.DEJA_TRAITE:
                continue   # POURVU / décidé dans ce run, ou traité dans un autre run (I11)
            statut, cause = {
                a.PROPOSITION: ("EN_ATTENTE", None),
                a.AUCUN_CANDIDAT: ("NON_POURVU", f"AUCUN_CANDIDAT : {b.cause}"),
                a.BLOQUE: ("BLOQUE", b.cause),
            }[b.statut]
            j = inst.jour[b.id_ouvrier_absent]
            id_exigence = conn.execute(
                "SELECT id FROM position_requirement WHERE id_chaine = %s AND code_poste = %s "
                "AND statut = 'ACTIVE'", (b.chaine, b.poste)).fetchone()
            existant = besoins_existants.get(b.id_ouvrier_absent)
            if existant is None:
                id_besoin = conn.execute(
                    "INSERT INTO replacement_request (id_run, date, id_chaine_cible, "
                    "id_ouvrier_absent, id_affectation_source, id_absence_source, code_poste, "
                    "id_exigence, code_competence_requise, code_niveau_min, est_critique, "
                    "rang_traitement, statut_cycle, cause_statut) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (id_run, run["date"], run["chaine"], b.id_ouvrier_absent, j.id_affectation,
                     j.id_absence, b.poste, id_exigence[0] if id_exigence else None,
                     b.competence, b.code_niveau_min, b.critique, b.rang_traitement, statut,
                     cause)).fetchone()[0]
            else:
                id_besoin = existant[0]
                conn.execute("UPDATE replacement_request SET statut_cycle = %s, cause_statut = %s,"
                             " rang_traitement = %s WHERE id = %s",
                             (statut, cause, b.rang_traitement, id_besoin))
            ids_eval = {}
            for e in b.evaluations:
                details = {k: v for k, v in asdict(e).items() if k != "explication"}
                ids_eval[e.id_ouvrier] = conn.execute(
                    "INSERT INTO candidate_evaluation (id_run, numero, id_besoin, id_ouvrier, "
                    "eligible, premier_echec, risque, rang, ex_aequo, chaine_donneuse, "
                    "poste_quitte, restants, explication, details) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (id_run, numero, id_besoin, e.id_ouvrier, e.eligible, e.premier_echec,
                     e.risque, e.rang, e.ex_aequo, e.chaine_donneuse, e.poste_quitte, e.restants,
                     e.explication, json.dumps(details, default=str))).fetchone()[0]
            if b.proposition:
                id_p = conn.execute(
                    "INSERT INTO proposal (id_run, numero, id_evaluation, id_besoin, id_ouvrier, "
                    "date, id_ouvrier_absent) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (id_run, numero, ids_eval[b.proposition.id_ouvrier], id_besoin,
                     b.proposition.id_ouvrier, run["date"], b.id_ouvrier_absent)).fetchone()[0]
                conn.execute("INSERT INTO worker_day_slot (date, id_ouvrier, type, id_proposal) "
                             "VALUES (%s, %s, 'RESERVE', %s)",
                             (run["date"], b.proposition.id_ouvrier, id_p))

        # Besoins dont l'absence n'est plus confirmée par les données courantes.
        for absent, (id_b, statut, cause) in besoins_existants.items():
            if absent not in vus and statut in (*STATUTS_VIVANTS, "NON_POURVU") \
                    and not (cause or "").startswith("DECISION"):
                conn.execute("UPDATE replacement_request SET statut_cycle = 'NON_POURVU', "
                             "cause_statut = 'ABSENCE_NON_CONFIRMEE : plus de besoin dans les "
                             "données courantes' WHERE id = %s", (id_b,))

        conn.execute("UPDATE allocation_run SET statut = 'OUVERT', cause_statut = NULL, "
                     "version = version + 1 WHERE id = %s", (id_run,))
        conn.commit()
        return numero


# --- Décisions --------------------------------------------------------------------------------

def _proposition(conn, id_proposal: int):
    ligne = conn.execute(
        "SELECT p.id, p.id_run, p.numero, p.id_besoin, p.id_ouvrier, p.date, p.statut, "
        "e.chaine_donneuse, e.poste_quitte FROM proposal p "
        "JOIN candidate_evaluation e ON e.id = p.id_evaluation WHERE p.id = %s",
        (id_proposal,)).fetchone()
    if ligne is None:
        raise NonTrouve("PROPOSITION_INCONNUE", f"proposition {id_proposal} inconnue")
    return dict(zip(("id", "id_run", "numero", "id_besoin", "id_ouvrier", "date", "statut",
                     "chaine", "poste"), ligne))


def accepter(url: str, id_proposal: int, identifiant: str, motif: str | None = None) -> int:
    """ACCEPTER : décision humaine explicite. Retourne l'identifiant du remplacement créé."""
    with psycopg.connect(url) as conn:
        p = _proposition(conn, id_proposal)
        _verrous(conn, runs=[p["id_run"]], chaines=[(p["date"], p["chaine"])],
                 ouvriers=[(p["date"], p["id_ouvrier"])])
        p = _proposition(conn, id_proposal)
        run = _run(conn, p["id_run"], verrou=True)
        if p["statut"] != "ACTIVE":
            raise RefusMetier("PROPOSITION_NON_ACTIVE",
                              f"la proposition {id_proposal} est {p['statut']}")
        if run["statut"] != "OUVERT":
            raise RefusMetier("RUN_NON_OUVERT", f"le calcul est {run['statut']} : relancer le calcul")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        if p["numero"] != _derniere_iteration(conn, run["id"]):
            raise RefusMetier("PROPOSITION_PERIMEE", "proposition d'une itération antérieure")
        version = conn.execute("SELECT version_donnees FROM allocation_iteration "
                               "WHERE id_run = %s AND numero = %s",
                               (run["id"], p["numero"])).fetchone()[0]
        if _version_donnees(conn, run["date"]) != version:
            raise RefusMetier("DONNEES_MODIFIEES",
                              "les données de la date ont changé depuis le calcul : recalculer")
        presents, poste_eng, chaine_eng = _restants_actuels(conn, p["date"], p["chaine"],
                                                            p["poste"], id_proposal)
        restants = presents - poste_eng - 1
        if restants < cfg.domaine.m_bloc:
            raise RefusMetier("P1", f"le poste quitté ({p['chaine']}, {p['poste']}) garderait "
                                    f"{restants} titulaire(s) < {cfg.domaine.m_bloc}")
        if chaine_eng + 1 > cfg.domaine.p3:
            raise RefusMetier("P3", f"plafond de transferts depuis {p['chaine']} atteint "
                                    f"({chaine_eng} / {cfg.domaine.p3})")

        id_dec = _decision(conn, id_besoin=p["id_besoin"], id_run=run["id"], type_="ACCEPTER",
                           auteur=id_acteur, usage=usage, cfg_validee=cfg.validee,
                           numero=p["numero"], id_proposal=id_proposal, motif=motif)
        absent = conn.execute("SELECT id_ouvrier_absent FROM replacement_request WHERE id = %s",
                              (p["id_besoin"],)).fetchone()[0]
        id_rempl = conn.execute(
            "INSERT INTO replacement_assignment (id_besoin, id_proposal, id_ouvrier, date, "
            "id_ouvrier_absent, id_decision_creation) VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (p["id_besoin"], id_proposal, p["id_ouvrier"], p["date"], absent, id_dec)
        ).fetchone()[0]
        conn.execute("UPDATE proposal SET statut = 'ACCEPTEE', date_acceptation = now(), "
                     "date_fin = now() WHERE id = %s", (id_proposal,))
        conn.execute("UPDATE worker_day_slot SET type = 'ENGAGE', id_remplacement = %s, "
                     "date_conversion = now() WHERE id_proposal = %s AND statut = 'COURANT'",
                     (id_rempl, id_proposal))
        conn.execute("UPDATE replacement_request SET statut_cycle = 'POURVU', "
                     "cause_statut = NULL WHERE id = %s", (p["id_besoin"],))
        conn.execute("UPDATE allocation_run SET version = version + 1 WHERE id = %s", (run["id"],))
        conn.commit()
        return id_rempl


def _ouvriers_reserves(conn, id_run):
    return [(d, o) for d, o in conn.execute(
        "SELECT date, id_ouvrier FROM proposal WHERE id_run = %s AND statut = 'ACTIVE'",
        (id_run,))]


def refuser(url: str, id_proposal: int, identifiant: str, motif: str) -> None:
    """REFUSER : l'ouvrier est exclu pour ce besoin (D8, proposition par défaut), puis recalcul."""
    with psycopg.connect(url) as conn:
        p = _proposition(conn, id_proposal)
        _verrous(conn, runs=[p["id_run"]], ouvriers=_ouvriers_reserves(conn, p["id_run"]))
        p = _proposition(conn, id_proposal)
        run = _run(conn, p["id_run"], verrou=True)
        if p["statut"] != "ACTIVE":
            raise RefusMetier("PROPOSITION_NON_ACTIVE",
                              f"la proposition {id_proposal} est {p['statut']}")
        if run["statut"] != "OUVERT":
            raise RefusMetier("RUN_NON_OUVERT", f"le calcul est {run['statut']}")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "un refus exige un motif")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        id_dec = _decision(conn, id_besoin=p["id_besoin"], id_run=run["id"], type_="REFUSER",
                           auteur=id_acteur, usage=usage, cfg_validee=cfg.validee,
                           numero=p["numero"], id_proposal=id_proposal, motif=motif)
        conn.execute("UPDATE proposal SET statut = 'REFUSEE', date_fin = now() WHERE id = %s",
                     (id_proposal,))
        conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                     "motif_fermeture = 'REFUS' WHERE id_proposal = %s AND statut = 'COURANT'",
                     (id_proposal,))
        conn.execute("UPDATE replacement_request SET statut_cycle = 'A_TRAITER', "
                     "cause_statut = 'REFUS' WHERE id = %s", (p["id_besoin"],))
        _recalcul_requis(conn, run["id"], "DECISION", id_decision=id_dec)
        conn.commit()
    calculer(url, p["id_run"], "REFUS")


def laisser_non_pourvu(url: str, id_besoin: int, identifiant: str, motif: str) -> None:
    with psycopg.connect(url) as conn:
        id_run = conn.execute("SELECT id_run FROM replacement_request WHERE id = %s",
                              (id_besoin,)).fetchone()
        if id_run is None:
            raise NonTrouve("BESOIN_INCONNU", f"besoin {id_besoin} inconnu")
        _verrous(conn, runs=[id_run[0]], ouvriers=_ouvriers_reserves(conn, id_run[0]))
        run = _run(conn, id_run[0], verrou=True)
        statut = conn.execute("SELECT statut_cycle FROM replacement_request WHERE id = %s",
                              (id_besoin,)).fetchone()[0]
        if run["statut"] != "OUVERT" or statut not in ("A_TRAITER", "EN_ATTENTE", "NON_POURVU"):
            raise RefusMetier("TRANSITION_INTERDITE",
                              f"besoin {statut} dans un calcul {run['statut']}")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "un motif est requis")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        active = conn.execute("SELECT id FROM proposal WHERE id_besoin = %s AND statut = 'ACTIVE'",
                              (id_besoin,)).fetchone()
        id_dec = _decision(conn, id_besoin=id_besoin, id_run=run["id"],
                           type_="LAISSER_NON_POURVU", auteur=id_acteur, usage=usage,
                           cfg_validee=cfg.validee, id_proposal=active[0] if active else None,
                           motif=motif)
        if active:
            conn.execute("UPDATE proposal SET statut = 'ANNULEE', motif_annulation = 'NON_POURVU',"
                         " id_decision_cause = %s, date_fin = now() WHERE id = %s",
                         (id_dec, active[0]))
            conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                         "motif_fermeture = 'NON_POURVU' WHERE id_proposal = %s "
                         "AND statut = 'COURANT'", (active[0],))
        conn.execute("UPDATE replacement_request SET statut_cycle = 'NON_POURVU', "
                     "cause_statut = %s WHERE id = %s",
                     (f"DECISION : laissé non pourvu — {motif}", id_besoin))
        _recalcul_requis(conn, run["id"], "DECISION", id_decision=id_dec)
        conn.commit()
    calculer(url, run["id"], "NON_POURVU")


def _remplacement(conn, id_rempl: int):
    ligne = conn.execute(
        "SELECT ra.id, ra.id_besoin, ra.id_ouvrier, ra.date, ra.statut, ra.statut_revue, "
        "r.id_run, e.chaine_donneuse, e.poste_quitte, ra.id_proposal, ra.id_ouvrier_absent "
        "FROM replacement_assignment ra JOIN replacement_request r ON r.id = ra.id_besoin "
        "JOIN proposal p ON p.id = ra.id_proposal "
        "JOIN candidate_evaluation e ON e.id = p.id_evaluation WHERE ra.id = %s",
        (id_rempl,)).fetchone()
    if ligne is None:
        raise NonTrouve("REMPLACEMENT_INCONNU", f"remplacement {id_rempl} inconnu")
    return dict(zip(("id", "id_besoin", "id_ouvrier", "date", "statut", "revue", "id_run",
                     "chaine", "poste", "id_proposal", "absent"), ligne))


def annuler_remplacement(url: str, id_rempl: int, identifiant: str, motif: str,
                         exclure: bool) -> None:
    with psycopg.connect(url) as conn:
        ra = _remplacement(conn, id_rempl)
        _verrous(conn, runs=[ra["id_run"]], chaines=[(ra["date"], ra["chaine"])],
                 ouvriers=[(ra["date"], ra["id_ouvrier"])] + _ouvriers_reserves(conn, ra["id_run"]))
        ra = _remplacement(conn, id_rempl)
        run = _run(conn, ra["id_run"], verrou=True)
        if ra["statut"] != "ACTIF":
            raise RefusMetier("REMPLACEMENT_NON_ACTIF", f"le remplacement est {ra['statut']}")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "une annulation exige un motif")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        id_dec = _decision(conn, id_besoin=ra["id_besoin"], id_run=run["id"],
                           type_="ANNULER_REMPLACEMENT", auteur=id_acteur, usage=usage,
                           cfg_validee=cfg.validee, id_remplacement=id_rempl,
                           exclure=bool(exclure), motif=motif)
        conn.execute("UPDATE replacement_assignment SET statut = 'ANNULE', date_annulation = now()"
                     " WHERE id = %s", (id_rempl,))
        conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                     "motif_fermeture = 'ANNULATION' WHERE id_proposal = %s AND statut = 'COURANT'",
                     (ra["id_proposal"],))
        if run["statut"] == "CLOS":
            conn.execute("UPDATE replacement_request SET statut_cycle = 'NON_POURVU', "
                         "cause_statut = 'DECISION : remplacement annulé (calcul clos)' "
                         "WHERE id = %s", (ra["id_besoin"],))
            relancer = False
        else:
            conn.execute("UPDATE replacement_request SET statut_cycle = 'A_TRAITER', "
                         "cause_statut = 'REMPLACEMENT_ANNULE' WHERE id = %s", (ra["id_besoin"],))
            if run["statut"] == "OUVERT":
                _recalcul_requis(conn, run["id"], "DECISION", id_decision=id_dec)
            relancer = True
        conn.commit()
    if relancer:
        calculer(url, ra["id_run"], "ANNULATION")


def confirmer_apres_reimport(url: str, id_rempl: int, identifiant: str, motif: str) -> None:
    """Confirmation d'un remplacement À REVOIR, seulement si une réévaluation sous verrous montre
    qu'il reste conforme aux données et aux seuils (4.3, IR 4) ; sinon : annuler."""
    with psycopg.connect(url) as conn:
        ra = _remplacement(conn, id_rempl)
        _verrous(conn, runs=[ra["id_run"]], chaines=[(ra["date"], ra["chaine"])],
                 ouvriers=[(ra["date"], ra["id_ouvrier"])])
        ra = _remplacement(conn, id_rempl)
        run = _run(conn, ra["id_run"], verrou=True)
        if ra["statut"] != "ACTIF" or ra["revue"] != "A_REVOIR":
            raise RefusMetier("TRANSITION_INTERDITE", "remplacement non actif ou non à revoir")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "un motif est requis")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        causes = _causes_revue(conn, ra, cfg.domaine)
        if causes:
            raise RefusMetier("NON_CONFORME",
                              "confirmation impossible : " + ", ".join(causes)
                              + " — annuler le remplacement ou corriger les données")
        _decision(conn, id_besoin=ra["id_besoin"], id_run=run["id"],
                  type_="CONFIRMER_APRES_REIMPORT", auteur=id_acteur, usage=usage,
                  cfg_validee=cfg.validee, id_remplacement=id_rempl, motif=motif)
        conn.execute("UPDATE replacement_assignment SET statut_revue = 'OK', cause_revue = NULL, "
                     "date_revue = now() WHERE id = %s", (id_rempl,))
        conn.commit()


def _causes_revue(conn, ra, cfg: a.Configuration) -> list[str]:
    etats = {d.id_ouvrier: d for d in disponibilite.lire(conn, ra["date"],
                                                         ouvriers=[ra["id_ouvrier"], ra["absent"]])}
    causes = []
    remp, absent = etats.get(ra["id_ouvrier"]), etats.get(ra["absent"])
    if remp is None or remp.etat != "DISPONIBLE":
        causes.append("DONNEES_INCONNUES" if remp and remp.etat == "INCONNU"
                      else "REMPLACANT_INDISPONIBLE")
    if absent is None or not absent.besoin_creable:
        causes.append("ABSENT_PRESENT")
    presents, poste_eng, chaine_eng = _restants_actuels(conn, ra["date"], ra["chaine"],
                                                        ra["poste"], ra["id_proposal"])
    if presents - poste_eng - 1 < cfg.m_bloc or chaine_eng + 1 > cfg.p3:
        causes.append("SEUIL_DONNEUR")
    return causes


def cloturer(url: str, id_run: int, identifiant: str, motif: str) -> None:
    with psycopg.connect(url) as conn:
        id_acteur, _ = _acteur(conn, identifiant)
        _verrous(conn, runs=[id_run], ouvriers=_ouvriers_reserves(conn, id_run))
        run = _run(conn, id_run, verrou=True)
        if run["statut"] == "CLOS":
            raise RefusMetier("RUN_CLOS", "calcul déjà clos")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "une clôture exige un motif")
        for (id_p,) in conn.execute("SELECT id FROM proposal WHERE id_run = %s "
                                    "AND statut = 'ACTIVE'", (id_run,)).fetchall():
            conn.execute("UPDATE proposal SET statut = 'ANNULEE', motif_annulation = 'CLOTURE', "
                         "date_fin = now() WHERE id = %s", (id_p,))
            conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                         "motif_fermeture = 'CLOTURE' WHERE id_proposal = %s "
                         "AND statut = 'COURANT'", (id_p,))
        conn.execute(
            "UPDATE replacement_request SET statut_cycle = 'NON_POURVU', cause_statut = CASE "
            "WHEN statut_cycle = 'BLOQUE' THEN 'CLOTURE : référentiel manquant — ' || "
            "coalesce(cause_statut, '') ELSE 'CLOTURE : sans décision' END "
            "WHERE id_run = %s AND statut_cycle IN ('BLOQUE', 'A_TRAITER', 'EN_ATTENTE')",
            (id_run,))
        conn.execute("UPDATE allocation_run SET statut = 'CLOS', cause_cloture = "
                     "'DECISION_RESPONSABLE', motif_cloture = %s, clos_par = %s, "
                     "date_cloture = now(), version = version + 1 WHERE id = %s",
                     (motif, id_acteur, id_run))
        conn.commit()


# --- Effet d'un import sur les calculs et remplacements (IMPACT_DONNEES, B8) -----------------

def impact_donnees(conn, dates, id_lot: int) -> dict:
    """Appelé DANS la transaction d'import, qui détient déjà les verrous S_D des dates.
    Runs non clos de ces dates → A_RECALCULER (propositions annulées, créneaux fermés) ;
    remplacements actifs → À REVOIR si les nouvelles données les rendent non conformes.
    Les remplacements ne sont jamais annulés automatiquement."""
    dates = list(dates)
    if not dates:
        return {"runs": [], "a_revoir": []}
    runs = [r for (r,) in conn.execute(
        "SELECT DISTINCT id FROM allocation_run WHERE date_run = ANY(%s) AND statut <> 'CLOS' "
        "UNION SELECT DISTINCT r.id_run FROM replacement_assignment ra "
        "JOIN replacement_request r ON r.id = ra.id_besoin "
        "WHERE ra.date = ANY(%s) AND ra.statut = 'ACTIF'", (dates, dates))]
    reserves = [(d, o) for d, o in conn.execute(
        "SELECT date, id_ouvrier FROM proposal WHERE date = ANY(%s) AND statut = 'ACTIVE'",
        (dates,))]
    _verrous(conn, runs=runs, ouvriers=reserves)
    touches = []
    for (id_run,) in conn.execute("SELECT id FROM allocation_run WHERE date_run = ANY(%s) "
                                  "AND statut <> 'CLOS' ORDER BY id", (dates,)).fetchall():
        _recalcul_requis(conn, id_run, "DONNEES_MODIFIEES", id_lot=id_lot,
                         motif="DONNEES_MODIFIEES")
        touches.append(id_run)
    a_revoir = []
    for (id_rempl,) in conn.execute("SELECT id FROM replacement_assignment WHERE date = ANY(%s) "
                                    "AND statut = 'ACTIF' ORDER BY id", (dates,)).fetchall():
        ra = _remplacement(conn, id_rempl)
        run = _run(conn, ra["id_run"])
        cfg = configuration.charger(conn, run["version_config"])
        causes = _causes_revue(conn, ra, cfg.domaine)
        if causes:
            conn.execute("UPDATE replacement_assignment SET statut_revue = 'A_REVOIR', "
                         "id_lot_revue = %s, cause_revue = %s, date_revue = now() WHERE id = %s",
                         (id_lot, ", ".join(causes), id_rempl))
            a_revoir.append(id_rempl)
    return {"runs": touches, "a_revoir": a_revoir}


# --- Choisir un autre candidat, rouvrir un besoin ----------------------------------------------

def choisir_autre(url: str, id_proposal: int, id_ouvrier: str, identifiant: str,
                  motif: str) -> int:
    """CHOISIR_AUTRE (3D.2 point 2, A2 F1–F8) : le responsable retient un autre candidat ÉLIGIBLE
    de la dernière itération à la place de la proposition courante (Pa). Si ce candidat est
    réservé par une autre proposition du MÊME calcul (Pc), celle-ci est annulée et son besoin
    recalculé. Tout se fait en une transaction ; en cas de refus, rien n'est modifié.
    Retourne l'identifiant du remplacement créé."""
    with psycopg.connect(url) as conn:
        pa = _proposition(conn, id_proposal)
        ev = conn.execute(
            "SELECT id, numero, eligible, chaine_donneuse, poste_quitte, explication, "
            "premier_echec FROM candidate_evaluation WHERE id_besoin = %s AND id_ouvrier = %s "
            "AND numero = %s", (pa["id_besoin"], id_ouvrier, pa["numero"])).fetchone()
        _verrous(conn, runs=[pa["id_run"]],
                 chaines=[(pa["date"], ev[3])] if ev and ev[3] else [],
                 ouvriers=[(pa["date"], pa["id_ouvrier"]), (pa["date"], id_ouvrier)])
        pa = _proposition(conn, id_proposal)
        run = _run(conn, pa["id_run"], verrou=True)
        if pa["statut"] != "ACTIVE":
            raise RefusMetier("PROPOSITION_NON_ACTIVE",
                              f"la proposition {id_proposal} est {pa['statut']}")
        if run["statut"] != "OUVERT":
            raise RefusMetier("RUN_NON_OUVERT", f"le calcul est {run['statut']} : recalculer")
        if id_ouvrier == pa["id_ouvrier"]:
            raise RefusMetier("MEME_CANDIDAT", "c'est le candidat déjà proposé : le confirmer")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "choisir un autre candidat exige un motif")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        if pa["numero"] != _derniere_iteration(conn, run["id"]):
            raise RefusMetier("PROPOSITION_PERIMEE", "proposition d'une itération antérieure")
        if ev is None:
            raise RefusMetier("CANDIDAT_NON_EVALUE",
                              f"{id_ouvrier} n'a pas été évalué pour ce besoin à la dernière "
                              "itération : recalculer")
        id_eval, numero, eligible, chaine, poste, explication, echec = ev
        if not eligible:
            raise RefusMetier("CANDIDAT_NON_ELIGIBLE",
                              f"{id_ouvrier} n'est pas admissible ({explication}) ; la dérogation "
                              "n'est pas autorisée (D5)")
        version = conn.execute("SELECT version_donnees FROM allocation_iteration "
                               "WHERE id_run = %s AND numero = %s",
                               (run["id"], numero)).fetchone()[0]
        if _version_donnees(conn, run["date"]) != version:
            raise RefusMetier("DONNEES_MODIFIEES",
                              "les données de la date ont changé depuis le calcul : recalculer")
        creneau = conn.execute(
            "SELECT s.type, p.id, p.id_run, p.id_besoin FROM worker_day_slot s "
            "JOIN proposal p ON p.id = s.id_proposal WHERE s.date = %s AND s.id_ouvrier = %s "
            "AND s.statut = 'COURANT'", (run["date"], id_ouvrier)).fetchone()
        pc = None
        if creneau:
            type_c, id_pc, run_pc, besoin_pc = creneau
            if type_c == "ENGAGE":
                raise RefusMetier("CANDIDAT_ENGAGE",
                                  f"{id_ouvrier} est déjà engagé dans un remplacement confirmé")
            if run_pc != run["id"]:
                raise RefusMetier("CANDIDAT_RESERVE_AILLEURS",
                                  f"{id_ouvrier} est réservé par un autre calcul (run {run_pc})")
            pc = (id_pc, besoin_pc)
        exclues = [id_proposal] + ([pc[0]] if pc else [])
        presents, poste_eng, chaine_eng = _restants_actuels(conn, run["date"], chaine, poste,
                                                            exclues)
        restants = presents - poste_eng - 1
        if restants < cfg.domaine.m_bloc:
            raise RefusMetier("P1", f"le poste quitté ({chaine}, {poste}) garderait {restants} "
                                    f"titulaire(s) < {cfg.domaine.m_bloc}")
        if chaine_eng + 1 > cfg.domaine.p3:
            raise RefusMetier("P3", f"plafond de transferts depuis {chaine} atteint "
                                    f"({chaine_eng} / {cfg.domaine.p3})")

        id_dec = _decision(conn, id_besoin=pa["id_besoin"], id_run=run["id"],
                           type_="CHOISIR_AUTRE", auteur=id_acteur, usage=usage,
                           cfg_validee=cfg.validee, numero=numero, motif=motif,
                           id_proposal_substituee=id_proposal)
        for id_p, motif_annulation in [(id_proposal, "SUBSTITUTION")] + (
                [(pc[0], "CANDIDAT_REPRIS")] if pc else []):
            conn.execute("UPDATE proposal SET statut = 'ANNULEE', motif_annulation = %s, "
                         "id_decision_cause = %s, date_fin = now() WHERE id = %s",
                         (motif_annulation, id_dec, id_p))
            conn.execute("UPDATE worker_day_slot SET statut = 'FERME', date_fermeture = now(), "
                         "motif_fermeture = %s WHERE id_proposal = %s AND statut = 'COURANT'",
                         (motif_annulation, id_p))
        if pc:
            conn.execute("UPDATE replacement_request SET statut_cycle = 'A_TRAITER', "
                         "cause_statut = 'CANDIDAT_REPRIS' WHERE id = %s", (pc[1],))
        absent = conn.execute("SELECT id_ouvrier_absent FROM replacement_request WHERE id = %s",
                              (pa["id_besoin"],)).fetchone()[0]
        id_p2 = conn.execute(
            "INSERT INTO proposal (id_run, numero, id_evaluation, id_besoin, id_ouvrier, date, "
            "id_ouvrier_absent, origine) VALUES (%s, %s, %s, %s, %s, %s, %s, 'CHOIX') "
            "RETURNING id", (run["id"], numero, id_eval, pa["id_besoin"], id_ouvrier,
                             run["date"], absent)).fetchone()[0]
        conn.execute("INSERT INTO worker_day_slot (date, id_ouvrier, type, id_proposal) "
                     "VALUES (%s, %s, 'RESERVE', %s)", (run["date"], id_ouvrier, id_p2))
        id_rempl = conn.execute(
            "INSERT INTO replacement_assignment (id_besoin, id_proposal, id_ouvrier, date, "
            "id_ouvrier_absent, id_decision_creation) VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id", (pa["id_besoin"], id_p2, id_ouvrier, run["date"], absent, id_dec)
        ).fetchone()[0]
        conn.execute("UPDATE proposal SET statut = 'ACCEPTEE', date_acceptation = now(), "
                     "date_fin = now() WHERE id = %s", (id_p2,))
        conn.execute("UPDATE worker_day_slot SET type = 'ENGAGE', id_remplacement = %s, "
                     "date_conversion = now() WHERE id_proposal = %s AND statut = 'COURANT'",
                     (id_rempl, id_p2))
        conn.execute("UPDATE replacement_request SET statut_cycle = 'POURVU', cause_statut = NULL "
                     "WHERE id = %s", (pa["id_besoin"],))
        # Le vivier a changé : les autres propositions sont recalculées (R-RECALC).
        _recalcul_requis(conn, run["id"], "DECISION", id_decision=id_dec)
        conn.commit()
    calculer(url, pa["id_run"], "CHOIX")
    return id_rempl


def rouvrir(url: str, id_besoin: int, identifiant: str, motif: str) -> None:
    """ROUVRIR : un besoin NON_POURVU d'un calcul ouvert redevient À TRAITER, puis recalcul."""
    with psycopg.connect(url) as conn:
        ligne = conn.execute("SELECT id_run FROM replacement_request WHERE id = %s",
                             (id_besoin,)).fetchone()
        if ligne is None:
            raise NonTrouve("BESOIN_INCONNU", f"besoin {id_besoin} inconnu")
        _verrous(conn, runs=[ligne[0]], ouvriers=_ouvriers_reserves(conn, ligne[0]))
        run = _run(conn, ligne[0], verrou=True)
        statut = conn.execute("SELECT statut_cycle FROM replacement_request WHERE id = %s",
                              (id_besoin,)).fetchone()[0]
        if run["statut"] == "CLOS":
            raise RefusMetier("RUN_CLOS", "calcul clos : lancer un nouveau calcul pour cette date")
        if statut != "NON_POURVU":
            raise RefusMetier("TRANSITION_INTERDITE", f"seul un besoin non pourvu peut être "
                                                      f"rouvert (statut actuel : {statut})")
        if not (motif or "").strip():
            raise RefusMetier("MOTIF_REQUIS", "rouvrir un besoin exige un motif")
        id_acteur, usage, cfg = _autoriser_decision(conn, identifiant, run["version_config"])
        id_dec = _decision(conn, id_besoin=id_besoin, id_run=run["id"], type_="ROUVRIR",
                           auteur=id_acteur, usage=usage, cfg_validee=cfg.validee, motif=motif)
        conn.execute("UPDATE replacement_request SET statut_cycle = 'A_TRAITER', "
                     "cause_statut = 'ROUVERT' WHERE id = %s", (id_besoin,))
        if run["statut"] == "OUVERT":
            _recalcul_requis(conn, run["id"], "DECISION", id_decision=id_dec)
        conn.commit()
    calculer(url, run["id"], "ROUVRIR")
