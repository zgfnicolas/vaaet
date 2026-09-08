---
name: vaaet-colab-operations
description: Prepare, adapt, review, or troubleshoot VAAET ML workflows on Google Colab Free with conservative resource use, resumability, secure secrets, Drive-backed immutable data, and artifact integrity. Use for VAAET Colab setup, GPU/RAM preflight, notebook runtime recovery, training checkpoints, data staging, or HITL feedback workflows.
---

# VAAET Colab Operations

## Operating model

Treat Colab as an ephemeral compute worker. Keep source code and high-I/O data under `/content`; persist only governed datasets, locks, review packages, and completed artifacts to mounted Drive.

Before altering a workflow, read ADR-0021, ADR-0026, ADR-0027 and the applicable ADRs `0013` through `0019` in `docs/architecture/decisions/`. Read ADR-0022 before any serving-related change. Preserve the 19 `FEATURE_COLS`, public states, MLP, thresholds, PostgreSQL schema, bundle v3, and DVC remotes unless the user explicitly authorizes a governed change.

- Keep notebooks as thin orchestrators. Put portable operations in `vaaet-core/src/vaaet/` and laboratory behavior in `vaaet-ml/src/vaaet_ml/`.
- Do not mutate `sys.path`.
- In Colab, clone to `/content/vaaet`, install `vaaet-core` before `vaaet-ml`, and validate that both `vaaet` and `vaaet_ml` resolve to installed packages rather than checkout source paths.
- Use editable installation only during local development.
- The MLP produces Normal, Reduced, and Congested. Accident remains human-confirmed only.

## Runtime workflow

### Preflight

Before expensive work, report GPU availability and memory, system RAM, free `/content` storage, Python/TensorFlow versions, and Git commit. Use `nvidia-smi` when available and `tf.config.list_physical_devices("GPU")` for the framework check.

For GPU-required training or visual processing, fail early if no GPU is assigned; do not silently attempt a long CPU fallback. Do not assume a GPU model or memory allocation. Keep system RAM below 11 GB: process videos and datasets in batches/chunks, free large objects between phases, and reduce batch size, frame resolution, workers, or clip scope before increasing runtime load.

### Environment

Use the existing `# Environment setup — run once per Colab runtime` cell as the sole setup path. It must detect Colab, clone or fast-forward `/content/vaaet`, quietly install declared core and ML extras in order, clear stale `vaaet` and `vaaet_ml` modules, validate both import origins, run `pip check` diagnostically, and print versions plus commit—never credentials.

Do not install dependencies or repeatedly import heavyweight modules inside loops. Prefer `subprocess` argument lists to shell strings.

### Secrets and persistent roots

Use Colab Secrets through VAAET's database settings loader. Never print secrets, write them into notebooks, copy them to Drive, use them in Git remotes, or persist them in `.env`. Use the least-privilege `collection`, `inference`, `training`, or `review` database profile.

Use Drive only when governed persistence is needed:

| Asset | Drive root |
| --- | --- |
| Bundle | `/content/drive/MyDrive/vaaet-ml/artifacts/traffic-state` |
| Seed snapshots | `/content/drive/MyDrive/vaaet-ml/data/seed-bootstrap` |
| HITL catalog | `/content/drive/MyDrive/vaaet-ml/data/hitl-reviews/catalog.json` |
| Frozen holdouts | `/content/drive/MyDrive/vaaet-ml/data/holdouts` |
| Training locks | `/content/drive/MyDrive/vaaet-ml/training-runs` |

Do not provide an ephemeral fallback for immutable seed, HITL, or frozen-holdout data. Stop before training or updating a catalog if mounting Drive or checksum validation fails.

### Data and resumability

Do not train from thousands of Drive files. Copy or download an immutable, checksummed archive to `/content`, unpack and process it locally, then retain the original governed object unchanged. Keep external access tokens in Secrets and never in URLs or logs.

Use VAAET's existing persistence rather than standalone checkpoint schemes:

- Record each workflow with `pipeline_run`; keep local fallback manifests redacted.
- Create/reuse seed snapshots, HITL packages, catalog entries, frozen holdouts, and training input locks through VAAET APIs.
- Atomically update pointers/catalogs only after the canonical Drive bytes and SHA-256 match.
- Produce the four-file bundle only after `create_manifest()` succeeds: `traffic_classifier.keras`, `feature_scaler.joblib`, `label_mapping.joblib`, and `model-manifest.json`.
- Call `vaaet.artifacts.validate_manifest()` before Keras or joblib deserialization.

For a new experimental Keras loop, write callbacks only to a run-specific local directory. Persist a validated candidate separately; never overwrite a governed bundle, snapshot, `current.json`, catalog, holdout, or input lock.

### Human checkpoints

At bounded intervals, show epoch/step, loss, validation metric, RAM/GPU state, and a small representative prediction or annotated-frame sample. Stop or ask for review if metrics collapse, quality is low, class balance is unexpected, or incident candidates appear.

Never publish Accident automatically. Preserve the conservative Congested state and the candidate flag; only a human effective validation may publish Accident.

## Reset recovery

Resume in this order:

1. Start a fresh runtime and run the preflight/setup cell.
2. Mount Drive and verify the required root.
3. Select the same explicit `TrainingMode` and artifact action.
4. Verify package origin, checksums, `current.json`, catalog/snapshot, and training input lock.
5. Resume from a complete immutable input, finalized review package, or validated bundle; re-run only idempotent failed phases.

Do not resume from partial mutable Drive content. Keep failed local HITL output as `pending-sync` until Drive synchronization and checksum verification succeed.

## Completion checklist

- Verify GPU/RAM budget and local `/content` staging.
- Confirm that no secrets occur in code, outputs, metadata, exceptions, or commits.
- Record both installed package origins, extras, commit, and redacted pipeline run metadata.
- Confirm that governed snapshots, catalog, holdout, and input lock are immutable and checksummed.
- Confirm that the bundle has exactly four files and passes manifest validation.
- Keep training free of operational database writes; make inference/review persistence explicit.
