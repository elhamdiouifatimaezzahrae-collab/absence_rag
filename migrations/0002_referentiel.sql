-- 0002 — Référentiel, utilisateurs et lots d'import (Phase 4 B1, B2 ; 4.1 corr. 4 ; 4.2 point 8)
-- Le référentiel est importé une seule fois en V1 (D15) et n'est pas modifiable par l'application,
-- sauf position_requirement (saisies d'exigence, incréments suivants).

-------------------------------------------------------------------------------
-- Utilisateurs (D14 ouverte : la liste des rôles n'est pas contrainte)
-------------------------------------------------------------------------------
CREATE TABLE app_user (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identifiant   text        NOT NULL UNIQUE CHECK (btrim(identifiant) <> ''),
    nom           text        NOT NULL CHECK (btrim(nom) <> ''),
    role          text        NOT NULL CHECK (btrim(role) <> ''),
    actif         boolean     NOT NULL DEFAULT true,
    date_creation timestamptz NOT NULL DEFAULT now()
);

-------------------------------------------------------------------------------
-- Lots d'import ou de saisie
-------------------------------------------------------------------------------
CREATE TABLE import_batch (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type              text        NOT NULL CHECK (type IN ('IMPORT', 'SAISIE')),
    perimetre         text        NOT NULL CHECK (perimetre IN ('REFERENTIEL', 'JOURNALIER')),
    fichier_source    text        NULL,
    empreinte_fichier char(64)    NULL CHECK (empreinte_fichier ~ '^[0-9a-f]{64}$'),
    reference_archive text        NULL,
    horodatage        timestamptz NOT NULL DEFAULT now(),
    auteur            bigint      NOT NULL REFERENCES app_user (id),
    statut            text        NOT NULL
                      CHECK (statut IN ('EN_ATTENTE_VALIDATION', 'APPLIQUE', 'REJETE')),
    date_application  timestamptz NULL,
    date_rejet        timestamptz NULL,
    valide_par        bigint      NULL REFERENCES app_user (id),
    rapport           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT import_fichier_obligatoire
        CHECK (type <> 'IMPORT' OR (fichier_source IS NOT NULL AND empreinte_fichier IS NOT NULL)),
    CONSTRAINT import_date_application
        CHECK ((statut = 'APPLIQUE') = (date_application IS NOT NULL)),
    CONSTRAINT import_date_rejet
        CHECK ((statut = 'REJETE') = (date_rejet IS NOT NULL))
);

-- D15 : un seul référentiel appliqué en V1.
CREATE UNIQUE INDEX import_un_referentiel_applique
    ON import_batch (perimetre) WHERE perimetre = 'REFERENTIEL' AND statut = 'APPLIQUE';
-- Un même fichier n'est jamais appliqué deux fois pour un même périmètre.
CREATE UNIQUE INDEX import_fichier_applique_une_fois
    ON import_batch (perimetre, empreinte_fichier) WHERE statut = 'APPLIQUE';

-------------------------------------------------------------------------------
-- Niveaux de compétence (ordre validé : R5)
-------------------------------------------------------------------------------
CREATE TABLE skill_level (
    code_niveau text    PRIMARY KEY CHECK (code_niveau ~ '^[A-Z_]+$'),
    libelle     text    NOT NULL UNIQUE,
    rang        integer NOT NULL UNIQUE CHECK (rang > 0)
);

INSERT INTO skill_level (code_niveau, libelle, rang) VALUES
    ('DEBUTANT',      'Débutant',      1),
    ('INTERMEDIAIRE', 'Intermédiaire', 2),
    ('EXPERT',        'Expert',        3);

-------------------------------------------------------------------------------
-- Compétences, postes, chaînes
-------------------------------------------------------------------------------
CREATE TABLE skill (
    code_competence text   PRIMARY KEY CHECK (code_competence ~ '^[A-Z0-9_]+$'),
    libelle         text   NOT NULL UNIQUE CHECK (btrim(libelle) <> ''),
    id_lot_import   bigint NOT NULL REFERENCES import_batch (id)
);

CREATE TABLE position (
    code_poste               text    PRIMARY KEY CHECK (code_poste ~ '^[A-Z0-9_]+$'),
    libelle                  text    NOT NULL UNIQUE CHECK (btrim(libelle) <> ''),
    code_competence_associee text    NULL REFERENCES skill (code_competence),
    source_correspondance    text    NULL CHECK (source_correspondance IN ('BESOINS_POSTES', 'DEDUITE')),
    correspondance_validee   boolean NOT NULL DEFAULT false,
    id_lot_import            bigint  NOT NULL REFERENCES import_batch (id),
    CONSTRAINT position_source_si_correspondance
        CHECK ((code_competence_associee IS NULL) = (source_correspondance IS NULL)),
    CONSTRAINT position_validee_si_correspondance
        CHECK (NOT correspondance_validee OR code_competence_associee IS NOT NULL)
);

CREATE TABLE production_line (
    id_chaine            text    PRIMARY KEY CHECK (btrim(id_chaine) <> ''),
    produit              text    NOT NULL UNIQUE CHECK (btrim(produit) <> ''),
    effectif_necessaire  integer NOT NULL CHECK (effectif_necessaire >= 0),
    effectif_planifie    integer NOT NULL CHECK (effectif_planifie >= 0),
    libelle_priorite     text    NOT NULL CHECK (btrim(libelle_priorite) <> ''),
    capacite_journaliere integer NOT NULL CHECK (capacite_journaliere >= 0),
    id_lot_import        bigint  NOT NULL REFERENCES import_batch (id)
);

CREATE TABLE line_critical_skill (
    id_chaine       text   NOT NULL REFERENCES production_line (id_chaine),
    code_competence text   NOT NULL REFERENCES skill (code_competence),
    id_lot_import   bigint NOT NULL REFERENCES import_batch (id),
    PRIMARY KEY (id_chaine, code_competence)
);

-------------------------------------------------------------------------------
-- Ouvriers et compétences détenues
-------------------------------------------------------------------------------
CREATE TABLE worker (
    id_ouvrier           text   PRIMARY KEY CHECK (btrim(id_ouvrier) <> ''),
    nom                  text   NOT NULL CHECK (btrim(nom) <> ''),   -- non unique : homonymes
    id_chaine_origine    text   NOT NULL REFERENCES production_line (id_chaine),
    code_poste_principal text   NOT NULL REFERENCES position (code_poste),
    heure_debut          time   NOT NULL,
    heure_fin            time   NOT NULL,
    statut_source        text   NULL,   -- conservé tel qu'importé, jamais utilisé (R6)
    id_lot_import        bigint NOT NULL REFERENCES import_batch (id),
    CONSTRAINT worker_horaire_ordonne CHECK (heure_fin > heure_debut)
);

CREATE TABLE worker_skill (
    id_ouvrier         text    NOT NULL REFERENCES worker (id_ouvrier),
    code_competence    text    NOT NULL REFERENCES skill (code_competence),
    type_competence    text    NOT NULL CHECK (type_competence IN ('PRINCIPALE', 'SECONDAIRE')),
    annees_experience  integer NOT NULL CHECK (annees_experience > 0),
    code_niveau        text    NOT NULL REFERENCES skill_level (code_niveau),
    certification      boolean NOT NULL,
    id_lot_import      bigint  NOT NULL REFERENCES import_batch (id),
    PRIMARY KEY (id_ouvrier, code_competence)
);

CREATE UNIQUE INDEX worker_skill_une_principale
    ON worker_skill (id_ouvrier) WHERE type_competence = 'PRINCIPALE';

-- Contrôle différé (fin de transaction) : chaque ouvrier a exactement une compétence principale,
-- et elle correspond à la compétence associée à son poste principal lorsque celle-ci est connue.
CREATE FUNCTION controle_ouvrier(p_id text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    n_principales integer;
    comp_principale text;
    comp_poste text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM worker WHERE id_ouvrier = p_id) THEN
        RETURN;
    END IF;
    SELECT count(*), min(code_competence) INTO n_principales, comp_principale
      FROM worker_skill WHERE id_ouvrier = p_id AND type_competence = 'PRINCIPALE';
    IF n_principales <> 1 THEN
        RAISE EXCEPTION 'ouvrier % : % compétence(s) principale(s), exactement 1 attendue',
            p_id, n_principales USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.code_competence_associee INTO comp_poste
      FROM worker w JOIN position p ON p.code_poste = w.code_poste_principal
     WHERE w.id_ouvrier = p_id;
    IF comp_poste IS NOT NULL AND comp_poste <> comp_principale THEN
        RAISE EXCEPTION 'ouvrier % : compétence principale % différente de celle du poste (%)',
            p_id, comp_principale, comp_poste USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

CREATE FUNCTION trg_controle_ouvrier() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM controle_ouvrier(OLD.id_ouvrier);
    ELSE
        PERFORM controle_ouvrier(NEW.id_ouvrier);
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER worker_controle
    AFTER INSERT OR UPDATE ON worker
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_controle_ouvrier();

CREATE CONSTRAINT TRIGGER worker_skill_controle
    AFTER INSERT OR UPDATE OR DELETE ON worker_skill
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_controle_ouvrier();

-------------------------------------------------------------------------------
-- Exigences de poste, versionnées (R2, R3)
-------------------------------------------------------------------------------
CREATE TABLE position_requirement (
    id                     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_chaine              text        NOT NULL REFERENCES production_line (id_chaine),
    code_poste             text        NOT NULL REFERENCES position (code_poste),
    version                integer     NOT NULL CHECK (version >= 1),
    code_competence_requise text       NOT NULL REFERENCES skill (code_competence),
    code_niveau_min        text        NULL REFERENCES skill_level (code_niveau),  -- vide : besoin Bloqué
    nombre_requis          integer     NULL CHECK (nombre_requis >= 0),           -- informatif
    origine                text        NOT NULL CHECK (origine IN ('EXCEL', 'SAISIE')),
    statut                 text        NOT NULL CHECK (statut IN ('ACTIVE', 'REMPLACEE')),
    id_lot_import          bigint      NULL REFERENCES import_batch (id),
    auteur                 bigint      NULL REFERENCES app_user (id),
    date_saisie            timestamptz NULL,
    motif                  text        NULL,
    debut_validite         timestamptz NOT NULL DEFAULT now(),
    fin_validite           timestamptz NULL,
    CONSTRAINT exigence_version_unique UNIQUE (id_chaine, code_poste, version),
    CONSTRAINT exigence_origine_excel CHECK (origine <> 'EXCEL' OR id_lot_import IS NOT NULL),
    CONSTRAINT exigence_origine_saisie CHECK (
        origine <> 'SAISIE'
        OR (auteur IS NOT NULL AND date_saisie IS NOT NULL AND btrim(coalesce(motif, '')) <> '')),
    CONSTRAINT exigence_validite CHECK ((statut = 'ACTIVE') = (fin_validite IS NULL)),
    CONSTRAINT exigence_periode CHECK (fin_validite IS NULL OR fin_validite >= debut_validite)
);

CREATE UNIQUE INDEX exigence_une_active
    ON position_requirement (id_chaine, code_poste) WHERE statut = 'ACTIVE';

-------------------------------------------------------------------------------
-- Droits : l'application lit tout, insère le référentiel lors de l'import,
-- ne modifie ni ne supprime rien.
-------------------------------------------------------------------------------
GRANT SELECT ON app_user, import_batch, skill_level, skill, position, production_line,
                line_critical_skill, worker, worker_skill, position_requirement
    TO agent_tag_app;
GRANT INSERT ON import_batch, skill, position, production_line, line_critical_skill,
                worker, worker_skill, position_requirement
    TO agent_tag_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO agent_tag_app;
