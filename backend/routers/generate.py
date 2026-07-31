import json
from fastapi import APIRouter
from models import GenerateInput
from database import openai_client, GENERATION_MODEL
from routers.memories import search_memories
from memory_operations import reinforce_memory

router = APIRouter()

SYSTEM_PROMPT = (
    "You are Engram's assistant. Use the retrieved memories below as your "
    "source of truth when they're relevant. If a memory isn't actually "
    "useful for answering, ignore it. After answering, call reinforce_memory "
    "for each memory you genuinely relied on — do not call it for memories "
    "that were shown but not used."
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
def generate(body: GenerateInput):
    retrieved = search_memories(body.text, body.limit)

    memory_context = "\n".join(f"- ({m['id']}) {m['text']}" for m in retrieved) or "No relevant memories found."

    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nRetrieved memories:\n{memory_context}"}]
    for turn in body.recent_turns:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": body.text})

    response = openai_client.chat.completions.create(
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
                args = json.loads(call.function.arguments)
                try:
                    reinforce_memory(args["id"])
                    reinforced_ids.append(args["id"])
                    result = "reinforced"
                except ValueError:
                    result = "memory not found, skipped"
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

        # Second call so the model can produce a final natural-language
        # answer now that its tool calls have results — the first response
        # often has no content when tool_calls are present.
        response = openai_client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=messages,
        )
        message = response.choices[0].message

    return {
        "answer": message.content,
        "reinforced_memory_ids": reinforced_ids,
        "retrieved": retrieved,
    }
