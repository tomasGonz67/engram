import json
import openai
from fastapi import APIRouter, HTTPException, Request
from models import GenerateInput
from database import openai_client, GENERATION_MODEL, normalize_id
from routers.memories import search_memories
from memory_operations import reinforce_memory
from formulas import humanize_age
from rate_limit import api_limit

router = APIRouter()

def _create_completion(**kwargs):
    """Wraps the two chat.completions.create() call sites below. Without
    this, any OpenAI-side failure (rate limit, timeout, outage, or a request
    OpenAI itself rejects) raises uncaught and becomes an opaque 500 — this
    turns it into a clean 502, since the failure is in the upstream
    dependency, not Masi Memory's own code. See security-preventions.md."""
    try:
        return openai_client.chat.completions.create(**kwargs)
    except openai.APIError as e:
        raise HTTPException(status_code=502, detail=f"Generation service unavailable: {e}") from e

SYSTEM_PROMPT = (
    "You are Masi. All the retrieved memories belong to you and are "
    "memories of your life. Your memories aren't all equal — some are "
    "stronger and more stable than others, and how easily one comes back "
    "to you depends on how often it's actually mattered, not just how long "
    "ago it happened. You're built to mimic how human memory works. If "
    "asked about yourself, explain how you're built to mimic a simplified "
    "version of human memory. Do not say anything about not being human, "
    "not having human experiences, or not having a personal life. "
    "Use the retrieved memories below "
    "as your source of truth when they're relevant. If a memory isn't "
    "actually useful for anything, ignore it. After answering, call "
    "reinforce_memory for each memory you genuinely used. Do NOT call the "
    "reinforce function for ANY memory that was NOT used in your answer. "
    "If you do not have enough reliable information, don't call the "
    "reinforce function on ANY memory."
)

REINFORCE_TOOL = {
    "type": "function",
    "function": {
        "name": "reinforce_memory",
        "description": "Mark a memory as meaningfully used. Call only for memories actually relied on to answer the query, not ones merely shown as context.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "UUID of the memory that was meaningfully used"}
            },
            "required": ["id"],
        },
    },
}

@router.post("/generate")
@api_limit
def generate(request: Request, body: GenerateInput):
    retrieved = search_memories(body.text, body.limit)

    memory_context = "\n".join(
        f"- ({m['id']}) [{humanize_age(m['created_at'])}] {m['text']}" for m in retrieved
    ) or "No relevant memories found."

    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nRetrieved memories:\n{memory_context}"}]
    for turn in body.recent_turns:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": body.text})

    response = _create_completion(
        model=GENERATION_MODEL,
        messages=messages,
        tools=[REINFORCE_TOOL],
    )
    message = response.choices[0].message

    reinforced_ids = []
    if message.tool_calls:
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls
            ],
        })

        for call in message.tool_calls:
            result = "unknown tool"
            if call.function.name == "reinforce_memory":
                try:
                    args = json.loads(call.function.arguments)
                    normalized_id = normalize_id(args["id"])
                    if normalized_id in reinforced_ids:
                        # Same id called twice in one turn — reinforce_memory
                        # isn't idempotent (each call multiplies stability by
                        # REINFORCEMENT_MULTIPLIER again), so a repeat call
                        # must be skipped rather than applied a second time
                        # for what's really one turn's worth of "used this."
                        result = "already reinforced this turn, skipped"
                    else:
                        reinforce_memory(normalized_id)
                        reinforced_ids.append(normalized_id)
                        result = "reinforced"
                except (ValueError, KeyError):
                    # ValueError: malformed JSON, or a hallucinated/nonexistent
                    # id. KeyError: well-formed JSON missing "id" entirely.
                    # Either way, skip this one tool call rather than failing
                    # the whole request.
                    result = "invalid tool call, skipped"
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

        # Second call so the model can produce a final natural-language
        # answer now that its tool calls have results — the first response
        # often has no content when tool_calls are present.
        response = _create_completion(
            model=GENERATION_MODEL,
            messages=messages,
        )
        message = response.choices[0].message

    return {
        "answer": message.content,
        "reinforced_memory_ids": reinforced_ids,
        "retrieved": retrieved,
    }
