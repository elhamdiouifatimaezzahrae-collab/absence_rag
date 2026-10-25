-- 0003 — Données journalières : affectations, absences, couvertures (Phase 4 B2 ; 4.1 corr. 4 ;
-- 4.2 points 1, 6, 8 ; 4.3 point 4 : version des données par date).
-- Les lignes importées ne sont jamais modifiées ni supprimées. Un nouvel import remplace la
-- couverture courante d'un (date, chaîne, type) ; l'ancien lot et ses lignes sont conservés.
-- Les saisies manuelles (source SAISIE) sont prévues par le modèle mais pas encore implémentées.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-------------------------------------------------------------------------------
-- Affectations journalières
-------------------------------------------------------------------------------
CREATE TABLE daily_assignment (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lot          bigint NOT NULL REFERENCES import_batch (id),
    date            date   NOT NULL,
    id_ouvrier      text   NOT NULL REFERENCES worker (id_ouvrier),
    id_chaine       text   NOT NULL REFERENCES production_line (id_chaine),
    code_poste      text   NOT NULL REFERENCES position (code_poste),
    heure_debut     time   NOT NULL,
    heure_fin       time   NOT NULL,
    statut_presence text   NOT NULL CHECK (statut_presence IN ('PRESENT', 'ABSENT')),
    statut_source   text   NOT NULL,                 -- valeur lue telle quelle (ex. 'Présent')
    statut_ligne    text   NOT NULL DEFAULT 'ACTIVE' CHECK (statut_ligne IN ('ACTIVE', 'ANNULEE')),
    CONSTRAINT affectation_unique_par_lot UNIQUE (id_lot, date, id_ouvrier),
    CONSTRAINT affectation_cible_fk UNIQUE (id, id_ouvrier, date),   -- cible de FK composite (4.3)
    CONSTRAINT affectation_horaire_ordonne CHECK (heure_fin > heure_debut)
);

CREATE INDEX affectation_par_date ON daily_assignment (date, id_ouvrier);

