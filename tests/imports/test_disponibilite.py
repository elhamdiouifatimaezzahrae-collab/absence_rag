"""Disponibilité d'un ouvrier pour une date, calculée sur les données importées (ARTIFICIELLES)."""

import time as horloge
from datetime import date, datetime, timedelta

import psycopg
import pytest
from fabrique import J1, J2, absence, affectation, journalier

from agent_tag.domain import disponibilite as d

pytestmark = pytest.mark.db


def _etats(resultats):
    return {i: (x.etat, x.cause, x.besoin_creable) for i, x in resultats.items()}


def test_disponibilite_apres_import_valide(importer_jour, dispo):
    importer_jour(journalier())
    assert _etats(dispo(J1)) == {
        "T01": (d.DISPONIBLE, "PRESENT_SANS_ABSENCE", False),
        "T02": (d.ABSENT, "ABSENCE_CONFIRMEE", True),
        "T03": (d.DISPONIBLE, "PRESENT_SANS_ABSENCE", False),
        "T04": (d.DISPONIBLE, "PRESENT_SANS_ABSENCE", False),
    }


def test_sans_attestation_aucun_present_n_est_disponible(importer_jour, dispo):
    importer_jour(journalier(), attester=False)
    etats = _etats(dispo(J1))
    assert etats["T01"] == (d.INCONNU, "ABSENCES_NON_COMPLETES", False)
    assert etats["T02"] == (d.ABSENT, "ABSENCE_CONFIRMEE", True)


def test_date_sans_donnees_tous_inconnus(importer_jour, dispo):
    importer_jour(journalier())
    etats = _etats(dispo(J2))   # aucune donnée pour J2 : rien n'est généré
    assert {e for e, _, _ in etats.values()} == {d.INCONNU}
    assert {c for _, c, _ in etats.values()} == {"AFFECTATION_INCONNUE"}


def test_ouvrier_sans_affectation_inconnu(importer_jour, dispo):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"), affectation(J1, "T03")]
    importer_jour(journalier(affectations=affs))
    res = dispo(J1)
    assert _etats(res)["T04"] == (d.INCONNU, "AFFECTATION_INCONNUE", False)
    assert res["T04"].couverture_affectations == "PARTIEL"
    assert _etats(res)["T03"] == (d.DISPONIBLE, "PRESENT_SANS_ABSENCE", False)


def test_absence_sans_affectation_absent_sans_besoin(importer_jour, dispo):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"), affectation(J1, "T03")]
    importer_jour(journalier(affectations=affs, absences=[absence(J1, "T02"), absence(J1, "T04")]))
    assert _etats(dispo(J1))["T04"] == (d.ABSENT, "ABSENCE_SANS_AFFECTATION", False)


def test_contradictions_resolues_en_indetermine(importer_jour, dispo):
    affs = [affectation(J1, "T01"), affectation(J1, "T02", "Absent"),
            affectation(J1, "T03", "Absent"), affectation(J1, "T04")]
    importer_jour(journalier(affectations=affs, absences=[absence(J1, "T01"), absence(J1, "T02")]))
    etats = _etats(dispo(J1))
    assert etats["T01"] == (d.INDETERMINE, "CONTRADICTION_PRESENT_ET_ABSENCE", False)
    assert etats["T03"] == (d.INDETERMINE, "CONTRADICTION_ABSENT_SANS_ABSENCE", False)
    assert etats["T02"] == (d.ABSENT, "ABSENCE_CONFIRMEE", True)


def test_absence_de_plusieurs_jours_couvre_la_date_demandee(importer_jour, dispo):
    """Absence de T02 sur 3 jours à partir de J1 : J1..J1+2 certains ; J1+3, J1+4 possibles (D19)."""
    jours = [J1 + timedelta(days=k) for k in range(6)]
    affs = []
    for k, jour in enumerate(jours):
        for o in ("T01", "T03", "T04"):
            affs.append(affectation(jour, o))
        affs.append(affectation(jour, "T02", "Absent" if k < 3 else "Présent"))
    importer_jour(journalier(affectations=affs, absences=[absence(J1, "T02", duree=3)]))

    attendu = [(d.ABSENT, "ABSENCE_CONFIRMEE")] * 3 + \
              [(d.INDETERMINE, "ABSENCE_POSSIBLE_D19")] * 2 + \
              [(d.DISPONIBLE, "PRESENT_SANS_ABSENCE")]
    obtenu = [(x.etat, x.cause) for x in (dispo(j)["T02"] for j in jours)]
    assert obtenu == attendu


def test_absence_anterieure_ne_couvre_pas_la_date(importer_jour, dispo):
    veille = J1 - timedelta(days=1)
    affs = [affectation(veille, o, "Absent" if o == "T02" else "Présent")
            for o in ("T01", "T02", "T03", "T04")]
    affs += [affectation(J1, o) for o in ("T01", "T02", "T03", "T04")]
    importer_jour(journalier(affectations=affs, absences=[absence(veille, "T02")]))
    assert dispo(veille)["T02"].etat == d.ABSENT
    assert _etats(dispo(J1))["T02"] == (d.DISPONIBLE, "PRESENT_SANS_ABSENCE", False)


def test_filtres_par_ouvrier_et_par_chaine(importer_jour, dispo):
    importer_jour(journalier())
    assert set(dispo(J1, ouvriers=["T02"])) == {"T02"}
    assert set(dispo(J1, chaine="LB")) == {"T03", "T04"}


def test_statut_du_referentiel_jamais_utilise(importer_jour, dispo, base_referentiel):
    """Ouvriers.Statut vaut 'Disponible' pour T02, qui est pourtant ABSENT le jour J1."""
    importer_jour(journalier())
    with base_referentiel.owner() as c:
        assert c.execute("SELECT statut_source FROM worker WHERE id_ouvrier = 'T02'"
                         ).fetchone()[0] == "Disponible"
    assert dispo(J1)["T02"].etat == d.ABSENT


def test_historique_relu_a_un_instant_passe(importer_jour, dispo, base_referentiel):
    """Après remplacement de la couverture, l'état d'avant reste consultable à l'instant passé."""
    importer_jour(journalier())
    horloge.sleep(0.05)
    with psycopg.connect(base_referentiel.app_url) as c:
        entre_les_deux = c.execute("SELECT clock_timestamp()").fetchone()[0]
    horloge.sleep(0.05)
    affs = [affectation(J1, o) for o in ("T01", "T02", "T03", "T04")]
    importer_jour(journalier(affectations=affs, absences=[]))

    assert dispo(J1)["T02"].etat == d.DISPONIBLE                    # état courant
    passe = dispo(J1, instant=entre_les_deux)["T02"]
    assert (passe.etat, passe.besoin_creable) == (d.ABSENT, True)   # état historique
    with psycopg.connect(base_referentiel.app_url) as c:
        avant_tout = c.execute("SELECT min(horodatage) - interval '1 second' FROM import_batch"
                               ).fetchone()[0]
    assert {x.etat for x in dispo(J1, instant=avant_tout).values()} == {d.INCONNU}


def test_lot_rejete_sans_effet_sur_la_disponibilite(importer_jour, dispo):
    importer_jour(journalier())
    avant = _etats(dispo(J1))
    importer_jour(journalier().modifier("Affectations", 0, "ID_Ouvrier", "T99"))
    assert _etats(dispo(J1)) == avant
