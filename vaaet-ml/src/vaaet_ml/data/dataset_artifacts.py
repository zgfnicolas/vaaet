# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada compatible de artefactos inmutables para VAAET ML 4.x."""

from vaaet_ml.data.artifact_serialization import frames_fingerprint, sha256_file
from vaaet_ml.data.hitl_catalog import (
    HITL_CATALOG_CONTRACT,
    HITL_CATALOG_FILE,
    CatalogSelection,
    HitlCatalogSource,
    HitlReviewCatalog,
    load_hitl_catalog_components,
    load_hitl_catalog_feedback,
    resolve_effective_human_feedback,
)
from vaaet_ml.data.review_finalization import (
    FinalizedReviewSession,
    finalize_review_session,
    import_legacy_hitl_package,
)
from vaaet_ml.data.seed_artifacts import (
    SEED_ARTIFACT_CONTRACT,
    DatasetArtifactAction,
    SeedArtifactConfig,
    SeedArtifactSnapshot,
    VersionedSeedStore,
)
from vaaet_ml.data.training_input_lock import (
    TRAINING_INPUT_LOCK_CONTRACT,
    TrainingInputLock,
    create_training_input_lock,
)

# Compatibilidad de pruebas y extensiones 4.x que aún inspeccionan estos helpers.
_frames_fingerprint = frames_fingerprint
_sha256_file = sha256_file

__all__ = [
    "CatalogSelection",
    "DatasetArtifactAction",
    "FinalizedReviewSession",
    "HITL_CATALOG_CONTRACT",
    "HITL_CATALOG_FILE",
    "HitlCatalogSource",
    "HitlReviewCatalog",
    "SEED_ARTIFACT_CONTRACT",
    "SeedArtifactConfig",
    "SeedArtifactSnapshot",
    "TRAINING_INPUT_LOCK_CONTRACT",
    "TrainingInputLock",
    "VersionedSeedStore",
    "create_training_input_lock",
    "finalize_review_session",
    "import_legacy_hitl_package",
    "load_hitl_catalog_feedback",
    "load_hitl_catalog_components",
    "resolve_effective_human_feedback",
]
