-- 0004 — Processus d'allocation : configuration, calculs, propositions, réservations, décisions
-- (Phase 4 B3, B4 ; 4.1 corr. 1, 3, 6 ; 4.2 points 2, 4, 7 ; 4.3 points 1, 3, 5).
-- Une proposition n'est jamais une affectation : seul un replacement_assignment créé par une
-- décision humaine explicite représente un remplacement confirmé.

-------------------------------------------------------------------------------
-- Configuration versionnée (D3, D4, D12, D17 : valeurs PROVISOIRES tant que non validées)
-------------------------------------------------------------------------------
CREATE TABLE allocation_configuration (
    version                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    libelle                text        NOT NULL CHECK (btrim(libelle) <> ''),
    statut                 text        NOT NULL DEFAULT 'BROUILLON'
                           CHECK (statut IN ('BROUILLON', 'ACTIVE', 'ARCHIVEE')),
    copie_de               bigint      NULL REFERENCES allocation_configuration (version),
    m_bloc                 integer     NULL CHECK (m_bloc >= 0),
    m_bloc_valide          boolean     NOT NULL DEFAULT false,
    m_alerte               integer     NULL CHECK (m_alerte >= 0),
    m_alerte_valide        boolean     NOT NULL DEFAULT false,
    p3                     integer     NULL CHECK (p3 >= 0),
    p3_valide              boolean     NOT NULL DEFAULT false,
    priorites_valide       boolean     NOT NULL DEFAULT false,
    mode_expiration        text        NULL CHECK (mode_expiration IN ('MANUELLE', 'AUTOMATIQUE')),
    mode_expiration_valide boolean     NOT NULL DEFAULT false,
    regle_cascade          boolean     NOT NULL DEFAULT true,
    regle_cascade_valide   boolean     NOT NULL DEFAULT false,
    derogation_autorisee   boolean     NOT NULL DEFAULT false CHECK (NOT derogation_autorisee),
    reaffectation_interne  boolean     NOT NULL DEFAULT false CHECK (NOT reaffectation_interne),
    auteur                 bigint      NOT NULL REFERENCES app_user (id),
    date_creation          timestamptz NOT NULL DEFAULT now(),
    active_par             bigint      NULL REFERENCES app_user (id),
    date_activation        timestamptz NULL,
    origine_externe        text        NULL,
    CONSTRAINT config_alerte_bloc CHECK (m_alerte IS NULL OR m_bloc IS NULL OR m_alerte >= m_bloc)
);
-- D5/D16 : la dérogation reste désactivée (contrainte) tant que la décision n'est pas prise ;
-- D1 : la réaffectation interne est hors V1.

CREATE UNIQUE INDEX config_une_active ON allocation_configuration ((statut)) WHERE statut = 'ACTIVE';

CREATE TABLE config_priority_rank (
    version          bigint  NOT NULL REFERENCES allocation_configuration (version),
    libelle_priorite text    NOT NULL,
    rang             integer NOT NULL CHECK (rang > 0),
    PRIMARY KEY (version, libelle_priorite),
    UNIQUE (version, rang)
);

