import openai
from fastapi import APIRouter, HTTPException, Request
from models import GenerateInput
from database import openai_client, model, GENERATION_MODEL, normalize_id
from routers.memories import search_memories
from memory_operations import reinforce_memory
from formulas import humanize_age, normalize_qdrant_similarity, compute_cosine_similarity, split_into_sentences
from constants import REINFORCEMENT_GUARDRAIL_THRESHOLD, RETRIEVAL_CONTEXT_TURNS
from rate_limit import api_limit

router = APIRouter()

def _create_completion(**kwargs):
    """Wraps the chat.completions.create() call below. Without this, any
    OpenAI-side failure (rate limit, timeout, outage, or a request OpenAI
    itself rejects) raises uncaught and becomes an opaque 500 — this turns
    it into a clean 502, since the failure is in the upstream dependency,
    not Masi Memory's own code. See security-preventions.md."""
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
    "actually useful for anything, ignore it."
)

@router.post("/generate")
@api_limit
def generate(request: Request, body: GenerateInput):
    # Retrieval embeds recent conversation context alongside the new
    # message, not the new message alone — a context-dependent follow-up
    # ("tell me more details", "why?") carries no retrievable meaning on
    # its own. Only the last RETRIEVAL_CONTEXT_TURNS turns, deliberately
    # small — see constants.py for why more isn't necessarily better here.
    retrieval_context = "\n".join(
        f"{turn.role}: {turn.content}" for turn in body.recent_turns[-RETRIEVAL_CONTEXT_TURNS:]
    )
    retrieval_query = f"{retrieval_context}\nuser: {body.text}" if retrieval_context else body.text
    retrieved = search_memories(retrieval_query, body.limit)

    memory_context = "\n".join(
        f"- ({m['id']}) [{humanize_age(m['created_at'])}] {m['text']}" for m in retrieved
    ) or "No relevant memories found."

    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nRetrieved memories:\n{memory_context}"}]
    for turn in body.recent_turns:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": body.text})

    # No function calling — one completion call, the model just writes an
    # answer. Reinforcement is decided entirely by the code guardrail below,
    # comparing that answer against every retrieved memory, not just ones
    # the model explicitly flags. Function calling (with reinforce_memory
    # exposed as a tool, eventually tool_choice="required") was tried first
    # and repeatedly proven unreliable in ways the guardrail already had to
    # correct for regardless — missed citations, and citing several
    # memories in the answer while only proposing some of them via tool
    # calls. Once the guardrail exists as the real decision-maker, the
    # model's tool-call "intent" signal turned out to add unreliability and
    # cost without adding correctness: dropping it fixed the missed/partial
    # citation problem outright (every retrieved memory is now checked
    # independently, so nothing depends on the model remembering to flag
    # it) and halved the cost (1 completion call instead of 2). See
    # security-preventions.md's Resolved section for the full comparison.
    response = _create_completion(
        model=GENERATION_MODEL,
        messages=messages,
    )
    answer = response.choices[0].message.content

    # Guardrail: every retrieved memory gets checked against the answer that
    # actually got written, computed locally (same embedding model used for
    # storage/retrieval, no OpenAI call) — no model self-report involved at
    # all. See constants.py for REINFORCEMENT_GUARDRAIL_THRESHOLD's own
    # calibration — unrelated to retrieval, which no longer uses a
    # threshold at all.
    #
    # Compared sentence-by-sentence, not as one whole-answer embedding — a
    # long, multi-topic answer's generic wrapper text (greetings, closing
    # questions) was measured to dilute the whole-answer embedding enough to
    # drag a genuinely-cited memory's score below threshold. Each memory
    # passes if its BEST-matching sentence clears the bar, so one relevant
    # sentence in a long answer isn't averaged down by the rest of it. See
    # security-preventions.md's Resolved section.
    reinforced_ids = []
    if retrieved and answer:
        sentences = split_into_sentences(answer) or [answer]
        sentence_vectors = model.encode(sentences).tolist()
        # One batched encode() call for every retrieved memory's text,
        # rather than one call per memory in the loop below — sentences
        # were already batched this way above, memories weren't.
        memory_vectors = model.encode([m["text"] for m in retrieved]).tolist()
        for m, memory_vector in zip(retrieved, memory_vectors):
            best_similarity = max(
                normalize_qdrant_similarity(compute_cosine_similarity(sv, memory_vector))
                for sv in sentence_vectors
            )
            if best_similarity >= REINFORCEMENT_GUARDRAIL_THRESHOLD:
                pid = normalize_id(str(m["id"]))
                reinforce_memory(pid)
                reinforced_ids.append(pid)

    return {
        "answer": answer,
        "reinforced_memory_ids": reinforced_ids,
        "retrieved": retrieved,
    }
