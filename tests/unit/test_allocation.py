"""Moteur d'allocation — tests unitaires sur instantanés ARTIFICIELS (sans base)."""

import itertools
import random
from datetime import time

import pytest
from fabrique_allocation import P, S, base, config

from agent_tag.domain import allocation as a


def _besoin(res, id_absent="C1"):
    return next(b for b in res.besoins if b.id_ouvrier_absent == id_absent)


def _evals(res, id_absent="C1"):
    return {e.id_ouvrier: e for e in _besoin(res, id_absent).evaluations}


def _avec_reserve(f, chaine, poste, n=2, prefixe="R"):
    """Ajoute n titulaires DISPONIBLES sans la compétence évaluée (renforcent le poste)."""
    for i in range(n):
        f.ouvrier(f"{prefixe}{chaine}{poste}{i}", chaine, poste, competences=[P(comp="aut")])
    return f


# --- Compétences et niveaux --------------------------------------------------------------

def test_competence_secondaire_admise():
    f = _avec_reserve(base(), "LD", "FIN")
    f.ouvrier("D1", "LD", "FIN", competences=[P(comp="fin"), S("INTERMEDIAIRE")])
    res = a.allouer(f.instantane(), config(), "LC")
    assert _besoin(res).proposition.id_ouvrier == "D1"
    assert _evals(res)["D1"].type_competence == "SECONDAIRE"


def test_niveau_inferieur_refuse_superieur_admis():
    f = _avec_reserve(base(), "LD", "PIQ")
    f.ouvrier("D1", "LD", "PIQ", competences=[P("DEBUTANT")])
    f.ouvrier("D2", "LD", "PIQ", competences=[P("EXPERT")])
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))
    assert (ev["D1"].eligible, ev["D1"].premier_echec) == (False, "R5")
    assert "Debutant < Intermediaire" in ev["D1"].explication   # libellés artificiels
    assert ev["D2"].eligible


def test_detenteurs_sans_la_competence_non_evalues():
    f = _avec_reserve(base(), "LD", "PIQ")
    f.ouvrier("D1", "LD", "PIQ", competences=[P(comp="sur")])
    assert "D1" not in _evals(a.allouer(f.instantane(), config(), "LC"))


# --- Disponibilité, chaîne cible, horaire, engagements ------------------------------------

@pytest.mark.parametrize("etat", ["ABSENT", "INDETERMINE", "INCONNU"])
def test_candidat_non_disponible_refuse(etat):
    f = _avec_reserve(base(), "LD", "PIQ")
    f.ouvrier("D1", "LD", "PIQ", etat, [P()], besoin=False)
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["D1"]
    assert (ev.eligible, ev.premier_echec) == (False, "R6")


def test_chaine_cible_exclue_D1():
    f = base()
    f.ouvrier("C2", "LC", "FIN", competences=[P(comp="fin"), S("EXPERT")])
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["C2"]
    assert (ev.eligible, ev.premier_echec) == (False, "R7")


def test_horaire_incompatible_refuse():
    f = _avec_reserve(base(), "LD", "PIQ")
    f.ouvrier("D1", "LD", "PIQ", competences=[P()], horaire=(time(14), time(22)))
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["D1"]
    assert (ev.eligible, ev.premier_echec) == (False, "R9")


def test_engage_ailleurs_S0_et_cascade_refuses():
    f = _avec_reserve(base(), "LD", "PIQ")
    _avec_reserve(f, "LE", "PIQ")
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])
    f.ouvrier("E1", "LE", "PIQ", competences=[P()])
    f.engages.add("D1")
    f.chaines_interdites.add("LE")
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))
    assert ev["D1"].premier_echec == "S0"
    assert ev["E1"].premier_echec == "CASCADE"
    # R-CASCADE désactivée : E1 redevient éligible.
    ev2 = _evals(a.allouer(f.instantane(), config(regle_cascade=False), "LC"))
    assert ev2["E1"].eligible


