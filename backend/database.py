import os
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

COLLECTION_NAME = "memories"
VECTOR_SIZE = 1024

model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"))
qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST"),
    port=int(os.getenv("QDRANT_PORT"))
)
