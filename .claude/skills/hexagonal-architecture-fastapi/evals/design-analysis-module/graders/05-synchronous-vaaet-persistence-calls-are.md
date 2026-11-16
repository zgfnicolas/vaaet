---
type: llm
focus: trace
weight: 1
---

Synchronous vaaet-persistence calls are wrapped in a threadpool (anyio.to_thread, run_in_threadpool or similar) or only run inside the synchronous worker, never called directly from an async endpoint