# --- Risques sur la chaîne donneuse --------------------------------------------------------

def test_P1_bloque_si_le_poste_quitte_serait_sous_le_minimum():
    f = base()
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])           # seul titulaire du poste
    ev = _evals(a.allouer(f.instantane(), config(m_bloc=1), "LC"))["D1"]
    assert (ev.restants, ev.risque, ev.premier_echec) == (0, a.BLOQUANT, "P1")
    ev0 = _evals(a.allouer(f.instantane(), config(m_bloc=0, m_alerte=1), "LC"))["D1"]
    assert (ev0.eligible, ev0.risque, ev0.causes_risque) == (True, a.ELEVE, ["P2"])


def test_risque_mesure_sur_le_poste_quitte_pas_sur_la_competence_apportee():
    """D1 sait piquer mais occupe FIN, seul sur FIN : c'est FIN qui serait vidé."""
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    f.ouvrier("D1", "LD", "FIN", competences=[P(comp="fin"), S()])
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["D1"]
    assert (ev.poste_quitte, ev.restants, ev.premier_echec) == ("FIN", 0, "P1")


def test_absences_de_la_donneuse_reduisent_les_presents():
    f = base()
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])
    f.ouvrier("D2", "LD", "PIQ", "ABSENT", [P(comp="aut")], besoin=True)
    ev = _evals(a.allouer(f.instantane(), config(m_bloc=1), "LC"))["D1"]
    assert (ev.presents_poste, ev.restants, ev.risque) == (1, 0, a.BLOQUANT)


def test_P2_risque_eleve_et_competence_critique_de_la_donneuse():
    f = base()
    f.chaine("LD", "Moyenne", critiques=("fin",))
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])
    f.ouvrier("D2", "LD", "PIQ", competences=[P(comp="aut")])
    f.ouvrier("D3", "LD", "FIN", competences=[P(comp="fin"), S()])
    _avec_reserve(f, "LD", "FIN", n=3)
    ev = _evals(a.allouer(f.instantane(), config(m_bloc=0, m_alerte=2), "LC"))
    assert (ev["D1"].risque, ev["D1"].causes_risque) == (a.ELEVE, ["P2"])
    assert (ev["D3"].risque, ev["D3"].causes_risque) == (a.ELEVE, ["CRITIQUE"])


def test_criticite_inconnue_traitee_comme_risque_eleve():
    f = base().poste("XXX", None)
    f.ouvrier("D1", "LD", "XXX", competences=[S()])
    _avec_reserve(f, "LD", "XXX", n=3)
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["D1"]
    assert "CRITIQUE_INCONNUE" in ev.causes_risque and ev.risque == a.ELEVE


def test_correspondance_deduite_signalee():
    f = base().poste("COU", "cou", source="DEDUITE")
    f.ouvrier("D1", "LD", "COU", competences=[P(comp="cou"), S()])
    _avec_reserve(f, "LD", "COU", n=3)
    ev = _evals(a.allouer(f.instantane(), config(), "LC"))["D1"]
    assert ev.correspondance_deduite and "D7" in ev.explication


def test_P3_plafond_de_transferts_par_chaine():
    f = base()
    f.ouvrier("C2", "LC", "PIQ", "ABSENT", [P()])
    for i in range(4):
        f.ouvrier(f"D{i}", "LD", "PIQ", competences=[P()])
    res = a.allouer(f.instantane(), config(m_bloc=0, p3=1), "LC")
    statuts = sorted(b.statut for b in res.besoins)
    assert statuts == [a.AUCUN_CANDIDAT, a.PROPOSITION]
    sans = next(b for b in res.besoins if b.statut == a.AUCUN_CANDIDAT)
    assert "P3" in sans.cause


# --- Classement --------------------------------------------------------------------------

