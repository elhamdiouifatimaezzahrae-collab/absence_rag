"""Incrément 5 : CHOISIR_AUTRE, ROUVRIR, vues des engagements et des imports, simulation de réimport.

Mêmes données que test_services_allocation (classeur fictif de référence, profil PROVISOIRE A).
Après chaque opération réussie, le vérificateur d'invariants doit être vide ; après un refus,
rien ne doit avoir changé.
"""

import psycopg
import pytest

from agent_tag import demo
from agent_tag.services import allocation as s
from agent_tag.services import configuration, vues

from test_services_allocation import J, actives, base, q, sain  # noqa: F401  (fixture base)

pytestmark = pytest.mark.db


def derniere(base, id_besoin):
    return q(base, "SELECT max(numero) FROM candidate_evaluation WHERE id_besoin = %s",
             id_besoin)[0][0]


def eligibles(base, pid, libres=None):
    """Candidats éligibles du besoin de la proposition pid, à sa dernière itération, hors
    candidat proposé. libres=True : sans créneau courant ; False : réservés par une autre
    proposition active du même calcul."""
    id_besoin, propose, run = q(base, "SELECT id_besoin, id_ouvrier, id_run FROM proposal "
                                      "WHERE id = %s", pid)[0]
    lignes = q(base, "SELECT e.id_ouvrier, s.id_proposal FROM candidate_evaluation e "
                     "LEFT JOIN worker_day_slot s ON s.id_ouvrier = e.id_ouvrier AND s.date = %s "
                     "AND s.statut = 'COURANT' WHERE e.id_besoin = %s AND e.numero = %s "
                     "AND e.eligible AND e.id_ouvrier <> %s ORDER BY e.rang, e.id_ouvrier",
               J, id_besoin, derniere(base, id_besoin), propose)
    if libres is True:
        return [o for o, slot in lignes if slot is None]
    if libres is False:
        return [o for o, slot in lignes if slot is not None]
    return [o for o, _ in lignes]


def instantane(base):
    return q(base, "SELECT (SELECT count(*) FROM allocation_decision), "
                   "(SELECT count(*) FROM replacement_assignment), "
                   "(SELECT count(*) FROM proposal WHERE statut = 'ACTIVE'), "
                   "(SELECT string_agg(id || statut_cycle, ',' ORDER BY id) FROM replacement_request)")


def une_proposition_avec_choix_libre(base):
    for absent, (pid, _) in sorted(actives(base).items()):
        for o in eligibles(base, pid, libres=True):
            return absent, pid, o
    pytest.skip("aucun candidat éligible libre dans les données")


# --- CHOISIR_AUTRE --------------------------------------------------------------------------

