---
name: vaaet-monorepo-architecture
description: Govern VAAET's single Git monorepo and its core, persistence, ML, and reserved app boundaries. Use for workspace packaging, DVC ownership, path-scoped validation, future API planning, or cross-component architecture decisions.
---

# VAAET Monorepo Architecture

## Overview

VAAET is already one repository with independently bounded components, not a nested monorepo. Preserve the portable core, shared persistence, ML laboratory, DVC boundary, and future API/web separation defined by ADR-0021 and ADR-0028.

## Use one Git and DVC root

Keep a single `.git`, `.dvc`, remote configuration, top-level CI surface, and shared architecture documentation. Do not create nested Git repositories, autonomous DVC remotes, or an inner monorepo inside `vaaet-ml/` or `vaaet-app/`.

Preserve the current layout:

```text
vaaet/
├─ vaaet-core/        # portable Python distribution; import vaaet
├─ vaaet-persistence/ # shared PostgreSQL distribution; import vaaet_persistence
├─ vaaet-ml/          # ML laboratory distribution; import vaaet_ml
├─ vaaet-app/         # reserved: no API or web scaffold yet
├─ docs/              # shared ADRs and architecture
├─ .dvc/              # one DVC configuration
└─ .github/           # root CI
```


## Keep components independently bounded

Keep portable perception, telemetry, canonical features, state policy, bundle validation, and inference in `vaaet-core/`. It must not import `vaaet_ml`, PostgreSQL, DVC, Drive, or notebook APIs.

Keep `vaaet-persistence/` as the only implementation of PostgreSQL settings, engines, concrete SQL, writes, audit, roles, and Alembic. It may depend on core base but never on ML, TensorFlow, YOLO, DVC, Drive, Colab, or app code.

Keep `vaaet-ml/` as the laboratory: datasets, backup ingestion, training, evaluation, notebooks, Colab adapters, and governed artifacts. Install core, persistence, and ML in order.

Reserve `vaaet-app/` until an HTTP contract and component scope are approved. A future web consumes only that API. Backend workers use `vaaet-core`, validate the current manifest before deserialization, and may use `vaaet-persistence` with service-specific credentials. They never import ML, DVC, Drive, or notebooks; the browser never connects to PostgreSQL.

## Govern changes to the current monorepo

Treat ADR-0021 and ADR-0028 as the current boundaries and ADR-0022 as the serving rule for YOLO. Do not move responsibilities, introduce app code, or alter package boundaries without authorization and a governed ADR/plan.

For a future API or public demo, select one explicit serving route: an AGPL-3.0 public demo with the approved checklist, or a private/commercial deployment with a verified Ultralytics Enterprise license outside Git. Do not expose private artifacts, data, credentials, or review evidence through either route.

Keep DVC at the root and track `vaaet-ml/artifacts/traffic-state/` as the existing atomic four-file bundle. Preserve checksums, manifests, input locks, immutable seed/HITL packages, holdouts, and the configured remotes.

## Preserve the ML serving contract

Keep bundle v3 as the only current ML/API exchange: `traffic_classifier.keras`, `feature_scaler.joblib`, `label_mapping.joblib`, and `model-manifest.json`. Require `vaaet.artifacts.validate_manifest()` before deserializing a bundle in the API.

Preserve the 19 `FEATURE_COLS`, learned states `Normal`, `Reduced`, `Congested`, and the human-only publication of `Accident`. Preserve lifecycle, input policy, `production_eligible`, `promotion_blockers`, and artifact eligibility; relocating code never promotes a bundle.

Use the API as the sole web/ML boundary. Do not make the frontend a DVC client or database client, and do not expose a raw filesystem path, a model binary, secrets, or human-review data through the HTTP contract.

## Keep validation and ownership explicit

Keep shared ADRs, security policy, DVC configuration, and root CI at the repository root. Scope CI by changed paths so ML and application checks can run independently while preserving full integration checks at boundary changes.

Run the core, persistence, or ML gates from its `AGENTS.md` according to the component changed. Add app-specific checks only after its framework and HTTP contract are approved. Validate cross-boundary behavior with a verified bundle and versioned API contract when an API exists.

Reject a migration if package installation, Colab setup, DVC pull, manifest validation, or existing ML tests regress. Keep GPU, Drive, DVC remote, and live PostgreSQL validation manual and explicit.

---

Reject these antipatterns:

- Do not create a second `.git`, nested monorepo, independent DVC remote, or duplicate artifact registry.
- Do not let web import Python, load a model, access DVC, or connect directly to the database.
- Do not copy ML code into the API or bypass manifest validation to accelerate serving.
- Do not move paths and change model behavior, schemas, dependencies, DVC remotes, or permissions in one migration.
- Do not bypass ADR-0021/ADR-0022 or add application scaffolding before the HTTP contract and scope are approved.