def test_classement_risque_puis_priorite_puis_niveau_juste_suffisant():
    f = base()
    for ch in ("LD", "LE"):
        _avec_reserve(f, ch, "PIQ", n=3)
    f.ouvrier("E_INT", "LE", "PIQ", competences=[P("INTERMEDIAIRE", 5)])  # Élevée
    f.ouvrier("D_EXP", "LD", "PIQ", competences=[P("EXPERT", 8)])         # Moyenne, expert
    f.ouvrier("D_INT", "LD", "PIQ", competences=[P("INTERMEDIAIRE", 3)])  # Moyenne, juste
    f.ouvrier("D_SEC", "LD", "SUR", competences=[P(comp="sur"), S("INTERMEDIAIRE", 9)])
    _avec_reserve(f, "LD", "SUR", n=3)
    res = a.allouer(f.instantane(), config(), "LC")
    ordre = [e.id_ouvrier for e in _besoin(res).evaluations if e.eligible]
    # Moyenne avant Élevée ; à priorité égale, Intermédiaire (= minimum) avant Expert ;
    # à niveau égal, principale avant secondaire même avec moins d'années.
    assert ordre == ["D_INT", "D_SEC", "D_EXP", "E_INT"]
    assert _besoin(res).proposition.id_ouvrier == "D_INT"


def test_risque_faible_passe_avant_une_meilleure_priorite():
    f = base()
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])          # Moyenne, mais 1 restant
    f.ouvrier("D2", "LD", "PIQ", competences=[P(comp="aut")])
    _avec_reserve(f, "LE", "PIQ", n=3)
    f.ouvrier("E1", "LE", "PIQ", competences=[P()])          # Élevée, 3 restants
    res = a.allouer(f.instantane(), config(m_bloc=0, m_alerte=2), "LC")
    assert _besoin(res).proposition.id_ouvrier == "E1"


def test_departage_annees_puis_identifiant_et_ex_aequo():
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    f.ouvrier("D2", "LD", "PIQ", competences=[P(ans=4)])
    f.ouvrier("D1", "LD", "PIQ", competences=[P(ans=4)])
    f.ouvrier("D3", "LD", "PIQ", competences=[P(ans=5)])
    ev = [e for e in _besoin(a.allouer(f.instantane(), config(), "LC")).evaluations if e.eligible]
    assert [e.id_ouvrier for e in ev] == ["D3", "D1", "D2"]
    assert [e.ex_aequo for e in ev] == [False, True, True]


def test_certification_sans_effet_sur_le_classement():
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    f.ouvrier("D1", "LD", "PIQ", competences=[P(ans=4)])
    f.ouvrier("D2", "LD", "PIQ", competences=[P(ans=4)])
    inst = f.instantane()
    d = inst.competences[("D2", "piq")]
    inst.competences[("D2", "piq")] = a.Detenue(d.type_competence, d.code_niveau, d.rang_niveau,
                                                d.annees, True)
    assert _besoin(a.allouer(inst, config(), "LC")).proposition.id_ouvrier == "D1"


# --- Besoins -----------------------------------------------------------------------------

def test_besoin_bloque_sans_exigence_ou_sans_niveau_minimum():
    f = base().exigence("LC", "SUR", "sur", niveau_min=None)
    f.ouvrier("C2", "LC", "COU", "ABSENT", [P(comp="cou")])    # aucune exigence pour COU
    f.ouvrier("C3", "LC", "SUR", "ABSENT", [P(comp="sur")])    # niveau minimum vide
    f.ouvrier("D1", "LD", "COU", competences=[P(comp="cou", niveau="EXPERT")])
    res = a.allouer(f.instantane(), config(), "LC")
    assert _besoin(res, "C2").statut == a.BLOQUE and "EXIGENCE_ABSENTE" in _besoin(res, "C2").cause
    assert _besoin(res, "C3").statut == a.BLOQUE and "NIVEAU_MIN_ABSENT" in _besoin(res, "C3").cause
    assert _besoin(res, "C2").evaluations == [] and _besoin(res, "C2").proposition is None


