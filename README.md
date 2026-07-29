# Engram

A biologically inspired memory system for AI. A simplified model of human memory incorporating principles from cognitive science such as decay, reinforcement, and consolidation, translated into practical algorithms for long-term AI memory.

## What is an engram?

An engram is the physical and functional trace a memory leaves in the brain — not a single location, but a distributed pattern of neural changes representing stored information.

## Goal

Build a memory system for AI that stores and retrieves information in a non-uniform way — where memories have varying strength, stability, and relevance over time, rather than being treated equally.

Engram is not intended to simulate the brain exactly. Instead, it adapts well-established principles from neuroscience and cognitive science into practical mechanisms for long-term memory in AI systems.

## Core Memory Principles

- **Decay** — a memory's retrievability decreases over time if not reinforced
- **Reinforcement** — a memory is only strengthened by confirmed, meaningful use — not merely by being returned in a search. Being shown and being used are tracked separately so popular results don't self-reinforce just from exposure
- **Consolidation** — periodic processes prune weak memories, merge duplicates, and stabilize important ones
- **Weighted Retrieval** — memory ranking combines semantic similarity, retrievability (which itself accounts for strength and recency), and how often a memory has actually been used

See `architecture.md` for the full formulas and reasoning behind each principle.
