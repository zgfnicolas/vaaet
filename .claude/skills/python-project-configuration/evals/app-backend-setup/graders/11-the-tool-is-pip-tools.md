---
type: llm
focus: trace
weight: 1
---

The dependency tool is pip + pip-tools (the default: requirements.in compiled with pip-compile --generate-hashes) unless the result names one of the skill's cases for uv (existing uv.lock, ADR, explicit request, multi-package workspace or multiplatform lock, platform-provided uv), and the result states which tool it chose and why
