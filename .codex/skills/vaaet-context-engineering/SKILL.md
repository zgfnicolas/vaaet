---
name: vaaet-context-engineering
description: Design, audit, or safely evolve VAAET AI context and repository documentation. Use for AGENTS.md and tool pointer file upkeep, documentation hierarchy, ADR and contract discoverability, risk-proportionate HITL planning, context-rot reviews, or repository onboarding improvements.
---

# VAAET Context Engineering

## Preserve the canonical context map

Treat the existing VAAET files as one modular context system. Read the smallest
set of authoritative files needed for the task, then follow their links rather
than copying their contents into a new summary.

| Responsibility | Canonical location |
| --- | --- |
| Human project entrypoint | `README.md` |
| Agent operating boundaries | `AGENTS.md` |
| Tool pointer files | `CLAUDE.md` and `.github/copilot-instructions.md` (one line pointing to `AGENTS.md`) |
| Documentation navigation | `docs/index.md` |
| Requirements, roles and business rules | `docs/product/` |
| Decision index | `docs/architecture/decisions/README.md` |
| Portable Python component | `vaaet-core/` and `vaaet-core/AGENTS.md` |
| Shared persistence component | `vaaet-persistence/` and `vaaet-persistence/AGENTS.md` |
| ML laboratory component | `vaaet-ml/` and `vaaet-ml/AGENTS.md` |
| Reserved application boundary | `vaaet-app/` (no code until approved) |
| Architecture and ADRs | `docs/architecture/` |
| ML, product, operations, quality, governance | their matching `docs/` domains |
| Specialized Codex guidance | `.codex/skills/` |
| Claude Code configuration | `.claude/` (settings, hooks, path-scoped rules that point to these skills, skills, subagents) and one `CLAUDE.md` per component that imports its `AGENTS.md` |
| Governed plan template | `docs/governance/plans/TEMPLATE.md` |

Treat ADRs, data contracts, and security rules as stronger evidence than a
README or dense summary. Preserve the 19 features, public-state policy, bundle
contract, HITL invariants, and database governance described by their active
ADRs.

Before editing component code, read the root context and the owning component's
`AGENTS.md`. ADR-0021 governs the core--ML--app boundary; read ADR-0022 before
planning any serving path that uses YOLO.

Do not create a parallel root such as `llms.txt`, `llms-full.txt`,
`architecture.md`, or `instructions.md`; `AGENTS.md` is the single agent
context file and other tools get a one-line pointer to it. Do not introduce `.ai/`, `agents_custom/`, generic prompt
catalogs, or a second skills hierarchy. Keep context in plain text and Markdown
so it remains portable across tools while keeping VAAET's `.codex/skills/` as
the local capability catalogue.

## Keep context small, factual, and synchronized

Document incrementally: before changing a governed component, identify its
canonical contract or ADR; after the change, update only the affected source of
truth, its navigation link when necessary, and any concise summary that became
factually stale.

Keep `AGENTS.md` under 150 lines: routing, commands, where things live,
inviolable rules with links, limits, and closing evidence. Point to files
instead of copying them; never list ADRs one by one outside the decision index,
and never hardcode component versions outside `pyproject.toml`, the changelog,
and CI. Keep diagrams and detailed explanations in their appropriate `docs/`
domain.

Never place secrets, passwords, API tokens, DSNs, certificates, private paths,
PII, raw production payloads, or unredacted exceptions in context files, plans,
commit references, or examples. Use links, identifiers, and redacted summaries
instead.

When a request conflicts with `AGENTS.md`, an active ADR, a contract, or an
explicit business invariant, stop before editing code. State the conflicting
sources, the impact, and the needed human decision. Do not resolve ambiguity by
silently changing context or implementation.

## Apply HITL proportionately to risk

Use ordinary task evidence for contained edits that do not alter a public
contract, security posture, architecture, data lifecycle, dependencies, or
governed invariant. Record scope, tests, and documentation impact in the normal
change review; do not require a standalone plan for every routine fix.

For architectural changes, migrations, schema or permission changes, data and
artifact contract changes, dependency additions, major refactors, security
policy changes, DVC-remote changes, or changes to governed model behavior,
propose a dated plan at:

```text
docs/governance/plans/YYYY-MM-DD-<slug>.md
```

Wait for explicit human ACK before each approved high-risk phase. Include the
decision, scope and non-scope, affected canonical sources, invariants, rollback
or recovery considerations, acceptance checks, and phase status. Link the
implemented plan to its commit, PR, or issue using public identifiers only.

Retain a NACKed or failed plan only when it records a reusable correction to an
instruction, contract, or review process. Archive it with a concise reason;
do not create a noisy dead-letter archive for routine abandoned ideas.

## Use the governed execution-plan template

Use the template only for a change that meets the governed-risk threshold
above. Copy [`docs/governance/plans/TEMPLATE.md`](../../../docs/governance/plans/TEMPLATE.md),
the single source shared with the Claude Code `governed-plan` skill, to
`docs/governance/plans/YYYY-MM-DD-<slug>.md`. Replace every placeholder,
retain only applicable checks, and keep the plan free of sensitive data.

Use VAAET scopes such as `core`, `ml`, `vision`, `features`, `inference`,
`data`, `training`, `evaluation`, `artifacts`, `notebooks`, `docs`, or `ci`
when they clarify a Conventional Commit. Do not invent generic `frontend`,
`backend`, `database`, or `infra` scopes while `vaaet-app/` remains reserved.

## Review quality without adding tooling by default

Use ISO/IEC 26514 and IEEE 29148 as review lenses for readability,
discoverability, consistency, traceability, and verifiable requirements. Use an
Agile Definition of Done to require scoped acceptance evidence and human review
for governed changes. Do not claim certification or compliance without a
separate assessed scope and evidence.

Measure context quality only when it helps a real decision: onboarding time,
first-pass acceptance, repeated context conflicts, documentation drift, and
relevant token use are observations, not universal release gates. Do not add
Markdownlint, pre-commit hooks, token telemetry, NumPy analysis, or CI changes
without explicit authorization and a compatibility review.

Validate Markdown links through the repository checks, preserve headings and
relative paths, and keep terminology consistent with `AGENTS.md` and active
ADRs. For changes in scope, run the VAAET quality gates and report the
authoritative sources reviewed, the context changed, the human decision when
required, and remaining manual validation.

## Reject context-engineering antipatterns

- Copying an ADR, contract, or rule into multiple competing summaries.
- Documenting an entire legacy system before the task identifies the relevant
  module or risk.
- Treating an AI-generated proposal as an approved architectural decision.
- Advancing a governed multi-phase change without the required human ACK.
- Replacing current VAAET paths with generic framework folders without an
  approved migration.
- Persisting sensitive data or presenting unmeasured AI-quality metrics as facts.
