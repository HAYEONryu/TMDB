#!/bin/sh
# New EMPTY databases only. Never run against an existing development/demo DB.
set -eu
TM_APP_DB_PASSWORD="$(cat "${TM_APP_DB_PASSWORD_FILE:-/run/secrets/app_db_password}")"
export TM_APP_DB_PASSWORD
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password TM_APP_DB_PASSWORD
\getenv target_db POSTGRES_DB
CREATE ROLE tm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
SELECT format('ALTER ROLE tm_app PASSWORD %L', :'app_password') \gexec
GRANT CONNECT, TEMPORARY ON DATABASE :"target_db" TO tm_app;
GRANT USAGE, CREATE ON SCHEMA public TO tm_app;
SQL
unset TM_APP_DB_PASSWORD
