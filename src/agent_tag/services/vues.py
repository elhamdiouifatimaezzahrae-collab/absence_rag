"""Lectures pour l'API et l'interface (aucune écriture)."""

from __future__ import annotations

from collections import Counter
from datetime import date

from agent_tag.domain import allocation as moteur
from agent_tag.persistence import disponibilite
from agent_tag.services import allocation as s
from agent_tag.services import configuration

AVERTISSEMENT = ("Paramètres provisoires de TEST, non validés (D3 : P1, P2, P3 ; D4 : priorités). "
                 "Résultats non utilisables pour une décision réelle.")


def _cfg_dict(cfg) -> dict | None:
    if cfg is None:
        return None
    d = cfg.domaine
    return {"version": cfg.version, "statut": cfg.statut, "libelle": d.libelle,
            "m_bloc": d.m_bloc, "m_alerte": d.m_alerte, "p3": d.p3,
            "rangs_priorite": d.rangs_priorite, "regle_cascade": d.regle_cascade,
            "indicateurs": cfg.indicateurs, "validee": cfg.validee,
            "avertissement": None if cfg.validee else AVERTISSEMENT}


def etat(conn) -> dict:
    env = conn.execute("SELECT id_environnement::text, usage, libelle, fuseau_horaire "
                       "FROM environment").fetchone()
    utilisateurs = [dict(zip(("identifiant", "nom", "role"), u)) for u in conn.execute(
        "SELECT identifiant, nom, role FROM app_user WHERE actif ORDER BY identifiant")]
    chaines = [dict(zip(("id", "produit", "priorite"), c)) for c in conn.execute(
        "SELECT id_chaine, produit, libelle_priorite FROM production_line ORDER BY id_chaine")]
    dates = [d.isoformat() for (d,) in conn.execute(
        "SELECT DISTINCT date FROM batch_coverage WHERE statut = 'COURANT' ORDER BY date DESC")]
    return {
        "environnement": dict(zip(("id", "usage", "libelle", "fuseau_horaire"), env)) if env else None,
        "configuration": _cfg_dict(configuration.active(conn)),
        "utilisateurs": utilisateurs, "chaines": chaines, "dates": dates,
        "roles_decision_test": sorted(s.ROLES_DECISION_TEST),
    }


def effectifs(conn, jour: date, chaine: str) -> dict:
    postes = dict(conn.execute("SELECT code_poste, libelle FROM position"))
    lignes = disponibilite.lire(conn, jour, chaine=chaine)
    aff = {}
    ids = [d.id_affectation for d in lignes if d.id_affectation]
    if ids:
        aff = {i: p for i, p in conn.execute(
            "SELECT id, code_poste FROM daily_assignment WHERE id = ANY(%s)", (ids,))}
    principaux = dict(conn.execute("SELECT id_ouvrier, code_poste_principal FROM worker "
                                   "WHERE id_chaine_origine = %s", (chaine,)))
    ouvriers = []
    for d in lignes:
        code = aff.get(d.id_affectation) or principaux.get(d.id_ouvrier)
        ouvriers.append({"id": d.id_ouvrier, "nom": d.nom, "etat": d.etat, "cause": d.cause,
                         "besoin_creable": d.besoin_creable, "poste": postes.get(code, code),
                         "code_poste": code,
                         "couverture_affectations": d.couverture_affectations,
                         "couverture_absences": d.couverture_absences})
    ouvriers.sort(key=lambda o: (o["poste"] or "", o["id"]))
    return {"date": jour.isoformat(), "chaine": chaine, "ouvriers": ouvriers,
            "synthese": dict(Counter(o["etat"] for o in ouvriers))}


def runs(conn, jour: date | None = None, chaine: str | None = None) -> list[dict]:
    lignes = conn.execute(
        "SELECT r.id, r.date_run, r.id_chaine_cible, r.statut, r.cause_statut, r.date_creation, "
        "u.identifiant FROM allocation_run r JOIN app_user u ON u.id = r.cree_par "
        "WHERE (%s::date IS NULL OR r.date_run = %s) AND (%s::text IS NULL OR "
        "r.id_chaine_cible = %s) ORDER BY r.id DESC", (jour, jour, chaine, chaine)).fetchall()
    return [{"id": i, "date": d.isoformat(), "chaine": ch, "statut": st, "cause": ca,
             "date_creation": dc.isoformat(), "cree_par": u} for i, d, ch, st, ca, dc, u in lignes]


