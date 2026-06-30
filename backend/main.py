from fastapi import FastAPI
from sentence_transformers import SentenceTransformer

app = FastAPI()

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

@app.get("/")
def embed(text: str = "hello world"):
    vector = model.encode(text)
    return {"text": text, "vector": vector.tolist()}
