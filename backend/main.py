import asyncio
import os
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from qdrant_client.models import Distance, VectorParams
from database import qdrant, COLLECTION_NAME, VECTOR_SIZE, get_pg_conn, CREATE_MEMORIES_TABLE
from routers import memories, generate
from memory_operations import delete_decayed_memories
from constants import FORGETTING_INTERVAL_SECONDS
from rate_limit import limiter

# Defaults to dry-run: MIN_RETRIEVABILITY was just changed (see
# constants.py) and this permanently deletes data, so the first real run
# under any new threshold should be inspected via logs before deletion is
# ever enabled. Flip explicitly (FORGETTING_DRY_RUN=false) once the
# dry-run logs for a full cycle look reasonable against real data.
def _resolve_forgetting_dry_run() -> bool:
    """Fails closed: only an exact "false" (case/whitespace-insensitive)
    disables dry-run. A control gating irreversible deletion should not
    let a typo ("ture", "flase", "0") silently enable it — anything that
    isn't recognized stays in dry-run and logs a warning instead."""
    raw = os.getenv("FORGETTING_DRY_RUN", "true").strip().lower()
    if raw not in ("true", "false"):
        print(f"Forgetting: FORGETTING_DRY_RUN={raw!r} is not \"true\" or \"false\" — defaulting to dry-run.")
        return True
    return raw != "false"


FORGETTING_DRY_RUN = _resolve_forgetting_dry_run()

async def forgetting_loop():
    """Runs delete_decayed_memories() on a timer for as long as the app is
    up. The prototype approximates forgetting by permanently deleting
    memories whose modeled retrievability falls below a threshold. The
    blocking DB work happens via asyncio.to_thread so it never stalls the
    event loop handling requests — same reasoning FastAPI already uses for
    plain-def routes. See architecture.md's Decay-Based Forgetting section.

    delete_decayed_memories() already guards against a single malformed
    row (see its own per-row try/except in memory_operations.py), but a
    genuine infrastructure failure — Postgres or Qdrant unreachable, a
    query timeout — happening in get_all_memories() or delete_memories()
    isn't a malformed row and wasn't caught by that. Uncaught here, it
    would propagate out of this coroutine entirely; since this runs as a
    fire-and-forget asyncio.create_task() with nothing awaiting or
    restarting it, that silently ends the loop for the rest of the
    process's life — a transient blip permanently disabling forgetting
    until a manual restart. Catching broadly here (not just the row-level
    ValueError delete_decayed_memories() already handles) and logging
    instead of raising means a bad week is just a skipped week, not a
    permanently dead loop. See security-preventions.md's Resolved
    section."""
    while True:
        await asyncio.sleep(FORGETTING_INTERVAL_SECONDS)
        try:
            deleted = await asyncio.to_thread(delete_decayed_memories, FORGETTING_DRY_RUN)
            if deleted:
                if FORGETTING_DRY_RUN:
                    print(f"Forgetting dry run: would delete {len(deleted)} decayed memories: {deleted}")
                else:
                    print(f"Deleted {len(deleted)} decayed memories.")
        except Exception as e:
            print(f"Forgetting: run failed, will retry next interval: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Qdrant collection
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )

    # Postgres table
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute(CREATE_MEMORIES_TABLE)
    conn.commit()
    cur.close()
    conn.close()

    task = asyncio.create_task(forgetting_loop())
    yield
    task.cancel()
    # Awaiting the cancellation, not just requesting it, avoids "task was
    # destroyed but it is pending" warnings on shutdown. Note this only
    # cancels the loop while it's suspended at `await asyncio.sleep(...)`
    # between runs — cancellation can't interrupt work already running
    # inside `asyncio.to_thread()` (a real forgetting cycle in progress),
    # since that's a separate OS thread the event loop doesn't control.
    # Worth understanding before deploying with real deletion enabled: a
    # shutdown mid-cycle lets that cycle finish rather than aborting it.
    with suppress(asyncio.CancelledError):
        await task

app = FastAPI(lifespan=lifespan)

# No auth by design (see project decision) — CORS here is just about which
# browser origins may call the API, not a security boundary. Frontend origin
# configurable since dev (Vite) and prod (Cloudflare Pages) differ.
#
# Added before the rate limiter below so it stays the outermost middleware
# (Starlette applies add_middleware() calls in the order added, first-added
# = outermost) — this way CORS headers still get attached to 429 responses
# from the rate limiter, not just successful ones. See security-preventions.md.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting — see rate_limit.py for the actual limits/reasoning.
# No auth by design means IP is the only dimension available to key on.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(memories.router)
app.include_router(generate.router)