CREATE FUNCTION config_garde() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    usage_env text;
    manquants text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.statut <> 'BROUILLON' THEN
            RAISE EXCEPTION 'configuration % : seule une version BROUILLON peut être supprimée',
                OLD.version USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.statut = 'ARCHIVEE' THEN
        RAISE EXCEPTION 'configuration % archivée : immuable', OLD.version
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut = 'ACTIVE' THEN
        IF NEW.statut <> 'ARCHIVEE' OR ROW(NEW.libelle, NEW.m_bloc, NEW.m_alerte, NEW.p3,
               NEW.m_bloc_valide, NEW.m_alerte_valide, NEW.p3_valide, NEW.priorites_valide,
               NEW.mode_expiration, NEW.mode_expiration_valide, NEW.regle_cascade,
               NEW.regle_cascade_valide, NEW.auteur, NEW.active_par, NEW.date_activation)
           IS DISTINCT FROM ROW(OLD.libelle, OLD.m_bloc, OLD.m_alerte, OLD.p3,
               OLD.m_bloc_valide, OLD.m_alerte_valide, OLD.p3_valide, OLD.priorites_valide,
               OLD.mode_expiration, OLD.mode_expiration_valide, OLD.regle_cascade,
               OLD.regle_cascade_valide, OLD.auteur, OLD.active_par, OLD.date_activation) THEN
            RAISE EXCEPTION 'configuration % active : immuable (seul l''archivage est permis)',
                OLD.version USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    -- OLD.statut = 'BROUILLON'
    IF NEW.statut = 'ACTIVE' THEN
        IF NEW.m_bloc IS NULL OR NEW.m_alerte IS NULL OR NEW.p3 IS NULL
           OR NEW.mode_expiration IS NULL THEN
            RAISE EXCEPTION 'configuration % incomplète : activation refusée', NEW.version
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT string_agg(DISTINCT pl.libelle_priorite, ', ') INTO manquants
          FROM production_line pl
         WHERE NOT EXISTS (SELECT 1 FROM config_priority_rank r
                            WHERE r.version = NEW.version
                              AND r.libelle_priorite = pl.libelle_priorite);
        IF manquants IS NOT NULL THEN
            RAISE EXCEPTION 'configuration % : priorités sans rang (%)', NEW.version, manquants
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT usage INTO usage_env FROM environment;
        IF usage_env IS DISTINCT FROM 'TEST' AND NOT (NEW.m_bloc_valide AND NEW.m_alerte_valide
           AND NEW.p3_valide AND NEW.priorites_valide AND NEW.mode_expiration_valide
           AND NEW.regle_cascade_valide) THEN
            RAISE EXCEPTION 'configuration % : activation hors TEST refusée tant que tous les '
                'paramètres ne sont pas validés', NEW.version USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.active_par IS NULL OR NEW.date_activation IS NULL THEN
            RAISE EXCEPTION 'activation : auteur et date requis' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.statut = 'ARCHIVEE' THEN
        RAISE EXCEPTION 'un brouillon ne peut pas être archivé' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER config_garde BEFORE UPDATE OR DELETE ON allocation_configuration
    FOR EACH ROW EXECUTE FUNCTION config_garde();

CREATE FUNCTION config_rang_garde() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v bigint := coalesce(NEW.version, OLD.version);
BEGIN
    IF (SELECT statut FROM allocation_configuration WHERE version = v) <> 'BROUILLON' THEN
        RAISE EXCEPTION 'rangs de priorité de la configuration % : modifiables en BROUILLON seulement', v
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN coalesce(NEW, OLD);
END;
$$;

CREATE TRIGGER config_rang_garde BEFORE INSERT OR UPDATE OR DELETE ON config_priority_rank
    FOR EACH ROW EXECUTE FUNCTION config_rang_garde();

-------------------------------------------------------------------------------
-- Calculs (runs) et itérations
-------------------------------------------------------------------------------
CREATE TABLE allocation_run (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_run        date        NOT NULL,
    id_chaine_cible text        NOT NULL REFERENCES production_line (id_chaine),
    version_config  bigint      NOT NULL REFERENCES allocation_configuration (version),
    statut          text        NOT NULL CHECK (statut IN ('OUVERT', 'A_RECALCULER', 'CLOS')),
    cause_statut    text        NULL,
    cause_cloture   text        NULL CHECK (cause_cloture IN ('DECISION_RESPONSABLE', 'EXPIRATION')),
    motif_cloture   text        NULL,
    cree_par        bigint      NOT NULL REFERENCES app_user (id),
    date_creation   timestamptz NOT NULL DEFAULT now(),
    clos_par        bigint      NULL REFERENCES app_user (id),
    date_cloture    timestamptz NULL,
    version         integer     NOT NULL DEFAULT 1,
    UNIQUE (id, date_run),
    UNIQUE (id, date_run, id_chaine_cible),
    CONSTRAINT run_cloture CHECK ((statut = 'CLOS') = (date_cloture IS NOT NULL)
                                  AND (statut = 'CLOS') = (cause_cloture IS NOT NULL))
);

-- D9 (proposition par défaut) : un seul run non clos par (date, chaîne cible).
CREATE UNIQUE INDEX run_un_ouvert ON allocation_run (date_run, id_chaine_cible)
    WHERE statut <> 'CLOS';