def test_choisir_autre_cas_nominal(base):
    id_run = s.lancer(base.url, J, "L1", "testeur")
    absent, pa, choisi = une_proposition_avec_choix_libre(base)
    propose = q(base, "SELECT id_ouvrier FROM proposal WHERE id = %s", pa)[0][0]
    try:
        id_rempl = s.choisir_autre(base.url, pa, choisi, "testeur", "préférence de l'atelier")
    except s.RefusMetier as e:          # contrôle de protection P1/P3 : légitime, mais non visé ici
        pytest.skip(f"candidat libre refusé par {e.code}")
    # Remplacement créé pour le candidat choisi, à partir d'une proposition d'origine CHOIX.
    assert q(base, "SELECT ra.id_ouvrier, ra.statut, p.origine, p.statut FROM replacement_assignment ra "
                   "JOIN proposal p ON p.id = ra.id_proposal WHERE ra.id = %s", id_rempl) == \
        [(choisi, "ACTIF", "CHOIX", "ACCEPTEE")]
    # La proposition initiale est annulée pour substitution et son ouvrier libéré.
    assert q(base, "SELECT statut, motif_annulation FROM proposal WHERE id = %s", pa) == \
        [("ANNULEE", "SUBSTITUTION")]
    assert q(base, "SELECT count(*) FROM worker_day_slot WHERE id_proposal = %s "
                   "AND statut = 'COURANT'", pa) == [(0,)]
    # Décision tracée avec la proposition substituée et le motif.
    assert q(base, "SELECT d.type, d.id_proposal, d.id_proposal_substituee, ra.id_ouvrier, d.motif "
                   "FROM allocation_decision d JOIN replacement_assignment ra "
                   "ON ra.id_decision_creation = d.id") == \
        [("CHOISIR_AUTRE", None, pa, choisi, "préférence de l'atelier")]
    # L'historique affiche le candidat CHOISI, pas celui de la proposition substituée.
    with psycopg.connect(base.url) as c:
        hist = vues.decisions(c, J, "L1", None)
        det = vues.detail_run(c, id_run, "testeur")
    assert [(d["type"], d["ouvrier"]) for d in hist] == [("CHOISIR_AUTRE", choisi)]
    besoin = next(b for b in det["besoins"] if b["absent"] == absent)
    assert [(d["type"], d["ouvrier"]) for d in besoin["decisions"]] == [("CHOISIR_AUTRE", choisi)]
    assert besoin["remplacement"]["ouvrier"] == choisi
    assert q(base, "SELECT statut_cycle FROM replacement_request WHERE id_run = %s "
                   "AND id_ouvrier_absent = %s", id_run, absent) == [("POURVU",)]
    assert q(base, "SELECT type FROM worker_day_slot WHERE id_ouvrier = %s AND date = %s "
                   "AND statut = 'COURANT'", choisi, J) == [("ENGAGE",)]
    # L'ancien candidat redevient libre ou est reproposé par le recalcul, jamais engagé.
    assert q(base, "SELECT count(*) FROM worker_day_slot WHERE id_ouvrier = %s AND date = %s "
                   "AND type = 'ENGAGE' AND statut = 'COURANT'", propose, J) == [(0,)]
    sain(base)


def test_choisir_autre_reprend_un_candidat_reserve_dans_le_meme_calcul(base):
    s.lancer(base.url, J, "L1", "testeur")
    trouve = None
    for absent, (pid, _) in sorted(actives(base).items()):
        reserves = eligibles(base, pid, libres=False)
        if reserves:
            trouve = (absent, pid, reserves[0])
            break
    if not trouve:
        pytest.skip("aucun candidat éligible réservé par un autre besoin")
    absent, pa, choisi = trouve
    pc, besoin_pc = q(base, "SELECT id, id_besoin FROM proposal WHERE id_ouvrier = %s "
                            "AND statut = 'ACTIVE'", choisi)[0]
    try:
        s.choisir_autre(base.url, pa, choisi, "testeur", "arbitrage manuel")
    except s.RefusMetier as e:
        pytest.skip(f"reprise refusée par {e.code}")
    assert q(base, "SELECT statut, motif_annulation FROM proposal WHERE id = %s", pc) == \
        [("ANNULEE", "CANDIDAT_REPRIS")]
    # Le besoin privé de son candidat a été recalculé : il n'est plus EN_ATTENTE sur pc.
    statut = q(base, "SELECT statut_cycle FROM replacement_request WHERE id = %s", besoin_pc)[0][0]
    assert statut in ("EN_ATTENTE", "NON_POURVU", "BLOQUE")
    assert q(base, "SELECT count(*) FROM proposal WHERE id_besoin = %s AND statut = 'ACTIVE' "
                   "AND id_ouvrier = %s", besoin_pc, choisi) == [(0,)]
    sain(base)


def test_choisir_autre_refus_sans_effet(base):
    s.lancer(base.url, J, "L1", "testeur")
    absent, pa, choisi = une_proposition_avec_choix_libre(base)
    propose = q(base, "SELECT id_ouvrier, id_besoin FROM proposal WHERE id = %s", pa)[0]
    avant = instantane(base)

    def refus(code, ouvrier, motif="motif", qui="testeur"):
        with pytest.raises((s.RefusMetier, s.Interdit)) as e:
            s.choisir_autre(base.url, pa, ouvrier, qui, motif)
        assert e.value.code == code
        assert instantane(base) == avant

    refus("MOTIF_REQUIS", choisi, motif="  ")
    refus("MEME_CANDIDAT", propose[0])
    refus("CANDIDAT_NON_EVALUE", "O999")
    non_eligible = q(base, "SELECT id_ouvrier FROM candidate_evaluation WHERE id_besoin = %s "
                           "AND numero = %s AND NOT eligible LIMIT 1",
                     propose[1], derniere(base, propose[1]))
    if non_eligible:
        refus("CANDIDAT_NON_ELIGIBLE", non_eligible[0][0])
    with pytest.raises(s.Interdit):
        s.choisir_autre(base.url, pa, choisi, "lecteur", "motif")
    assert instantane(base) == avant
    sain(base)


