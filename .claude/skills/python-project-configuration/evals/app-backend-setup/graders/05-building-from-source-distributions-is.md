---
type: llm
focus: trace
weight: 1
---

Third-party packages are restricted to wheels without blocking the local path dependencies: either a two-step install (uv sync --no-install-local --no-build, then uv sync) or pip --only-binary for third parties with local packages installed separately; a global no-build = true together with path sources fails this assertion
