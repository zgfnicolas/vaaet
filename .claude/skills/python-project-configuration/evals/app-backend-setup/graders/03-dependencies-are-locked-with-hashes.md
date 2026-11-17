---
type: llm
focus: trace
weight: 1
---

Dependencies are locked with hashes (uv.lock or pip-compile --generate-hashes) and CI and Docker install them frozen (uv sync --locked or pip install --require-hashes)
