from contextlib import asynccontextmanager
from fastapi import FastAPI
from qdrant_client.models import Distance, VectorParams
from database import qdrant, COLLECTION_NAME, VECTOR_SIZE
from routers import memories

@asynccontextmanager
async def lifespan(app: FastAPI):
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(memories.router)
