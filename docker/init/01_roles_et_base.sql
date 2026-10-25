-- Création des rôles et de la base de TEST d'Agent TAG.
-- À exécuter UNE FOIS avec un compte superutilisateur PostgreSQL :
--   psql -h localhost -p <port> -U postgres -f docker/init/01_roles_et_base.sql
-- (exécuté automatiquement par docker-compose au premier démarrage du conteneur)
--
-- Mots de passe de TEST uniquement, publiés dans ce dépôt : ils ne protègent rien.
-- Ne jamais les réutiliser en EXPLOITATION ni sur un serveur accessible depuis le réseau.

CREATE ROLE agent_tag_owner LOGIN PASSWORD 'owner_test' CREATEDB;  -- CREATEDB : tests (bases jetables)
CREATE ROLE agent_tag_app   LOGIN PASSWORD 'app_test';

CREATE DATABASE agent_tag_test OWNER agent_tag_owner TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE agent_tag_test FROM PUBLIC;
GRANT CONNECT ON DATABASE agent_tag_test TO agent_tag_app;