def test_correspondance_deduite_ne_debloque_pas_le_poste():
    """Le poste COU a une compétence déduite (D7) : cela ne crée pas d'exigence."""
    f = base().poste("COU", "cou", source="DEDUITE")
    f.ouvrier("C2", "LC", "COU", "ABSENT", [P(comp="cou")])
    assert _besoin(a.allouer(f.instantane(), config(), "LC"), "C2").statut == a.BLOQUE


def test_besoin_seulement_pour_une_absence_confirmee():
    f = base()
    f.ouvrier("C2", "LC", "PIQ", "INDETERMINE", [P()], besoin=False)
    f.ouvrier("C3", "LC", "PIQ", "ABSENT", [P()], besoin=False)   # absence sans affectation
    res = a.allouer(f.instantane(), config(), "LC")
    assert [b.id_ouvrier_absent for b in res.besoins] == ["C1"]
    assert {(e.id_ouvrier, e.etat) for e in res.ecarts} == {("C2", "INDETERMINE"),
                                                            ("C3", "ABSENT")}


def test_aucun_detenteur():
    res = a.allouer(base().instantane(), config(), "LC")
    b = _besoin(res)
    assert b.statut == a.AUCUN_CANDIDAT and b.cause.startswith("AUCUN_DETENTEUR")


# --- Allocation séquentielle -------------------------------------------------------------

def test_ordre_critiques_puis_moins_de_candidats_puis_identifiant():
    f = base().exigence("LC", "FIN", "fin")
    f.ouvrier("C2", "LC", "FIN", "ABSENT", [P(comp="fin")])     # non critique, 1 candidat
    f.ouvrier("C0", "LC", "PIQ", "ABSENT", [P()])               # critique, même vivier que C1
    for i in range(3):
        f.ouvrier(f"D{i}", "LD", "PIQ", competences=[P()])
    f.ouvrier("E1", "LE", "FIN", competences=[P(comp="fin")])
    _avec_reserve(f, "LD", "PIQ", n=3)
    _avec_reserve(f, "LE", "FIN", n=3)
    res = a.allouer(f.instantane(), config(), "LC")
    ordre = sorted(res.besoins, key=lambda b: b.rang_traitement)
    assert [b.id_ouvrier_absent for b in ordre] == ["C0", "C1", "C2"]


def test_un_ouvrier_n_est_propose_qu_une_fois_et_risque_recalcule():
    f = base()
    f.ouvrier("C2", "LC", "PIQ", "ABSENT", [P()])
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])
    f.ouvrier("D2", "LD", "PIQ", competences=[P()])
    f.ouvrier("D3", "LD", "PIQ", competences=[P(comp="aut")])
    res = a.allouer(f.instantane(), config(m_bloc=1, m_alerte=2), "LC")
    proposes = [b.proposition.id_ouvrier for b in res.besoins if b.proposition]
    assert len(proposes) == len(set(proposes)) == 2
    second = sorted(res.besoins, key=lambda b: b.rang_traitement)[1]
    # Après la première réservation, il ne reste que 1 titulaire : risque P2 sur le second.
    assert second.proposition.restants == 1 and second.qualite == "AVEC_ALERTE"
    assert any(e.premier_echec == "R8" for e in second.evaluations)


def test_calcul_deterministe():
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    for i in range(5):
        f.ouvrier(f"D{i}", "LD", "PIQ", competences=[P(ans=3)])
    r1 = a.allouer(f.instantane(), config(), "LC")
    r2 = a.allouer(f.instantane(), config(), "LC")
    assert [(e.id_ouvrier, e.rang) for e in _besoin(r1).evaluations] == \
           [(e.id_ouvrier, e.rang) for e in _besoin(r2).evaluations]


def test_moteur_ne_modifie_pas_l_instantane():
    import copy
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    f.ouvrier("D1", "LD", "PIQ", competences=[P()])
    inst = f.instantane()
    avant = copy.deepcopy(inst)
    a.allouer(inst, config(), "LC")
    assert inst == avant


# --- Configuration -----------------------------------------------------------------------

