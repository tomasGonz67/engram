import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from qdrant_client.models import Distance, VectorParams
from database import qdrant, COLLECTION_NAME, VECTOR_SIZE, get_pg_conn, CREATE_MEMORIES_TABLE
from routers import memories, generate
from memory_operations import consolidate
from constants import CONSOLIDATION_INTERVAL_SECONDS
from rate_limit import limiter

async def consolidation_loop():
    """Runs consolidate() on a timer for as long as the app is up. The
    blocking DB work happens via asyncio.to_thread so it never stalls the
    event loop handling requests — same reasoning FastAPI already uses for
    plain-def routes. See architecture.md's Consolidation section."""
    while True:
        await asyncio.sleep(CONSOLIDATION_INTERVAL_SECONDS)
        deleted = await asyncio.to_thread(consolidate)
        if deleted:
            print(f"Consolidation: pruned {len(deleted)} memories")

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

    task = asyncio.create_task(consolidation_loop())
    yield
    task.cancel()

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
