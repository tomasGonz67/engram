from pydantic import BaseModel

class MemoryInput(BaseModel):
    text: str
    impact: float = 1.0

class SearchInput(BaseModel):
    text: str
    limit: int = 5