def test_configuration_incoherente_refusee():
    with pytest.raises(a.ConfigurationInvalide, match="m_alerte"):
        a.allouer(base().instantane(), config(m_bloc=2, m_alerte=1), "LC")
    with pytest.raises(a.ConfigurationInvalide, match="entier"):
        config(m_bloc=-1).verifier()
    cfg = a.Configuration("x", 1, 1, 1, {"Moyenne": 1})
    with pytest.raises(a.ConfigurationInvalide, match="sans rang"):
        a.allouer(base().instantane(), cfg, "LC")


def test_profils_provisoires_non_valides():
    assert all(not c.validee for c in a.PROFILS_PROVISOIRES.values())
    res = a.allouer(base().instantane(), a.PROFILS_PROVISOIRES["A"], "LC")
    assert res.utilisable_en_production is False


# --- Couverture maximale (flot) ----------------------------------------------------------

def _exemple_phase_3C(p3=2):
    """Exemple artificiel de la Phase 3C : B1, B2 (piq) et B3 (sur) ; donneuse DA (Moyenne) avec
    X1, X2 piqueurs et X3, X4 finisseurs (X3 sait piquer et surjeter) ; donneuse DB (Élevée) avec
    Y1, Y2, Y3 surjeteurs (Y1, Y2 savent surjeter). m_bloc = 1."""
    f = (base().chaine("LC", "Très élevée", critiques=("sur",))
         .chaine("DA", "Moyenne").chaine("DB", "Élevée")
         .exigence("LC", "SUR", "sur"))
    del f.ouvriers["C1"], f.jour["C1"], f.competences[("C1", "piq")]
    f.ouvrier("B1", "LC", "PIQ", "ABSENT", [P()])
    f.ouvrier("B2", "LC", "PIQ", "ABSENT", [P()])
    f.ouvrier("B3", "LC", "SUR", "ABSENT", [P(comp="sur")])
    f.ouvrier("X1", "DA", "PIQ", competences=[P()])
    f.ouvrier("X2", "DA", "PIQ", competences=[P()])
    f.ouvrier("X3", "DA", "FIN", competences=[P(comp="fin"), S(), S(comp="sur")])
    f.ouvrier("X4", "DA", "FIN", competences=[P(comp="fin")])
    f.ouvrier("Y1", "DB", "SUR", competences=[P(comp="sur")])
    f.ouvrier("Y2", "DB", "SUR", competences=[P(comp="sur")])
    f.ouvrier("Y3", "DB", "SUR", competences=[P(comp="aut")])
    return f.instantane(), config(m_bloc=1, m_alerte=1, p3=p3)


def test_flot_exemple_3C_maximum_3_et_alerte_sur_la_combinaison_sequentielle():
    inst, cfg = _exemple_phase_3C()
    res = a.allouer(inst, cfg, "LC")
    # B3 (critique) traité en premier : X3 (donneuse Moyenne) est préféré à Y1 (Élevée).
    assert _besoin(res, "B3").proposition.id_ouvrier == "X3"
    assert res.couverture_sequentielle == 2
    assert res.couverture_maximale == 3
    assert res.alerte_combinaison
    comb = res.combinaison_maximale
    assert len(comb) == 3 and len(set(comb.values())) == 3
    assert comb["B3"] in ("Y1", "Y2")


def test_flot_respecte_P3():
    inst, cfg = _exemple_phase_3C(p3=1)
    assert a.allouer(inst, cfg, "LC").couverture_maximale == 2


def test_flot_ignore_les_besoins_bloques():
    inst, cfg = _exemple_phase_3C()
    inst.exigences.pop(("LC", "SUR"))
    res = a.allouer(inst, cfg, "LC")
    assert res.besoins_consideres == 2 and res.couverture_maximale == 2


