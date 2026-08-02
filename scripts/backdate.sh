#!/bin/bash
# Spreads every memory's created_at/last_reinforced_at across a realistic
# range (0-3 years back) instead of everything looking freshly created right
# after a seed.py run — see techDebt.md. Both columns get set to the same
# randomly-generated timestamp per row, matching how a never-reinforced
# memory's last_reinforced_at already equals its created_at by default (see
# database.py's insert_memory) — this just moves that shared timestamp back
# in time instead of leaving it at "now".
#
# Dev only, same guard as clear.sh. Refuses to run if the ENVIRONMENT value
# baked into docker-compose-dev.yml resolves to 'production'. The compose
# file is the source of truth, not a host shell variable — there's no
# production deployment yet, but if/when one exists, whatever compose file
# it uses should set ENVIRONMENT=production so this can never be pointed at
# it by mistake. Also structurally can't reach prod even without this check:
# prod Postgres will be Neon (see prod.md), not a local container, so
# `docker compose exec postgres` has nothing to exec into there at all.
set -e

cd "$(dirname "$0")/.."

COMPOSE_ENV=$(docker compose -f docker-compose-dev.yml config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['backend']['environment'].get('ENVIRONMENT',''))")

if [ "$COMPOSE_ENV" = "production" ]; then
    echo "Refusing to run: docker-compose-dev.yml resolves ENVIRONMENT to 'production'. This script is for dev use only."
    exit 1
fi

echo "Backdating memories to a realistic spread of ages..."
docker compose -f docker-compose-dev.yml exec -T postgres psql -U engram_user -d engram_db -c "
UPDATE memories m
SET created_at = sub.new_time,
    last_reinforced_at = sub.new_time
FROM (
    SELECT id, NOW() - (random() * INTERVAL '1095 days') AS new_time
    FROM memories
) sub
WHERE m.id = sub.id;
"

echo "Done — timestamps spread across the last ~3 years."
