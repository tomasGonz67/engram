from contextlib import asynccontextmanager
from fastapi import FastAPI
from qdrant_client.models import Distance, VectorParams
from database import qdrant, COLLECTION_NAME, VECTOR_SIZE, get_pg_conn, CREATE_MEMORIES_TABLE
from routers import memories, generate

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

    yield

app = FastAPI(lifespan=lifespan)

app.include_router(memories.router)
app.include_router(generate.router)