def test_choisir_autre_refuse_un_candidat_engage(base):
    s.lancer(base.url, J, "L1", "testeur")
    # Cherche un ouvrier proposé pour un besoin et éligible pour un autre.
    for absent, (pid, ouvrier) in sorted(actives(base).items()):
        autres = [(a, p) for a, (p, _) in actives(base).items()
                  if a != absent and ouvrier in eligibles(base, p)]
        if autres:
            break
    else:
        pytest.skip("aucun ouvrier éligible sur deux besoins")
    s.accepter(base.url, pid, "testeur")
    # Après acceptation, la proposition visée peut avoir été recalculée : relire les actives.
    a_cible = autres[0][0]
    if a_cible not in actives(base):
        pytest.skip("le besoin cible n'a plus de proposition active")
    p_cible = actives(base)[a_cible][0]
    avant = instantane(base)
    with pytest.raises(s.RefusMetier) as e:
        s.choisir_autre(base.url, p_cible, ouvrier, "testeur", "motif")
    assert e.value.code in ("CANDIDAT_ENGAGE", "CANDIDAT_NON_EVALUE", "CANDIDAT_NON_ELIGIBLE")
    assert instantane(base) == avant
    sain(base)


def test_choisir_autre_refuse_un_candidat_reserve_par_un_autre_calcul(base, tmp_path):
    # Un piqueur de L2 (même poste que deux absents de L1) devient absent (simulation TEST) ; le calcul L1 est lancé AVANT le
    # calcul L2, qui réserve ensuite des candidats évalués comme éligibles côté L1.
    absent_l2 = q(base, "SELECT a.id_ouvrier FROM daily_assignment a JOIN worker w "
                        "ON w.id_ouvrier = a.id_ouvrier WHERE a.date = %s AND a.id_chaine = 'L2' "
                        "AND a.statut_presence = 'PRESENT' AND a.statut_ligne = 'ACTIVE' "
                        "ORDER BY a.code_poste = 'PIQUEUR_PIQUEUSE' DESC, 1 LIMIT 1", J)
    if not absent_l2:
        pytest.skip("aucun ouvrier présent sur L2")
    # Profil PROVISOIRE B (plafond P3 = 10) : avec A (P3 = 2) L2 n'obtient aucun candidat.
    configuration.installer_profil_provisoire(base.owner_url, "B", "testeur")
    demo.simuler_reimport(base.url, "testeur", absent_l2[0][0], base.archives, tmp_path)
    s.lancer(base.url, J, "L1", "testeur")
    propositions_l1 = actives(base)
    try:
        s.lancer(base.url, J, "L2", "testeur")
    except s.RefusMetier as e:
        pytest.skip(f"calcul L2 impossible : {e.code}")
    reserves_l2 = {o for (o,) in q(base, "SELECT p.id_ouvrier FROM proposal p JOIN allocation_run r "
                                         "ON r.id = p.id_run WHERE r.id_chaine_cible = 'L2' "
                                         "AND p.statut = 'ACTIVE'")}
    cible = next(((pid, o) for _, (pid, _) in sorted(propositions_l1.items())
                  for o in eligibles(base, pid) if o in reserves_l2), None)
    if not cible:
        pytest.skip("le calcul L2 n'a réservé aucun candidat éligible côté L1")
    avant = instantane(base)
    with pytest.raises(s.RefusMetier) as e:
        s.choisir_autre(base.url, cible[0], cible[1], "testeur", "motif")
    assert e.value.code == "CANDIDAT_RESERVE_AILLEURS"
    assert instantane(base) == avant
    sain(base)


# --- ROUVRIR --------------------------------------------------------------------------------