def _force_brute(inst, cfg, besoins):
    """Couverture maximale par énumération (petites instances), contraintes strictes."""
    stricts = ("R4", "R5", "R6", "R7", "R9", "EXCLU", "S0", "CASCADE")
    options = []
    for b in besoins:
        cands = [e.id_ouvrier for e in a.evaluer_candidats(inst, cfg, b)
                 if all(e.controles[k] == a.OK for k in stricts)]
        options.append([None] + cands)
    presents, *_ = a._comptages(inst, {})
    meilleur = 0
    for choix in itertools.product(*options):
        pris = [c for c in choix if c]
        if len(pris) != len(set(pris)):
            continue
        par_poste, par_chaine = {}, {}
        for c in pris:
            j = inst.jour[c]
            par_poste[(j.chaine, j.poste)] = par_poste.get((j.chaine, j.poste), 0) + 1
            par_chaine[j.chaine] = par_chaine.get(j.chaine, 0) + 1
        if all(presents[k] - n >= cfg.m_bloc for k, n in par_poste.items()) and \
           all(n <= cfg.p3 for n in par_chaine.values()):
            meilleur = max(meilleur, len(pris))
    return meilleur


@pytest.mark.parametrize("graine", range(40))
def test_propriete_sequentiel_inferieur_ou_egal_au_maximum_exact(graine):
    """Instances aléatoires : le flot égale la force brute, et séquentiel ≤ maximum (I15)."""
    rnd = random.Random(graine)
    f = (base().chaine("LC", "Très élevée", critiques=("piq",))
         .exigence("LC", "SUR", "sur", "DEBUTANT").exigence("LC", "FIN", "fin"))
    del f.ouvriers["C1"], f.jour["C1"], f.competences[("C1", "piq")]
    for i in range(rnd.randint(1, 4)):
        poste, comp = rnd.choice([("PIQ", "piq"), ("SUR", "sur"), ("FIN", "fin")])
        f.ouvrier(f"C{i}", "LC", poste, "ABSENT", [P(comp=comp)])
    niveaux = ["DEBUTANT", "INTERMEDIAIRE", "EXPERT"]
    for i in range(rnd.randint(2, 7)):
        ch = rnd.choice(["LD", "LE"])
        poste, comp = rnd.choice([("PIQ", "piq"), ("SUR", "sur"), ("FIN", "fin")])
        comps = [P(rnd.choice(niveaux), rnd.randint(1, 8), comp)]
        for autre in rnd.sample(["piq", "sur", "fin"], rnd.randint(0, 2)):
            if autre != comp:
                comps.append(S(rnd.choice(niveaux), rnd.randint(1, 8), autre))
        f.ouvrier(f"W{i}", ch, poste, rnd.choice(["DISPONIBLE"] * 4 + ["INCONNU"]), comps,
                  besoin=False)
    cfg = config(m_bloc=rnd.randint(0, 1), m_alerte=1, p3=rnd.randint(1, 3))
    inst = f.instantane()
    res = a.allouer(inst, cfg, "LC")
    traitables = [b for b in res.besoins if b.statut != a.BLOQUE]
    assert res.couverture_maximale == _force_brute(inst, cfg, traitables)
    assert res.couverture_sequentielle <= res.couverture_maximale


def test_exclusion_apres_refus_et_besoin_deja_traite():
    f = _avec_reserve(base(), "LD", "PIQ", n=3)
    f.ouvrier("D1", "LD", "PIQ", competences=[P(ans=5)])
    f.ouvrier("D2", "LD", "PIQ", competences=[P(ans=3)])
    inst = f.instantane()
    assert _besoin(a.allouer(inst, config(), "LC")).proposition.id_ouvrier == "D1"
    inst.exclusions = {"C1": frozenset({"D1"})}
    res = a.allouer(inst, config(), "LC")
    assert _besoin(res).proposition.id_ouvrier == "D2"
    assert _evals(res)["D1"].premier_echec == "EXCLU"
    inst.besoins_exclus = frozenset({"C1"})
    res = a.allouer(inst, config(), "LC")
    assert _besoin(res).statut == a.DEJA_TRAITE and res.besoins_consideres == 0