def decision_possible(conn, identifiant: str | None, version_config: int) -> tuple[bool, str]:
    try:
        s._autoriser_decision(conn, identifiant, version_config)
        return True, "décision autorisée en TEST (marquée TEST, non valable en réel)"
    except s.RefusMetier as exc:
        return False, exc.message


def detail_run(conn, id_run: int, identifiant: str | None = None) -> dict:
    run = s._run(conn, id_run)
    meta = conn.execute(
        "SELECT r.cause_statut, r.date_creation, u.identifiant, r.date_cloture, r.motif_cloture, "
        "c.identifiant FROM allocation_run r JOIN app_user u ON u.id = r.cree_par "
        "LEFT JOIN app_user c ON c.id = r.clos_par WHERE r.id = %s", (id_run,)).fetchone()
    cfg = configuration.charger(conn, run["version_config"])
    it = conn.execute(
        "SELECT numero, declencheur, date_calcul, instant_lecture, nb_besoins_consideres, "
        "couverture_sequentielle, couverture_maximale, alerte_combinaison, combinaison_maximale "
        "FROM allocation_iteration WHERE id_run = %s ORDER BY numero DESC LIMIT 1",
        (id_run,)).fetchone()
    noms = dict(conn.execute("SELECT id_ouvrier, nom FROM worker"))
    postes = dict(conn.execute("SELECT code_poste, libelle FROM position"))
    competences = dict(conn.execute("SELECT code_competence, libelle FROM skill"))
    niveaux = dict(conn.execute("SELECT code_niveau, libelle FROM skill_level"))

    besoins = []
    for (id_b, absent, poste, comp, niv, crit, rang, statut, cause) in conn.execute(
            "SELECT id, id_ouvrier_absent, code_poste, code_competence_requise, code_niveau_min, "
            "est_critique, rang_traitement, statut_cycle, cause_statut FROM replacement_request "
            "WHERE id_run = %s ORDER BY rang_traitement NULLS LAST, id_ouvrier_absent",
            (id_run,)).fetchall():
        prop = conn.execute(
            "SELECT p.id, p.id_ouvrier, p.numero, e.chaine_donneuse, e.poste_quitte, e.risque, "
            "e.rang, e.explication FROM proposal p JOIN candidate_evaluation e "
            "ON e.id = p.id_evaluation WHERE p.id_besoin = %s AND p.statut = 'ACTIVE'",
            (id_b,)).fetchone()
        rempl = conn.execute(
            "SELECT ra.id, ra.id_ouvrier, ra.statut_revue, ra.cause_revue, d.horodatage, "
            "u.identifiant, e.chaine_donneuse, e.poste_quitte, e.risque, e.explication, "
            "d.usage_environnement FROM replacement_assignment ra "
            "JOIN allocation_decision d ON d.id = ra.id_decision_creation "
            "JOIN app_user u ON u.id = d.auteur JOIN proposal p ON p.id = ra.id_proposal "
            "JOIN candidate_evaluation e ON e.id = p.id_evaluation "
            "WHERE ra.id_besoin = %s AND ra.statut = 'ACTIF'", (id_b,)).fetchone()
        numero_eval = conn.execute("SELECT max(numero) FROM candidate_evaluation "
                                   "WHERE id_besoin = %s", (id_b,)).fetchone()[0]
        candidats = []
        if numero_eval:
            for (o, el, rg, ri, pe, ex, ch, po, rest, aeq) in conn.execute(
                    "SELECT id_ouvrier, eligible, rang, risque, premier_echec, explication, "
                    "chaine_donneuse, poste_quitte, restants, ex_aequo FROM candidate_evaluation "
                    "WHERE id_besoin = %s AND numero = %s ORDER BY rang NULLS LAST, id_ouvrier",
                    (id_b, numero_eval)):
                candidats.append({"ouvrier": o, "nom": noms.get(o), "eligible": el, "rang": rg,
                                  "risque": ri, "premier_echec": pe, "explication": ex,
                                  "chaine": ch, "poste": postes.get(po, po), "restants": rest,
                                  "ex_aequo": aeq})
        historique_besoin = [
            {"type": ty, "ouvrier": o, "nom": noms.get(o), "motif": m, "auteur": u,
             "horodatage": h.isoformat()}
            for ty, o, m, u, h in conn.execute(
                "SELECT d.type, coalesce(p.id_ouvrier, rc.id_ouvrier, ra.id_ouvrier), d.motif, "
                "u.identifiant, d.horodatage FROM allocation_decision d "
                "JOIN app_user u ON u.id = d.auteur "
                "LEFT JOIN proposal p ON p.id = d.id_proposal "
                "LEFT JOIN replacement_assignment rc ON rc.id_decision_creation = d.id "
                "LEFT JOIN replacement_assignment ra ON ra.id = d.id_remplacement "
                "WHERE d.id_besoin = %s ORDER BY d.horodatage, d.id", (id_b,))]
        besoins.append({
            "id": id_b, "absent": absent, "nom_absent": noms.get(absent),
            "decisions": historique_besoin,
            "poste": postes.get(poste, poste), "competence": competences.get(comp, comp),
            "niveau_min": niveaux.get(niv, niv), "critique": crit, "rang_traitement": rang,
            "statut": statut, "cause": cause, "iteration_evaluation": numero_eval,
            "proposition": None if not prop else {
                "id": prop[0], "ouvrier": prop[1], "nom": noms.get(prop[1]), "iteration": prop[2],
                "chaine": prop[3], "poste": postes.get(prop[4], prop[4]), "risque": prop[5],
                "rang": prop[6], "explication": prop[7]},
            "remplacement": None if not rempl else {
                "id": rempl[0], "ouvrier": rempl[1], "nom": noms.get(rempl[1]),
                "statut_revue": rempl[2], "cause_revue": rempl[3],
                "confirme_le": rempl[4].isoformat(), "confirme_par": rempl[5],
                "chaine": rempl[6], "poste": postes.get(rempl[7], rempl[7]), "risque": rempl[8],
                "explication": rempl[9], "usage": rempl[10]},
            "candidats": candidats,
            "rejets": dict(Counter(c["premier_echec"] for c in candidats if not c["eligible"])),
        })

    possible, raison = decision_possible(conn, identifiant, run["version_config"])
    lots = conn.execute(
        "SELECT p.id_lot_cause, count(*), max(b.date_application) FROM proposal p "
        "JOIN import_batch b ON b.id = p.id_lot_cause WHERE p.id_run = %s "
        "AND p.motif_annulation = 'DONNEES_MODIFIEES' GROUP BY 1 ORDER BY 1", (id_run,)).fetchall()
    a_revoir = conn.execute(
        "SELECT count(*) FROM replacement_assignment ra JOIN replacement_request r "
        "ON r.id = ra.id_besoin WHERE r.id_run = %s AND ra.statut = 'ACTIF' "
        "AND ra.statut_revue = 'A_REVOIR'", (id_run,)).fetchone()[0]
    return {
        "run": {"id": run["id"], "date": run["date"].isoformat(), "chaine": run["chaine"],
                "statut": run["statut"], "cause_statut": meta[0], "version": run["version"],
                "date_creation": meta[1].isoformat(), "cree_par": meta[2],
                "date_cloture": meta[3].isoformat() if meta[3] else None,
                "motif_cloture": meta[4], "clos_par": meta[5]},
        "configuration": _cfg_dict(cfg),
        "iteration": None if not it else {
            "numero": it[0], "declencheur": it[1], "date_calcul": it[2].isoformat(),
            "instant_lecture": it[3].isoformat(), "besoins_consideres": it[4],
            "couverture_sequentielle": it[5], "couverture_maximale": it[6],
            "alerte_combinaison": it[7], "combinaison_maximale": it[8]},
        "besoins": besoins,
        "decision": {"possible": possible, "raison": raison},
        "reimports": {"lots": [{"lot": l, "propositions_annulees": n,
                                "applique_le": d.isoformat() if d else None} for l, n, d in lots],
                      "remplacements_a_revoir": a_revoir},
        "libelles_controles": moteur.LIBELLE_CONTROLE,
    }