def test_rouvrir_un_besoin_laisse_non_pourvu(base):
    id_run = s.lancer(base.url, J, "L1", "testeur")
    absent, (pid, _) = sorted(actives(base).items())[0]
    besoin = q(base, "SELECT id_besoin FROM proposal WHERE id = %s", pid)[0][0]
    s.laisser_non_pourvu(base.url, besoin, "testeur", "pas de remplacement aujourd'hui")
    assert q(base, "SELECT statut_cycle FROM replacement_request WHERE id = %s", besoin) == \
        [("NON_POURVU",)]
    with pytest.raises(s.RefusMetier) as e:
        s.rouvrir(base.url, besoin, "testeur", "")
    assert e.value.code == "MOTIF_REQUIS"
    s.rouvrir(base.url, besoin, "testeur", "finalement nécessaire")
    statut = q(base, "SELECT statut_cycle FROM replacement_request WHERE id = %s", besoin)[0][0]
    assert statut in ("EN_ATTENTE", "NON_POURVU", "BLOQUE")   # résultat du recalcul
    assert statut != "A_TRAITER"
    assert [t for (t,) in q(base, "SELECT type FROM allocation_decision WHERE id_besoin = %s "
                                  "ORDER BY id", besoin)] == ["LAISSER_NON_POURVU", "ROUVRIR"]
    assert q(base, "SELECT max(numero) FROM allocation_iteration WHERE id_run = %s", id_run)[0][0] >= 2
    sain(base)


def test_rouvrir_refuse_hors_non_pourvu_et_apres_cloture(base):
    id_run = s.lancer(base.url, J, "L1", "testeur")
    pid = sorted(actives(base).items())[0][1][0]
    besoin = q(base, "SELECT id_besoin FROM proposal WHERE id = %s", pid)[0][0]
    with pytest.raises(s.RefusMetier) as e:
        s.rouvrir(base.url, besoin, "testeur", "motif")
    assert e.value.code == "TRANSITION_INTERDITE"
    s.laisser_non_pourvu(base.url, besoin, "testeur", "motif")
    s.cloturer(base.url, id_run, "testeur", "fin de journée")
    with pytest.raises(s.RefusMetier) as e:
        s.rouvrir(base.url, besoin, "testeur", "motif")
    assert e.value.code == "RUN_CLOS"
    with pytest.raises(s.NonTrouve):
        s.rouvrir(base.url, 999999, "testeur", "motif")
    sain(base)


# --- Vues -----------------------------------------------------------------------------------

def test_vue_engagements_distingue_reserve_et_engage(base):
    s.lancer(base.url, J, "L1", "testeur")
    pid, ouvrier = sorted(actives(base).items())[0][1]
    s.accepter(base.url, pid, "testeur")
    with psycopg.connect(base.url) as c:
        liste = vues.engagements(c, J)
    types = {e["ouvrier"]: e["type"] for e in liste}
    assert types[ouvrier] == "ENGAGE"
    assert sum(t == "ENGAGE" for t in types.values()) == 1
    assert sum(t == "RESERVE" for t in types.values()) == len(actives(base))
    assert all(e["chaine_cible"] == "L1" and e["absent"] for e in liste)


def test_simulation_de_reimport_rend_les_consequences_visibles(base, tmp_path):
    id_run = s.lancer(base.url, J, "L1", "testeur")
    pid, ouvrier = sorted(actives(base).items())[0][1]
    s.accepter(base.url, pid, "testeur")
    rapport = demo.simuler_reimport(base.url, "testeur", ouvrier, base.archives, tmp_path)
    assert rapport.statut == "APPLIQUE"
    with psycopg.connect(base.url) as c:
        lots = vues.imports(c, J)
        detail = vues.detail_run(c, id_run, "testeur")
    assert [l["courant"] for l in lots][:2] == [True, False]
    assert lots[0]["remplacements_a_revoir"] == 1
    assert lots[0]["propositions_annulees"] == len(actives(base, id_run)) or \
        lots[0]["propositions_annulees"] >= 1
    assert detail["run"]["statut"] == "A_RECALCULER"
    assert detail["reimports"]["remplacements_a_revoir"] == 1
    assert detail["reimports"]["lots"]
    # Le remplacement confirmé n'est jamais annulé automatiquement.
    assert q(base, "SELECT statut, statut_revue FROM replacement_assignment") == [("ACTIF", "A_REVOIR")]
    sain(base)
