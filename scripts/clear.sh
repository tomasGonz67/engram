#!/bin/bash
# Resets Postgres and Qdrant together so they can never drift out of sync with
# each other (e.g. a memory existing as a vector in Qdrant with no matching
# metadata row in Postgres, or vice versa). Does NOT touch the hf_cache volume
# — no reason to force a re-download of the embedding model.
#
# Destructive — dev only. Refuses to run if the ENVIRONMENT value baked into
# docker-compose-dev.yml resolves to 'production'. The compose file is the
# source of truth, not a host shell variable — there's no production
# deployment yet, but if/when one exists, whatever compose file it uses should
# set ENVIRONMENT=production so this can never be pointed at it by mistake.
set -e

cd "$(dirname "$0")/.."

COMPOSE_ENV=$(docker compose -f docker-compose-dev.yml config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['backend']['environment'].get('ENVIRONMENT',''))")

if [ "$COMPOSE_ENV" = "production" ]; then
    echo "Refusing to run: docker-compose-dev.yml resolves ENVIRONMENT to 'production'. This script destroys all data and is for dev use only."
    exit 1
fi

echo "Stopping dev containers..."
docker compose -f docker-compose-dev.yml down

echo "Removing Postgres and Qdrant volumes..."
docker volume rm engram_postgres_data engram_qdrant_data 2>/dev/null || true

echo "Starting dev environment fresh..."
docker compose -f docker-compose-dev.yml up -d

echo "Done — Postgres and Qdrant are both reset and back in sync."
