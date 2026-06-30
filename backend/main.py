import uuid
from fastapi import FastAPI
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

app = FastAPI()

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

qdrant = QdrantClient(host="qdrant", port=6333)

COLLECTION_NAME = "memories"
VECTOR_SIZE = 1024

# Create collection if it doesn't exist
existing = [c.name for c in qdrant.get_collections().collections]
if COLLECTION_NAME not in existing:
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )

@app.post("/")
def store(text: str):
    id = str(uuid.uuid4())
    vector = model.encode(text).tolist()
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=id, vector=vector, payload={"text": text})]
    )
    return {"id": id, "text": text}
