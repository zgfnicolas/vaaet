---
type: llm
focus: trace
weight: 1
---

The refactor replaces the raw INSERT into an ad-hoc table with the public API of vaaet-persistence, noting that the schema is owned by Alembic