def decisions(conn, jour: date | None = None, chaine: str | None = None,
              id_run: int | None = None) -> list[dict]:
    lignes = conn.execute(
        "SELECT d.id, d.horodatage, d.type, r.id_ouvrier_absent, "
        "coalesce(p.id_ouvrier, rc.id_ouvrier, ra.id_ouvrier), d.motif, u.identifiant, d.usage_environnement, "
        "d.configuration_validee, d.id_run, ru.id_chaine_cible, ru.date_run, d.exclure_ouvrier "
        "FROM allocation_decision d JOIN replacement_request r ON r.id = d.id_besoin "
        "JOIN allocation_run ru ON ru.id = d.id_run JOIN app_user u ON u.id = d.auteur "
        "LEFT JOIN proposal p ON p.id = d.id_proposal "
        "LEFT JOIN replacement_assignment ra ON ra.id = d.id_remplacement "
        "LEFT JOIN replacement_assignment rc ON rc.id_decision_creation = d.id "
        "WHERE (%s::date IS NULL OR ru.date_run = %s) "
        "AND (%s::text IS NULL OR ru.id_chaine_cible = %s) "
        "AND (%s::bigint IS NULL OR d.id_run = %s) ORDER BY d.horodatage DESC, d.id DESC",
        (jour, jour, chaine, chaine, id_run, id_run)).fetchall()
    noms = dict(conn.execute("SELECT id_ouvrier, nom FROM worker"))
    return [{"id": i, "horodatage": h.isoformat(), "type": t, "absent": ab,
             "nom_absent": noms.get(ab), "ouvrier": o, "nom_ouvrier": noms.get(o), "motif": m,
             "auteur": u, "usage": us, "configuration_validee": cv, "run": r, "chaine": ch,
             "date": d.isoformat(), "exclure_ouvrier": ex}
            for i, h, t, ab, o, m, u, us, cv, r, ch, d, ex in lignes]


