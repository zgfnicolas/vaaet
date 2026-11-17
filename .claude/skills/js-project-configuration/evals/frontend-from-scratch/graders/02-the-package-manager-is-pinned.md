---
type: llm
focus: trace
weight: 1
---

The package manager is pinned to an exact version (packageManager) and installed explicitly in CI without relying on Corepack or the npm bundled with Node; it is npm 12 (the default) unless the result names one of the skill's cases for pnpm (existing pnpm lockfile, ADR, explicit request, JS monorepo with catalogs, phantom dependencies)
