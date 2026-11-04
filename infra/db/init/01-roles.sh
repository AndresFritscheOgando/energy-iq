#!/bin/sh
# Create the EnergyIQ roles and databases on a fresh volume (spec 0009/0001 AC-1).
# Table privileges are not granted here: every Alembic revision grants its own,
# so rebuilt and scratch databases end up with the same privileges.
set -eu

: "${ENERGYIQ_MIGRATOR_PASSWORD:?ENERGYIQ_MIGRATOR_PASSWORD must be set in infra/.env}"
: "${ENERGYIQ_APP_PASSWORD:?ENERGYIQ_APP_PASSWORD must be set in infra/.env}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v migrator_password="$ENERGYIQ_MIGRATOR_PASSWORD" \
  -v app_password="$ENERGYIQ_APP_PASSWORD" <<'SQL'
CREATE ROLE energyiq_migrator LOGIN CREATEDB PASSWORD :'migrator_password';
CREATE ROLE energyiq_app LOGIN PASSWORD :'app_password';

CREATE DATABASE energyiq_dev OWNER energyiq_migrator;
CREATE DATABASE energyiq_test OWNER energyiq_migrator;

REVOKE ALL ON DATABASE energyiq_dev FROM PUBLIC;
REVOKE ALL ON DATABASE energyiq_test FROM PUBLIC;
GRANT CONNECT ON DATABASE energyiq_dev TO energyiq_app;
GRANT CONNECT ON DATABASE energyiq_test TO energyiq_app;
SQL

for db in energyiq_dev energyiq_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<'SQL'
ALTER SCHEMA public OWNER TO energyiq_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO energyiq_app;
SQL
done
