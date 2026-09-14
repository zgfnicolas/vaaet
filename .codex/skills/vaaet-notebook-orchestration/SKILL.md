---
name: vaaet-notebook-orchestration
description: Design, review, simplify, or audit VAAET Jupyter and Google Colab notebooks as thin, sequential, idempotent orchestrators. Use for notebook cell organization, Run All reliability, centralized fail-fast configuration, optional ipywidgets adapters, output hygiene, notebook-to-module boundaries, or detection of notebook antipatterns.
---

# VAAET Notebook Orchestration

Implement the intent of specification `SKL-COLAB-ARCH-009` while preserving VAAET's
package, runtime, and governance contracts.

## Keep the responsibility boundary explicit

- Keep notebooks as user-facing orchestration and visualization entrypoints.
- Put portable vision, features, inference, and bundle behavior in
  `vaaet-core/src/vaaet/`; shared PostgreSQL behavior in
  `vaaet-persistence/src/vaaet_persistence/`; and laboratory data, training and
  evaluation in `vaaet-ml/src/vaaet_ml/`. Import them through `vaaet.*`,
  `vaaet_persistence.*` and `vaaet_ml.*`.
- Use `$vaaet-python-ml-engineering` when extracting or redesigning reusable Python.
- Use `$vaaet-colab-operations` for runtime setup, GPU/RAM, Drive, Secrets, recovery,
  immutable artifacts, and Colab-specific operational behavior.
- Read `AGENTS.md` and the applicable ADRs before changing contracts or workflow behavior.

Keep data access explicit and governed: DVC uses the local `vaaet-registry` remote in
`.dvc/config.local`; notebooks do not configure DVC, remotes, credentials, or providers. Keep
`VideoViewPlan` paths explicit, private, and validated by the ML adapter. Do not infer camera
profiles, metric references, or input sources from a clip.

Do not mutate `sys.path`, import `src.*`, use `requirements.txt`, or add notebook-local
dependency drift. Install project extras from `pyproject.toml`: use a normal installation in
Colab and an editable installation only for local development.

Keep stable imports near the shared setup and workflow boundary. A lazy import is acceptable only
for an explicitly optional capability, such as Colab upload/download or an authorized widget; it
must not conceal a required dependency, business rule, or alternate setup path. Do not require all
imports to occupy one cell when that would obscure those boundaries.

## Organize a linear workflow

Keep one responsibility per cell and preserve this conceptual order:

1. Explain the workflow, inputs, outputs, and safety defaults.
2. Run the single idempotent environment setup cell.
3. Validate one centralized workflow configuration before expensive work.
4. Acquire or select inputs explicitly.
5. Call shared package APIs for the main operation.
6. Perform opt-in persistence or human review.
7. Present and export bounded results.

Start each workflow with concise Markdown that states its goal, declared inputs and outputs,
safe defaults, and next step. Add Markdown headings before meaningful phases, then record a
decision, limitation, or changed parameter when it is made—not as retrospective prose. Link the
canonical ADR, contract, or operations guide instead of duplicating it. Never place secrets,
private paths, private camera data, raw review notes, or unredacted failures in narrative cells.

Place configuration before setup only when it uses plain Python values. Place it immediately
after setup when it requires enums or types imported from `vaaet`. Never require out-of-order
execution. Ensure `Run All` works with safe defaults and without repairing hidden state. After a
workflow change, validate from a restarted runtime with `Run All` when the relevant Colab inputs
are available; otherwise report that manual validation as pending.

Prefer operation cells below 50 lines. Treat a cell above 50 lines as an extraction review and
a cell above 500 lines as a structural failure. Do not split cohesive setup mechanically merely
to satisfy the soft target; extract reusable behavior instead.

## Make configuration deterministic

- Define each operational option exactly once in a clearly marked configuration cell.
- Default persistence, remote writes, experimental models, and expensive optional behavior to
  disabled unless the governing workflow says otherwise.
- Validate enum values, paths, mutually exclusive options, required profiles, and artifact
  compatibility before processing begins.