def engagements(conn, jour: date) -> list[dict]:
    """Ouvriers réservés (proposition en attente) ou engagés (remplacement confirmé) à la date,
    tous calculs confondus."""
    noms = dict(conn.execute("SELECT id_ouvrier, nom FROM worker"))
    postes = dict(conn.execute("SELECT code_poste, libelle FROM position"))
    lignes = conn.execute(
        "SELECT s.id_ouvrier, s.type, s.date_ouverture, s.date_conversion, p.id, p.id_run, "
        "r.id_chaine_cible, p.id_ouvrier_absent, e.chaine_donneuse, e.poste_quitte, "
        "ra.statut_revue FROM worker_day_slot s JOIN proposal p ON p.id = s.id_proposal "
        "JOIN candidate_evaluation e ON e.id = p.id_evaluation "
        "JOIN replacement_request r ON r.id = p.id_besoin "
        "LEFT JOIN replacement_assignment ra ON ra.id = s.id_remplacement "
        "WHERE s.date = %s AND s.statut = 'COURANT' ORDER BY s.type DESC, s.id_ouvrier",
        (jour,)).fetchall()
    return [{"ouvrier": o, "nom": noms.get(o), "type": ty,
             "depuis": (conv or ouv).isoformat(), "proposition": pid, "run": run,
             "chaine_cible": cible, "absent": absent, "nom_absent": noms.get(absent),
             "chaine_donneuse": don, "poste_quitte": postes.get(pq, pq), "revue": rev}
            for o, ty, ouv, conv, pid, run, cible, absent, don, pq, rev in lignes]


def imports(conn, jour: date) -> list[dict]:
    """Lots de données journalières couvrant la date, avec leurs conséquences."""
    lignes = conn.execute(
        "SELECT b.id, b.fichier_source, b.horodatage, b.date_application, u.identifiant, "
        "bool_or(c.statut = 'COURANT'), string_agg(DISTINCT c.id_chaine, ', '), "
        "(SELECT count(*) FROM proposal p WHERE p.id_lot_cause = b.id), "
        "(SELECT count(*) FROM replacement_assignment ra WHERE ra.id_lot_revue = b.id) "
        "FROM import_batch b JOIN batch_coverage c ON c.id_lot = b.id "
        "JOIN app_user u ON u.id = b.auteur WHERE c.date = %s "
        "GROUP BY b.id, u.identifiant ORDER BY b.id DESC", (jour,)).fetchall()
    return [{"lot": i, "fichier": f, "horodatage": h.isoformat(),
             "applique_le": a.isoformat() if a else None, "auteur": u, "courant": cour,
             "chaines": ch, "propositions_annulees": pa, "remplacements_a_revoir": rr}
            for i, f, h, a, u, cour, ch, pa, rr in lignes]
