from pydantic import BaseModel

class MemoryInput(BaseModel):
    text: str

class SearchInput(BaseModel):
    text: str
    limit: int = 5
