# ADR-009: Modular Three-Stage Architecture

**Estado:** Aceptada\
**Date:** 2026-03-10  
**Supersedes:** ADR-001 (Monolithic Notebook)  
**Decisors:** VAAET Team

> Nota de vigencia (2026-08-01): la separación modular continúa vigente; los
> nombres y límites actuales de los workflows se precisan en [ADR-0013](0013-on-demand-data-collection-workflow.md).
> La persistencia y HITL vigentes se definen en
> [ADR-0015](0015-postgresql-namespaces-security-and-hitl.md).

> **Estado de vigencia (2026-08-27):** esta ADR conserva la razón histórica de
> extraer lógica de notebooks. Las rutas y límites activos son
> `vaaet-core/src/vaaet/` y `vaaet-ml/src/vaaet_ml/`; ADR-0021 gobierna el
> monorepo y ADR-0022 el serving con YOLO. El cuerpo siguiente no describe el
> layout actual. La convención histórica «English-only» tampoco gobierna la
> documentación interna vigente: los identificadores permanecen en inglés y
> los comentarios y docstrings propios se redactan en español rioplatense.

## Context

VAAET originally followed a monolithic notebook pattern (ADR-001) where all code lived inside a single `.ipynb` file. This decision was appropriate for Phase 1 (Perception), which was a self-contained video-processing pipeline.

With the addition of Phase 2 (Intelligence), the project now has three distinct execution concerns:

1. **Bootstrap** — One-time initial data generation (YOLO + tracking + speed → `traffic_data`)
2. **Data Preparation** — One-time feature engineering, labeling, and model training
3. **Production** — Ongoing video analysis combining YOLO perception with trained MLP classification, with a feedback loop for continuous model improvement

The monolithic pattern creates several problems:
- **Code duplication**: Feature engineering and labeling logic must be identical across notebooks
- **No testability**: Functions embedded in notebooks cannot be unit-tested
- **No shared modules**: Common logic (DB connection, feature engineering) is copy-pasted
- **Confusing naming**: "Phase 1" / "Phase 2" / "Fase 1" / "Fase 2" / "Etapa 1" / "Etapa 2" created a three-level naming collision

## Decision

Adopt a **three-module architecture** with shared Python modules in `src/`:

```
archive/bootstrap-v1/        → Module 0: Bootstrap (archived, never runs again)
notebooks/01_data_prep/      → Module 1: Data Preparation (runs once)
notebooks/02_production/     → Module 2: Production (runs always)
src/                         → Shared Python modules (imported by notebooks 1 & 2)
```

### Shared modules in `src/`

| Module | Responsibility | Used by |
|---|---|---|
| `src/config.py` | Constants, paths, thresholds, state labels | All |
| `src/db.py` | SQLAlchemy engine factory, credential handling | Notebooks 1 & 2 |
| `src/features.py` | `engineer_features()` — 9→14 column transform | Notebooks 1 & 2 |
| `src/labeling.py` | `assign_traffic_state()` — auto-labeling rules | Notebooks 1 & 2 |
| `src/perception/detector.py` | YOLO detection wrapper | Notebook 2 |
| `src/perception/tracker.py` | SORT tracker implementation | Notebook 2 |
| `src/perception/speed.py` | Speed estimation (physics-based) | Notebook 2 |

### Module execution model

| Module | Notebook | Runs | Input | Output |
|---|---|---|---|---|
| **0 — Bootstrap** | `archive/bootstrap-v1/01_legacy_collection.ipynb` | Never again | Video .mp4 | `traffic_data` (DB) |
| **1 — Data Prep** | `notebooks/training/train_traffic_state_classifier.ipynb` | Once | `traffic_data.backup` | `.keras` + `.joblib` artifacts |
| **2 — Production** | `notebooks/inference/analyze_traffic_video.ipynb` | Always | Video .mp4 + trained model | `telemetry_raw` + `traffic_classifications` (DB) |

### Feedback loop

Module 2 generates two new database tables. Human operators can validate/override classifications via HITL fields. When enough validated data accumulates, Module 2 includes a re-training cell that:
1. Loads human-validated records from `traffic_classifications`
2. Merges with original training data
3. Re-trains the MLP
4. Exports updated `.keras` if F1-macro improves

### Naming convention

All artifacts use **English** for folder names, file names, docstrings, markdown, and comments. The previous Spanish/English mix (Etapa/Phase/Fase) is eliminated.

## Rationale

1. **Single source of truth**: `src/features.py` and `src/labeling.py` are imported by both active notebooks — no code duplication, no divergence risk
2. **Testability**: Functions in `src/` can be unit-tested with pytest independently of notebooks
3. **SOLID — Single Responsibility**: Each module has one job (config, DB, features, labeling, detection, tracking, speed)
4. **KISS**: Notebooks remain thin orchestrators calling `src/` functions. Business logic lives in tested Python modules
5. **YAGNI**: Only modules that are needed today are created. No premature abstractions
6. **Low coupling**: `src/perception/` depends only on `src/config`. `src/features.py` depends only on `src/config`. Notebooks depend on `src/` but not on each other
7. **High cohesion**: Each `src/` module groups related functions (all feature engineering in one file, all labeling in another)
8. **Archive pattern**: Module 0 is preserved for historical reference but clearly separated from active code

## Consequences

### Positive

- Feature engineering and labeling logic have a single canonical implementation
- `src/` modules are testable with pytest
- Clear separation: archived code vs. active code
- English-only naming eliminates the Etapa/Phase/Fase confusion
- Production notebook can run end-to-end: video → classification → persistence → re-training
- Feedback loop enables continuous model improvement without manual intervention

### Negative

- **Breaks ADR-001**: "No `.py` files outside notebooks" is now superseded. This is intentional — the monolithic pattern was appropriate for a single-notebook project but not for a three-module system
- **Colab import complexity**: Notebooks must add the repo root to `sys.path` for `from src...` imports to work. This is a minor setup cost handled in Cell 0 of each notebook
- **More files to maintain**: 7 Python modules + 2 active notebooks instead of 2 monolithic notebooks. The tradeoff is worth it for testability and reusability

### Technical debt

- **Module 2 is a skeleton**: The production notebook has functional structure but `# TODO:` markers for full implementation (perception loop, persistence batch inserts, re-training loop)
- **No unit tests yet**: `src/` modules are designed for testing but tests are not implemented
- **No CLI interface**: All execution is notebook-driven. A future CLI wrapper could call `src/` modules directly
