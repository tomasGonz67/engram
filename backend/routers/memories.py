import uuid
from fastapi import APIRouter
from qdrant_client.models import PointStruct
from models import MemoryInput
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
