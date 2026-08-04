#!/bin/bash
# Applies each memory's hand-assigned created_at from scripts/seed_data.json
# — the same canonical dataset scripts/seed.py reads for text/impact. Run
# this after seed.py. Matches rows by text (not id, since ids are
# server-generated and change on every reseed — same reasoning
# evaluation/evaluate_retrieval.py's fixture already relies on).
#
# created_at can't be set through the public API at all (see dataModel.md,
# security-preventions.md) — MemoryInput doesn't expose it, by design, so a
# real caller can never backdate their own memories. This script bypasses
# that the same way its predecessor did: direct SQL against Postgres, not
# through the app.
#
# Both created_at and last_reinforced_at get set to the same value per row,
# matching how a never-reinforced memory naturally has them equal by
# default (see database.py's insert_memory()).
#
# Supersedes the old memory_type-keyed, category-random-range version: each
# memory now gets an exact, individually-chosen date instead of a random
# offset within a coarse childhood/teen/young_adult bucket. This also
# resolves the narrative-ordering gap the old approach had (see
# techDebt.md) — dates are chosen with real chronological dependencies in
# mind (e.g. a pet's acquisition predates its death) rather than assigned
# independently per row.
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

echo "Backdating memories to their hand-assigned created_at from scripts/seed_data.json..."

# Builds a single UPDATE ... FROM (VALUES ...) statement — one round trip
# regardless of dataset size, not one UPDATE per memory. Escapes single
# quotes the standard SQL way (doubling them) since memory text legitimately
# contains apostrophes (e.g. possessives) — string-building this by hand in
# bash would be exactly the kind of thing that quietly breaks on real data.
SQL=$(python3 -c "
import json

with open('scripts/seed_data.json') as f:
    memories = json.load(f)

def escape(s):
    return s.replace(\"'\", \"''\")

values = ',\n    '.join(
    f\"('{escape(m['text'])}', '{m['created_at']}'::timestamptz)\"
    for m in memories
)

print(f'''
UPDATE memories m
SET created_at = v.created_at,
    last_reinforced_at = v.created_at
FROM (VALUES
    {values}
) AS v(text, created_at)
WHERE m.text = v.text;
''')
")

docker compose -f docker-compose-dev.yml exec -T postgres psql -U engram_user -d engram_db -c "$SQL"

echo "Done — created_at/last_reinforced_at applied per memory from scripts/seed_data.json."
