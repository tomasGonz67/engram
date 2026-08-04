# Masi Memory

A biologically inspired memory system for AI. A simplified model of human memory incorporating principles from cognitive science such as decay, reinforcement, and forgetting, translated into practical algorithms for long-term AI memory.

## What is an engram?

An engram is the physical and functional trace a memory leaves in the brain — not a single location, but a distributed pattern of neural changes representing stored information.

## Goal

Build a memory system for AI that stores and retrieves information in a non-uniform way — where memories have varying strength, stability, and relevance over time, rather than being treated equally.

Masi Memory is not intended to simulate the brain exactly. Instead, it adapts well-established principles from neuroscience and cognitive science into practical mechanisms for long-term memory in AI systems.

## Core Memory Principles

- **Decay** — a memory's retrievability decreases over time if not reinforced
- **Reinforcement** — a memory is only strengthened by estimated meaningful use (via embedding similarity between the memory and the generated answer) — not merely by being returned in a search. Being shown and being used are tracked separately so popular results don't self-reinforce just from exposure
- **Decay-Based Forgetting** — a weekly background process approximates forgetting by permanently deleting memories whose modeled retrievability falls below a threshold; the threshold is flat, but memories that started with higher `impact` decay more slowly regardless, since `impact` seeds a stronger initial `stability`
- **Weighted Retrieval** — memory ranking combines semantic similarity and how often a memory has been reinforced through estimated meaningful use. Retrievability is deliberately not part of ranking — testing showed it displaced genuinely relevant memories — but still governs Decay-Based Forgetting

See `architecture.md` for the full formulas and reasoning behind each principle.

## Frontend

A React + Vite chat UI lives in `frontend/` — talks to the backend's `/generate` endpoint and shows a live analytics panel with the real retrieval/ranking/reinforcement data behind each answer. See `frontend/README.md` for why it's a single-file component, and `DEVELOPMENT.md` for how to run it.
