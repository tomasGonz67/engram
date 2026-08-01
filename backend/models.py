from pydantic import BaseModel, Field

class MemoryInput(BaseModel):
    text: str
    impact: float = 1.0

class SearchInput(BaseModel):
    text: str
    limit: int = Field(default=5, ge=1)

class Turn(BaseModel):
    role: str
    content: str

class GenerateInput(BaseModel):
    text: str
    limit: int = Field(default=5, ge=1)
    # Caller-supplied short-term context (e.g. the last few messages of the
    # current session). Engram is stateless and has no session concept of
    # its own — see architecture.md — so tracking/trimming this window is
    # the caller's job, not Engram's.
    recent_turns: list[Turn] = []
