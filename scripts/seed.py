#!/usr/bin/env python3
"""
Seeds the running Masi Memory API with mock memories, for testing search/ranking
at a more realistic scale. Talks to the real HTTP API (POST /memories) —
same code path a real client would use, not a shortcut around the system.

Usage:
    python3 scripts/seed.py

Requires the dev environment to already be running (see DEVELOPMENT.md).

Reads scripts/seed_data.json — a flat list of {text, impact, created_at}
objects, the single canonical dataset also used by scripts/backdate.sh
(which applies each entry's created_at afterward via direct SQL, matched
by text — see backdate.sh for why created_at can't be set through this
script itself). impact and created_at are both hand-assigned per memory
here, not randomly generated — impact reflects each memory's actual
content (a significant event vs. a mundane one), and created_at reflects
a real, internally consistent timeline (e.g. a pet's acquisition predates
its death), not a random offset within a coarse category range. See
scripts.md.

Note: every seeded memory starts with use_count=0 — this exercises
semantic relevance and impact/stability variation out of the box
(retrieval has no threshold filtering anymore — see architecture.md's
"How Retrieval Works" for why). Reinforcement (use_count/stability
growth) only happens through real use — either
memory_operations.reinforce_memory() called directly, or /generate's
model actually citing a memory — not from seeding. See architecture.md.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "http://localhost:8000/memories"
SEED_DATA_PATH = Path(__file__).resolve().parent / "seed_data.json"

def _load_admin_bypass_token():
    """ADMIN_BYPASS_TOKEN, sent as X-Admin-Bypass-Token on every request so
    this script's requests don't get rate-limited the same way a real
    anonymous caller would be — see backend/rate_limit.py and
    security-preventions.md. Not required: without it, seeding just runs
    into the normal 20/5min limit like anyone else, same code path, just
    slower.

    An already-exported shell env var wins if present. Otherwise, since
    this script runs on the host (not inside the backend container),
    falls back to reading .env directly — docker-compose reads .env for
    its own variable substitution into the container, it doesn't export
    it to the host shell, so os.getenv() alone wouldn't see it here."""
    token = os.getenv("ADMIN_BYPASS_TOKEN")
    if token:
        return token
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.strip().startswith("ADMIN_BYPASS_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

ADMIN_BYPASS_TOKEN = _load_admin_bypass_token()

def load_seed_data():
    with open(SEED_DATA_PATH) as f:
        return json.load(f)

def seed():
    memories = load_seed_data()
    total = len(memories)
    print(f"Seeding {total} memories against {API_URL}...")
    succeeded = 0
    failed = 0
    for i, memory in enumerate(memories, start=1):
        # Only text/impact go through the real API — created_at is
        # deliberately not part of MemoryInput (see dataModel.md and
        # security-preventions.md); scripts/backdate.sh applies it
        # afterward via direct SQL, matched by text.
        payload = json.dumps({"text": memory["text"], "impact": memory["impact"]}).encode()
        headers = {"Content-Type": "application/json"}
        if ADMIN_BYPASS_TOKEN:
            headers["X-Admin-Bypass-Token"] = ADMIN_BYPASS_TOKEN
        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
            succeeded += 1
            print(f"  [{i}/{total}] impact={memory['impact']:.2f} — {memory['text']}")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            failed += 1
            print(f"  [{i}/{total}] FAILED ({e}) — {memory['text']}")

    print(f"\nDone: {succeeded} succeeded, {failed} failed.")
    if succeeded:
        print("Run scripts/backdate.sh next to apply each memory's created_at.")


if __name__ == "__main__":
    seed()