CREATE TABLE allocation_iteration (
    id_run                  bigint      NOT NULL REFERENCES allocation_run (id),
    numero                  integer     NOT NULL CHECK (numero >= 1),
    declencheur             text        NOT NULL,
    date_calcul             timestamptz NOT NULL DEFAULT now(),
    instant_lecture         timestamptz NOT NULL,
    version_donnees         bigint      NOT NULL,
    nb_besoins_consideres   integer     NOT NULL,
    couverture_sequentielle integer     NOT NULL,
    couverture_maximale     integer     NOT NULL,
    alerte_combinaison      boolean     NOT NULL,
    combinaison_maximale    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id_run, numero),
    CONSTRAINT iteration_I15 CHECK (couverture_sequentielle <= couverture_maximale)
);

-------------------------------------------------------------------------------
-- Besoins
-------------------------------------------------------------------------------
CREATE TABLE replacement_request (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_run                  bigint NOT NULL,
    date                    date   NOT NULL,
    id_chaine_cible         text   NOT NULL,
    id_ouvrier_absent       text   NOT NULL REFERENCES worker (id_ouvrier),
    id_affectation_source   bigint NULL,
    id_absence_source       bigint NULL,
    code_poste              text   NOT NULL REFERENCES position (code_poste),
    id_exigence             bigint NULL REFERENCES position_requirement (id),
    code_competence_requise text   NULL REFERENCES skill (code_competence),
    code_niveau_min         text   NULL REFERENCES skill_level (code_niveau),
    est_critique            boolean NOT NULL,
    rang_traitement         integer NULL,
    statut_cycle            text   NOT NULL
                            CHECK (statut_cycle IN ('BLOQUE', 'A_TRAITER', 'EN_ATTENTE',
                                                    'POURVU', 'NON_POURVU')),
    cause_statut            text   NULL,
    id_besoin_precedent     bigint NULL,
    FOREIGN KEY (id_run, date, id_chaine_cible)
        REFERENCES allocation_run (id, date_run, id_chaine_cible),
    FOREIGN KEY (id_affectation_source, id_ouvrier_absent, date)
        REFERENCES daily_assignment (id, id_ouvrier, date),
    FOREIGN KEY (id_absence_source, id_ouvrier_absent) REFERENCES absence (id, id_ouvrier),
    UNIQUE (id_run, id_ouvrier_absent),
    UNIQUE (id, id_run),
    UNIQUE (id, date, id_ouvrier_absent),
    FOREIGN KEY (id_besoin_precedent, date, id_ouvrier_absent)
        REFERENCES replacement_request (id, date, id_ouvrier_absent),
    CONSTRAINT besoin_bloque CHECK (statut_cycle <> 'BLOQUE' OR cause_statut IS NOT NULL)
);

-- I11 : un seul besoin « vivant » par journée d'absence, tous runs confondus.
CREATE UNIQUE INDEX besoin_un_vivant ON replacement_request (date, id_ouvrier_absent)
    WHERE statut_cycle IN ('BLOQUE', 'A_TRAITER', 'EN_ATTENTE', 'POURVU');

-------------------------------------------------------------------------------
-- Évaluations (jamais modifiées)
-------------------------------------------------------------------------------
CREATE TABLE candidate_evaluation (
    id                bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_run            bigint  NOT NULL,
    numero            integer NOT NULL,
    id_besoin         bigint  NOT NULL,
    id_ouvrier        text    NOT NULL REFERENCES worker (id_ouvrier),
    eligible          boolean NOT NULL,
    premier_echec     text    NULL,
    risque            text    NULL CHECK (risque IN ('FAIBLE', 'ELEVE', 'BLOQUANT')),
    rang              integer NULL,
    ex_aequo          boolean NOT NULL DEFAULT false,
    chaine_donneuse   text    NULL REFERENCES production_line (id_chaine),
    poste_quitte      text    NULL REFERENCES position (code_poste),
    restants          integer NULL,
    explication       text    NOT NULL,
    details           jsonb   NOT NULL,
    FOREIGN KEY (id_run, numero) REFERENCES allocation_iteration (id_run, numero),
    FOREIGN KEY (id_besoin, id_run) REFERENCES replacement_request (id, id_run),
    UNIQUE (id_run, numero, id_besoin, id_ouvrier),
    UNIQUE (id, id_run, numero, id_besoin, id_ouvrier),
    CONSTRAINT evaluation_rang CHECK ((rang IS NOT NULL) = eligible),
    CONSTRAINT evaluation_eligible CHECK (NOT eligible OR (premier_echec IS NULL
                                          AND risque IN ('FAIBLE', 'ELEVE')))
);

