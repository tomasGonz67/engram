from pydantic import BaseModel

class MemoryInput(BaseModel):
    text: str
