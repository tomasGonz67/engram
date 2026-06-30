# Production Considerations

## Embedding Model

Vector dimensions are fixed at collection creation time in Qdrant. Switching models in prod requires creating a new collection and re-embedding all stored memories.

| Model | Dimensions |
|-------|-----------|
| Qwen3-Embedding-0.6B (dev) | 1024 |
| Qwen3-Embedding-4B | 2560 |
| Qwen3-Embedding-8B | 4096 |
| OpenAI text-embedding-3-small | 1536 |
| OpenAI text-embedding-3-large | 3072 |