-------------------------------------------------------------------------------
-- Propositions (portent la réservation)
-------------------------------------------------------------------------------
CREATE TABLE proposal (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_run            bigint      NOT NULL,
    numero            integer     NOT NULL,
    id_evaluation     bigint      NOT NULL,
    id_besoin         bigint      NOT NULL,
    id_ouvrier        text        NOT NULL,
    date              date        NOT NULL,
    id_ouvrier_absent text        NOT NULL,
    origine           text        NOT NULL DEFAULT 'CALCUL' CHECK (origine IN ('CALCUL', 'CHOIX')),
    statut            text        NOT NULL DEFAULT 'ACTIVE'
                      CHECK (statut IN ('ACTIVE', 'ACCEPTEE', 'REFUSEE', 'ANNULEE')),
    motif_annulation  text        NULL CHECK (motif_annulation IN (
                          'RECALCUL', 'SUBSTITUTION', 'CANDIDAT_REPRIS', 'NON_POURVU', 'CLOTURE',
                          'EXPIRATION', 'DONNEES_MODIFIEES')),
    id_decision_cause bigint      NULL,
    id_lot_cause      bigint      NULL REFERENCES import_batch (id),
    date_creation     timestamptz NOT NULL DEFAULT now(),
    date_acceptation  timestamptz NULL,
    date_fin          timestamptz NULL,
    FOREIGN KEY (id_evaluation, id_run, numero, id_besoin, id_ouvrier)
        REFERENCES candidate_evaluation (id, id_run, numero, id_besoin, id_ouvrier),
    FOREIGN KEY (id_besoin, date, id_ouvrier_absent)
        REFERENCES replacement_request (id, date, id_ouvrier_absent),
    UNIQUE (id, id_besoin),
    UNIQUE (id, date, id_ouvrier),
    UNIQUE (id, id_besoin, id_ouvrier, date, id_ouvrier_absent),
    CONSTRAINT proposition_fin CHECK ((statut = 'ACTIVE') = (date_fin IS NULL)),
    CONSTRAINT proposition_annulee CHECK ((statut = 'ANNULEE') = (motif_annulation IS NOT NULL)),
    CONSTRAINT proposition_acceptee CHECK ((statut = 'ACCEPTEE') = (date_acceptation IS NOT NULL))
);

CREATE UNIQUE INDEX proposition_active_par_besoin ON proposal (id_besoin) WHERE statut = 'ACTIVE';
CREATE UNIQUE INDEX proposition_active_par_ouvrier ON proposal (date, id_ouvrier)
    WHERE statut = 'ACTIVE';

-------------------------------------------------------------------------------
-- Décisions humaines (journal non modifiable)
-------------------------------------------------------------------------------
CREATE TABLE allocation_decision (
    id                     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_besoin              bigint      NOT NULL,
    id_run                 bigint      NOT NULL,
    numero                 integer     NULL,
    type                   text        NOT NULL CHECK (type IN (
                               'ACCEPTER', 'REFUSER', 'LAISSER_NON_POURVU',
                               'ANNULER_REMPLACEMENT', 'CONFIRMER_APRES_REIMPORT', 'CLOTURER')),
    id_proposal            bigint      NULL,
    id_remplacement        bigint      NULL,
    exclure_ouvrier        boolean     NULL,
    motif                  text        NULL,
    auteur                 bigint      NOT NULL REFERENCES app_user (id),
    horodatage             timestamptz NOT NULL DEFAULT now(),
    usage_environnement    text        NOT NULL CHECK (usage_environnement IN ('TEST', 'EXPLOITATION')),
    configuration_validee  boolean     NOT NULL,
    FOREIGN KEY (id_besoin, id_run) REFERENCES replacement_request (id, id_run),
    FOREIGN KEY (id_proposal, id_besoin) REFERENCES proposal (id, id_besoin),
    UNIQUE (id, id_besoin),
    CONSTRAINT decision_motif CHECK (type IN ('ACCEPTER') OR btrim(coalesce(motif, '')) <> ''),
    CONSTRAINT decision_proposition CHECK (
        type NOT IN ('ACCEPTER', 'REFUSER') OR id_proposal IS NOT NULL),
    CONSTRAINT decision_remplacement CHECK (
        type NOT IN ('ANNULER_REMPLACEMENT', 'CONFIRMER_APRES_REIMPORT')
        OR id_remplacement IS NOT NULL),
    CONSTRAINT decision_exclusion CHECK (
        (type = 'ANNULER_REMPLACEMENT') = (exclure_ouvrier IS NOT NULL))
);

