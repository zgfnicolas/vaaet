---
name: vaaet-mlp-hitl-observability
description: Guide safe VAAET tabular MLP training and review. Use for seed bootstrap, HITL retraining, weak-supervision governance, immutable datasets and holdouts, model eligibility, TensorFlow/Keras evaluation, and interpretable training diagnostics.
---

# VAAET MLP HITL Observability

## Overview

Preserve VAAET's human-first learning lifecycle. Treat a seed model as an auditable pilot, not as production evidence, and use visual diagnostics to explain measured behavior without overstating model confidence.

Keep model contracts, feature policy, bundle validation, and serving-compatible inference in `vaaet-core/`; keep datasets, training, diagnostics, notebooks, DVC, and PostgreSQL in `vaaet-ml/`. The laboratory may depend on core; core must not depend on ML.

## Preserve the public learning contract

Keep the canonical 19 `FEATURE_COLS` in their existing order. Preserve the current MLP, its three learned outputs—`Normal`, `Reduced`, and `Congested`—and its bundle v3 interfaces unless authorization and the applicable ADR permit a change.

Keep `Accident` outside the learned target. A reliable automatic signal remains `Congested` with `accident_rule_triggered`; only an effective human validation can publish the public Accident state.

Respect ADR-0021, ADR-0014, and ADR-0017 through ADR-0019 as the current authority. Use earlier MLP ADRs only as historical context.


## Use the two explicit training modes

Use `TrainingMode.SEED_BOOTSTRAP` once to normalize raw legacy telemetry, calculate the canonical features, assign proxy labels, and resolve an immutable seed snapshot. Label its bundle `pilot`, `weak-proxy`, and `production_eligible=false`.

Use `TrainingMode.HITL_RETRAINING` to consume compatible processed features and effective human validations. Do not recalculate their features, turn predictions into targets, or treat unvalidated reviews as ground truth. Let proxy memory decrease only through the existing class-specific human-support policy.

Keep synthetic data in training only. Preserve its provenance, effective weight limits, and exclusion from validation/test; synthetic Accident sequences exercise the incident path and never become MLP labels.

## Protect data and evaluation integrity

Use immutable seed snapshots, finalized HITL session packages, the active catalog, frozen human holdouts, and the training input lock as auditable sources. Never overwrite a generation or compare candidates automatically across different holdout fingerprints.

Split complete clips before fitting scalers, balancing, or selecting thresholds. Keep synthetic records out of validation/test and require the existing partition validation to reject leakage. Select the decision policy on validation cost; leave test frozen for final evidence.

Keep TensorFlow/Keras, scikit-learn, Matplotlib, and Seaborn within the declared `vaaet-ml` extras. Use the core-owned input policy identically in training and serving, including legacy quality-feature neutralization.

## Make diagnostics interpretable

Recognize the current notebook diagnostics: class distribution, training curves, direct and policy-level confusion matrices, and the reliability diagram. Keep their metrics separated by data origin, class support, and human-versus-proxy evidence.

When modifying training behavior, save at least three descriptive diagnostics under the training-run directory. Give each a technical title and a short colloquial finding that tells a product reader what the observed evidence means; use accessible colors and annotate sparse or missing support.

Treat KDE plots of maximum confidence and post-training feature importance as future diagnostics, not current functionality. Compute them only from already-separated evaluation data, name the method and its limits, and never describe softmax confidence or an importance ranking as causal proof.

## Build auditable candidates

Create only the existing bundle v3 files and validate its manifest before use. Preserve lifecycle, supervision, input policy, data provenance, `production_eligible`, and `promotion_blockers`; a complete pilot bundle remains ineligible until human-evidence gates pass.

Require a real frozen human holdout, adequate telemetry coverage, no leakage, per-class support and intervals, retrospective review, and prospective shadow evidence before manual promotion. Report incident candidates as false candidates per hour and negative exposure; do not publish Accident recall without confirmed incidents.

For changes in scope, run the ML gates and any affected core contract gates from their `AGENTS.md` files, plus notebook-cell parsing, Markdown links, and `git diff --check`. Validate Drive persistence and a real Colab training run manually.

---

Reject these antipatterns:

- Do not change the MLP, `FEATURE_COLS`, thresholds, bundle contract, datasets, dependencies, or ADRs without authorization.
- Do not use `validation_split`, SMOTE 1:1, row-level random leakage, synthetic validation/test records, or predictions as targets.
- Do not promote a weak-proxy seed, treat `production_eligible` as optional, or bypass manifest and input-lock checks.
- Do not claim an automatic Accident state, incident recall without real confirmed cases, or calibration beyond the measured holdout.
- Do not store model binaries in Git or log human-review notes, secrets, private paths, or unredacted operational data.
