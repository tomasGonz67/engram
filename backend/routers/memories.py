import uuid
from fastapi import APIRouter
from qdrant_client.models import PointStruct
from models import MemoryInput, SearchInput
from database import model, qdrant, COLLECTION_NAME

router = APIRouter()

@router.post("/memories")
def store(body: MemoryInput):
    id = str(uuid.uuid4())
    vector = model.encode(body.text).tolist()
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=id, vector=vector, payload={"text": body.text})]
    )
    return {"id": id, "text": body.text}

@router.post("/memories/search")
def search(body: SearchInput):
    vector = model.encode(body.text).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=body.limit
    ).points
    return [
        {"id": r.id, "text": r.payload["text"], "score": r.score}
        for r in results
    ]