CREATE UNIQUE INDEX decision_une_annulation ON allocation_decision (id_remplacement)
    WHERE type = 'ANNULER_REMPLACEMENT';

ALTER TABLE proposal ADD FOREIGN KEY (id_decision_cause) REFERENCES allocation_decision (id);

-------------------------------------------------------------------------------
-- Remplacements confirmés
-------------------------------------------------------------------------------
CREATE TABLE replacement_assignment (
    id                   bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_besoin            bigint      NOT NULL,
    id_proposal          bigint      NOT NULL UNIQUE,
    id_ouvrier           text        NOT NULL,
    date                 date        NOT NULL,
    id_ouvrier_absent    text        NOT NULL,
    id_decision_creation bigint      NOT NULL UNIQUE,
    statut               text        NOT NULL DEFAULT 'ACTIF' CHECK (statut IN ('ACTIF', 'ANNULE')),
    statut_revue         text        NOT NULL DEFAULT 'OK' CHECK (statut_revue IN ('OK', 'A_REVOIR')),
    id_lot_revue         bigint      NULL REFERENCES import_batch (id),
    cause_revue          text        NULL,
    date_revue           timestamptz NULL,
    date_annulation      timestamptz NULL,
    FOREIGN KEY (id_proposal, id_besoin, id_ouvrier, date, id_ouvrier_absent)
        REFERENCES proposal (id, id_besoin, id_ouvrier, date, id_ouvrier_absent),
    FOREIGN KEY (id_decision_creation, id_besoin) REFERENCES allocation_decision (id, id_besoin),
    UNIQUE (id, id_besoin),
    UNIQUE (id, id_proposal, date, id_ouvrier),
    CONSTRAINT remplacement_annule CHECK ((statut = 'ANNULE') = (date_annulation IS NOT NULL)),
    CONSTRAINT remplacement_revue CHECK ((statut_revue = 'A_REVOIR') = (cause_revue IS NOT NULL))
);

CREATE UNIQUE INDEX remplacement_actif_par_ouvrier ON replacement_assignment (date, id_ouvrier)
    WHERE statut = 'ACTIF';
CREATE UNIQUE INDEX remplacement_actif_par_absent ON replacement_assignment (date, id_ouvrier_absent)
    WHERE statut = 'ACTIF';
CREATE UNIQUE INDEX remplacement_actif_par_besoin ON replacement_assignment (id_besoin)
    WHERE statut = 'ACTIF';

ALTER TABLE allocation_decision ADD FOREIGN KEY (id_remplacement, id_besoin)
    REFERENCES replacement_assignment (id, id_besoin);

-------------------------------------------------------------------------------
-- Registre d'engagement : un créneau courant par (date, ouvrier), tous runs confondus (I13)
-------------------------------------------------------------------------------
CREATE TABLE worker_day_slot (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            date        NOT NULL,
    id_ouvrier      text        NOT NULL,
    type            text        NOT NULL CHECK (type IN ('RESERVE', 'ENGAGE')),
    id_proposal     bigint      NOT NULL UNIQUE,
    id_remplacement bigint      NULL,
    statut          text        NOT NULL DEFAULT 'COURANT' CHECK (statut IN ('COURANT', 'FERME')),
    date_ouverture  timestamptz NOT NULL DEFAULT now(),
    date_conversion timestamptz NULL,
    date_fermeture  timestamptz NULL,
    motif_fermeture text        NULL,
    FOREIGN KEY (id_proposal, date, id_ouvrier) REFERENCES proposal (id, date, id_ouvrier),
    FOREIGN KEY (id_remplacement, id_proposal, date, id_ouvrier)
        REFERENCES replacement_assignment (id, id_proposal, date, id_ouvrier),
    CONSTRAINT creneau_engage CHECK ((type = 'ENGAGE') = (id_remplacement IS NOT NULL)),
    CONSTRAINT creneau_ferme CHECK ((statut = 'FERME') = (date_fermeture IS NOT NULL))
);