- Avoid mutable catch-all dictionaries and variables that change type across cells.
- Move a growing or shared configuration contract to a typed immutable object in the owning core or ML component.
- Use the existing `RANDOM_SEED` and framework helpers for random workflows; do not introduce
  competing notebook-local seeds. Record the selected seed together with the Git commit, selected
  extras, explicit input sources, and existing input-lock or artifact provenance.
- A seed makes the workflow repeatable under comparable inputs and runtime conditions; it does not
  promise bit-for-bit equality across Colab images, GPU hardware, or framework versions.

Treat `ipywidgets` as an optional frontend. Lazy-import it only when UI is authorized. Make the
widgets produce the same validated typed configuration used by the non-interactive path. Keep a
safe default configuration so `Run All` never depends on clicking a button. Do not let widget
callbacks become the only source of truth or business logic.

## Bound runtime memory and notebook outputs

Stage high-I/O archives under `/content`, process large data in batches or chunks, and use the
Colab RAM budget from `$vaaet-colab-operations`. Release a large object only after its final use
and after any required governed checkpoint, manifest, or export completes; do not add `del` or
garbage collection merely to conceal a dependency between cells.

Keep versioned notebooks output-light: retain small, safe summaries that support the narrative and
remove bulky frames, videos, binary payloads, repeated plots, noisy installation logs, and sensitive
tracebacks. Do not introduce `nbstripout`, `nbdime`, automatic output clearing, or Git hooks
without separate authorization and tool adoption.

## Preserve idempotency and observable failures

- Make setup safe to rerun: clone or fast-forward, install once, clear stale imports, and validate
  the installed package origin.
- Make downloads, persistence, review finalization, and artifact publication explicitly
  idempotent through their existing VAAET APIs. Seal a HITL ZIP locally before
  attempting Drive; preserve the exact package as `pending-sync` on remote failure.
  Keep finalization separate from catalog publication and require the designated
  active `HitlCatalogPublisher` for every catalog mutation.
- Fail fast with a clear recovery action when enabled behavior lacks inputs, credentials, schema,
  or compatible artifacts.
- Keep useful progress and final summaries visible, but capture or suppress noisy package output.
- Never print secrets, DSNs, certificates, private review notes, or unredacted exceptions.
- Do not catch broad exceptions merely to continue after a corrupted result.

Papermill, Jupytext, HTML/PDF export, Docker, Binder, and notebook automation are future options,
not current VAAET requirements. Propose them only with an approved use case, privacy review,
dependency and CI impact, and an ADR when they change the runtime or architecture. A static export
must be explicitly requested, redacted, and kept outside versioned notebook outputs unless a
governed deliverable says otherwise.

## Audit before and after edits

Run the bundled auditor against every active notebook:

```bash
python .codex/skills/vaaet-notebook-orchestration/scripts/audit_notebooks.py vaaet-ml/notebooks
```

The auditor returns nonzero for invalid JSON/Python, cells above 500 lines, forbidden import or
installation patterns, missing or duplicated setup/configuration cells, and configuration values
reassigned outside their owning cell. It reports cells above 50 lines as non-blocking warnings.

After changes, also run the repository-required Ruff, pytest, compileall, notebook AST, Markdown
link, and `git diff --check` gates. Report which logic stayed in the notebook, which logic moved to
the owning `vaaet-core/` or `vaaet-ml/` module, configuration and failure behavior, provenance and
seed impact, tests, and any Colab-only validation pending.

## Reject common notebook antipatterns

- Monolithic cells containing reusable OpenCV, model, database, or feature logic.
- Multiple setup paths, repeated installation commands, or hidden import-path mutations.
- Configuration assignments scattered across later cells or Markdown examples copied as code.
- Mandatory widget clicks, implicit persistence, or credentials that activate writes by presence.
- `Run All` flows that require returning to earlier cells or preserving stale runtime variables.
- Unbounded logs, displays inside frame loops, or outputs large enough to destabilize the browser.
- Notebook-local `requirements.txt`, `pip freeze`, DVC remote setup, or ad hoc data-provider
  credentials presented as reproducibility.
- Treating a random seed as proof of cross-hardware determinism, or deleting live variables to
  hide an out-of-order dependency.
