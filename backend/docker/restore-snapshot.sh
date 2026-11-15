#!/bin/sh
# Called by the PostgreSQL image ONLY on a fresh volume; no API migrations here.
set -eu
pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" /backup/source.backup
