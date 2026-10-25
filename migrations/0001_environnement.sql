-- 0001 — Environnement de la base (Phase 4.1, correction 1 ; Phase 4.2, point 3)
-- Une base = un seul environnement, dont l'usage (TEST / EXPLOITATION) est fixé à la création.
-- Convention : le rôle applicatif s'appelle agent_tag_app.

CREATE TABLE environment (
    id_environnement uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    ligne_unique     boolean     NOT NULL DEFAULT true,
    usage            text        NOT NULL,
    libelle          text        NOT NULL,
    fuseau_horaire   text        NULL,          -- à renseigner, jamais déduit
    date_creation    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT environment_ligne_unique UNIQUE (ligne_unique),
    CONSTRAINT environment_ligne_unique_vraie CHECK (ligne_unique),
    CONSTRAINT environment_usage_valide CHECK (usage IN ('TEST', 'EXPLOITATION')),
    CONSTRAINT environment_libelle_non_vide CHECK (btrim(libelle) <> '')
);

COMMENT ON TABLE environment IS
    'Identité et usage de la base. Une seule ligne. Usage et identifiant immuables.';

-- Immuabilité de l'identité et de l'usage ; suppression interdite ;
-- validation du fuseau horaire lorsqu'il est renseigné.
CREATE FUNCTION environment_garde() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'environment : suppression interdite'
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.id_environnement IS DISTINCT FROM OLD.id_environnement
           OR NEW.usage IS DISTINCT FROM OLD.usage
           OR NEW.date_creation IS DISTINCT FROM OLD.date_creation
           OR NEW.ligne_unique IS DISTINCT FROM OLD.ligne_unique THEN
            RAISE EXCEPTION 'environment : identifiant, usage et date de création sont immuables'
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;

    IF NEW.fuseau_horaire IS NOT NULL THEN
        BEGIN
            PERFORM now() AT TIME ZONE NEW.fuseau_horaire;
        EXCEPTION WHEN invalid_parameter_value THEN
            RAISE EXCEPTION 'environment : fuseau horaire inconnu : %', NEW.fuseau_horaire
                USING ERRCODE = 'check_violation';
        END;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER environment_garde
    BEFORE INSERT OR UPDATE OR DELETE ON environment
    FOR EACH ROW EXECUTE FUNCTION environment_garde();

-- Le rôle applicatif lit l'environnement mais ne peut ni le créer ni le modifier.
GRANT USAGE ON SCHEMA public TO agent_tag_app;
GRANT SELECT ON environment TO agent_tag_app;
