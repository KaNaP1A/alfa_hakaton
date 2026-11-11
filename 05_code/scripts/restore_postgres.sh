#!/usr/bin/env sh
# Run from 05_code after configuring .env. Restore only into a new empty database.
set -eu
docker compose up -d --wait db
count=$(docker compose exec -T db psql -U alfa -d alfa -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
if [ "$count" != "0" ]; then
  echo 'Database is not empty. Refusing to overwrite it.' >&2
  exit 1
fi
docker compose exec -T db pg_restore --host=localhost --username=alfa --dbname=alfa \
  --no-owner --no-privileges --exit-on-error --single-transaction \
  /input/alfa_course_hackathon.backup