-------------------------------------------------------------------------------
-- Absences
-------------------------------------------------------------------------------
CREATE TABLE absence (
    id            bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_lot        bigint  NOT NULL REFERENCES import_batch (id),
    id_ouvrier    text    NOT NULL REFERENCES worker (id_ouvrier),
    date_debut    date    NOT NULL,
    duree_jours   integer NOT NULL CHECK (duree_jours >= 1),
    id_chaine     text    NOT NULL REFERENCES production_line (id_chaine),
    code_poste    text    NOT NULL REFERENCES position (code_poste),
    statut_source text    NOT NULL,
    motif         text    NULL,
    statut_ligne  text    NOT NULL DEFAULT 'ACTIVE' CHECK (statut_ligne IN ('ACTIVE', 'ANNULEE')),
    CONSTRAINT absence_unique_par_lot UNIQUE (id_lot, id_ouvrier, date_debut),
    CONSTRAINT absence_cible_fk UNIQUE (id, id_ouvrier),             -- cible de FK composite (4.2)
    -- Pas de chevauchement entre absences actives d'un même ouvrier dans un même lot (période
    -- calendaire certaine [début, début + durée[).
    CONSTRAINT absence_sans_chevauchement EXCLUDE USING gist (
        id_lot WITH =,
        id_ouvrier WITH =,
        daterange(date_debut, date_debut + duree_jours, '[)') WITH &&
    ) WHERE (statut_ligne = 'ACTIVE')
);

CREATE INDEX absence_par_ouvrier ON absence (id_ouvrier, date_debut);

-------------------------------------------------------------------------------
-- Couverture des lots : ce qu'un lot couvre, pour quelle date, chaîne et type de donnée
-------------------------------------------------------------------------------
CREATE TABLE batch_coverage (
    id_lot           bigint      NOT NULL REFERENCES import_batch (id),
    date             date        NOT NULL,
    id_chaine        text        NOT NULL REFERENCES production_line (id_chaine),
    type_donnee      text        NOT NULL CHECK (type_donnee IN ('AFFECTATIONS', 'ABSENCES')),
    etat             text        NOT NULL CHECK (etat IN ('COMPLET', 'PARTIEL')),
    mode_completude  text        NOT NULL CHECK (mode_completude IN ('CALCULEE', 'DECLAREE')),
    atteste_par      bigint      NULL REFERENCES app_user (id),
    source           text        NOT NULL DEFAULT 'IMPORT' CHECK (source IN ('IMPORT', 'SAISIE')),
    statut           text        NOT NULL CHECK (statut IN ('EN_ATTENTE', 'COURANT', 'REMPLACE')),
    debut_courant    timestamptz NULL,
    fin_courant      timestamptz NULL,
    remplace_par_lot bigint      NULL REFERENCES import_batch (id),
    PRIMARY KEY (id_lot, date, id_chaine, type_donnee),
    CONSTRAINT couverture_mode CHECK (
        (type_donnee = 'AFFECTATIONS' AND mode_completude = 'CALCULEE')
        OR (type_donnee = 'ABSENCES' AND mode_completude = 'DECLAREE')),
    CONSTRAINT couverture_attestation CHECK (
        NOT (mode_completude = 'DECLAREE' AND etat = 'COMPLET') OR atteste_par IS NOT NULL),
    CONSTRAINT couverture_periode CHECK (
        (statut = 'EN_ATTENTE' AND debut_courant IS NULL AND fin_courant IS NULL)
        OR (statut = 'COURANT' AND debut_courant IS NOT NULL AND fin_courant IS NULL)
        OR (statut = 'REMPLACE' AND debut_courant IS NOT NULL AND fin_courant IS NOT NULL
            AND fin_courant >= debut_courant AND remplace_par_lot IS NOT NULL))
);

-- Une seule couverture courante par (date, chaîne, type, source).
CREATE UNIQUE INDEX couverture_une_courante
    ON batch_coverage (date, id_chaine, type_donnee, source) WHERE statut = 'COURANT';

-- Seule transition autorisée : COURANT → REMPLACE (fin de validité et lot remplaçant).
CREATE FUNCTION batch_coverage_garde() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'batch_coverage : suppression interdite' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT (OLD.statut = 'COURANT' AND NEW.statut = 'REMPLACE')
       OR (NEW.id_lot, NEW.date, NEW.id_chaine, NEW.type_donnee, NEW.etat, NEW.mode_completude,
           NEW.atteste_par, NEW.source, NEW.debut_courant)
          IS DISTINCT FROM
          (OLD.id_lot, OLD.date, OLD.id_chaine, OLD.type_donnee, OLD.etat, OLD.mode_completude,
           OLD.atteste_par, OLD.source, OLD.debut_courant) THEN
        RAISE EXCEPTION 'batch_coverage : seule la transition COURANT → REMPLACE est autorisée'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER batch_coverage_garde
    BEFORE UPDATE OR DELETE ON batch_coverage
    FOR EACH ROW EXECUTE FUNCTION batch_coverage_garde();

-------------------------------------------------------------------------------
-- Version des données par date (incrémentée à chaque modification des données d'une date)
-------------------------------------------------------------------------------
CREATE TABLE data_version (
    date        date        PRIMARY KEY,
    version     bigint      NOT NULL CHECK (version >= 1),
    mise_a_jour timestamptz NOT NULL DEFAULT now()
);

-------------------------------------------------------------------------------
-- Droits
-------------------------------------------------------------------------------
GRANT SELECT, INSERT ON daily_assignment, absence, batch_coverage TO agent_tag_app;
GRANT UPDATE (statut, fin_courant, remplace_par_lot) ON batch_coverage TO agent_tag_app;
GRANT SELECT, INSERT, UPDATE ON data_version TO agent_tag_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO agent_tag_app;
