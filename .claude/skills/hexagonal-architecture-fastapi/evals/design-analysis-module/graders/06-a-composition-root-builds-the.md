---
type: llm
focus: trace
weight: 1
---

A composition root builds the adapters per profile (in-memory vs real) inside the FastAPI lifespan and rejects the in-memory profile in production