CREATE UNIQUE INDEX creneau_un_courant ON worker_day_slot (date, id_ouvrier)
    WHERE statut = 'COURANT';

-------------------------------------------------------------------------------
-- Gardes de transition (défense en profondeur ; les services appliquent les mêmes règles)
-------------------------------------------------------------------------------
CREATE FUNCTION immuable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% : ligne non modifiable', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER decision_immuable BEFORE UPDATE OR DELETE ON allocation_decision
    FOR EACH ROW EXECUTE FUNCTION immuable();
CREATE TRIGGER evaluation_immuable BEFORE UPDATE OR DELETE ON candidate_evaluation
    FOR EACH ROW EXECUTE FUNCTION immuable();
CREATE TRIGGER iteration_immuable BEFORE UPDATE OR DELETE ON allocation_iteration
    FOR EACH ROW EXECUTE FUNCTION immuable();

CREATE FUNCTION proposal_garde() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.statut <> 'ACTIVE' THEN
        RAISE EXCEPTION 'proposition % : % interdit (statut %)', OLD.id, TG_OP, OLD.statut
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION creneau_garde() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.statut = 'FERME' OR (OLD.type = 'ENGAGE' AND NEW.type = 'RESERVE') THEN
        RAISE EXCEPTION 'créneau % : transition interdite', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION remplacement_garde() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.statut = 'ANNULE' THEN
        RAISE EXCEPTION 'remplacement % : modification interdite (statut %)', OLD.id, OLD.statut
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION run_garde() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.statut = 'CLOS' THEN
        RAISE EXCEPTION 'run % : modification interdite (statut %)', OLD.id, OLD.statut
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER proposal_transition BEFORE UPDATE OR DELETE ON proposal
    FOR EACH ROW EXECUTE FUNCTION proposal_garde();
CREATE TRIGGER creneau_transition BEFORE UPDATE OR DELETE ON worker_day_slot
    FOR EACH ROW EXECUTE FUNCTION creneau_garde();
CREATE TRIGGER remplacement_transition BEFORE UPDATE OR DELETE ON replacement_assignment
    FOR EACH ROW EXECUTE FUNCTION remplacement_garde();
CREATE TRIGGER run_transition BEFORE UPDATE OR DELETE ON allocation_run
    FOR EACH ROW EXECUTE FUNCTION run_garde();

-------------------------------------------------------------------------------
-- Droits du rôle applicatif
-------------------------------------------------------------------------------
GRANT SELECT ON allocation_configuration, config_priority_rank, allocation_run,
                allocation_iteration, replacement_request, candidate_evaluation, proposal,
                allocation_decision, replacement_assignment, worker_day_slot TO agent_tag_app;
GRANT INSERT ON allocation_run, allocation_iteration, replacement_request, candidate_evaluation,
                proposal, allocation_decision, replacement_assignment, worker_day_slot
    TO agent_tag_app;
GRANT UPDATE (statut, cause_statut, cause_cloture, motif_cloture, clos_par, date_cloture, version)
    ON allocation_run TO agent_tag_app;
GRANT UPDATE (statut_cycle, cause_statut, rang_traitement) ON replacement_request TO agent_tag_app;
GRANT UPDATE (statut, motif_annulation, id_decision_cause, id_lot_cause, date_acceptation, date_fin)
    ON proposal TO agent_tag_app;
GRANT UPDATE (type, id_remplacement, statut, date_conversion, date_fermeture, motif_fermeture)
    ON worker_day_slot TO agent_tag_app;
GRANT UPDATE (statut, statut_revue, id_lot_revue, cause_revue, date_revue, date_annulation)
    ON replacement_assignment TO agent_tag_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO agent_tag_app;
