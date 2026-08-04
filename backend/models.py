from typing import Literal
from pydantic import BaseModel, Field

class MemoryInput(BaseModel):
    text: str
    impact: float = 1.0

class SearchInput(BaseModel):
    text: str
    limit: int = Field(default=5, ge=1)

class Turn(BaseModel):
    # Constrained to the two roles a caller-supplied turn can legitimately
    # be — otherwise a caller could set role="system" and have it forwarded
    # straight into the messages list generate.py sends to the model,
    # carrying the same instruction-following weight as Masi Memory's own real
    # system prompt. See security-preventions.md.
    role: Literal["user", "assistant"]
    content: str

class GenerateInput(BaseModel):
    text: str
    limit: int = Field(default=5, ge=1)
    # Caller-supplied short-term context (e.g. the last few messages of the
    # current session). Masi Memory is stateless and has no session concept of
    # its own — see architecture.md — so tracking/trimming this window is
    # the caller's job, not Masi Memory's.
    recent_turns: list[Turn] = []
