# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos inmutables y validados para los workflows de notebooks VAAET."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from vaaet_ml.exceptions import RuntimeConfigurationError

ReviewMode = Literal["priority", "all"]
TrainingModeName = Literal["seed_bootstrap", "hitl_retraining"]
ArtifactActionName = Literal["reuse_or_create", "create_new_version"]


def _require_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise RuntimeConfigurationError(f"{name} must be a boolean.")


def _optional_path(name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise RuntimeConfigurationError(f"{name} must be a non-empty path or None.")


def _optional_run_id(name: str, value: str | None) -> None:
    """Valida la referencia inmutable sin aceptar aliases mutables."""

    if value is None:
        return
    try:
        UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeConfigurationError(f"{name} must be a training pipeline UUID or None.") from exc


def _string_tuple(name: str, values: tuple[str, ...]) -> None:
    """Valida filtros inmutables sin aceptar colecciones ambiguas o vacías."""

    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise RuntimeConfigurationError(f"{name} must be a tuple of non-empty strings.")
    if len(values) != len(set(values)):
        raise RuntimeConfigurationError(f"{name} must not contain duplicates.")


@dataclass(frozen=True)
class CollectionWorkflowConfig:
    """Controles explícitos para recolectar telemetría y video anotado."""

    persist_to_database: bool
    hud_debug: bool
    view_plan_path: str | None = None
    download_outputs: bool = False

    def __post_init__(self) -> None:
        _require_bool("persist_to_database", self.persist_to_database)
        _require_bool("hud_debug", self.hud_debug)
        _require_bool("download_outputs", self.download_outputs)
        _optional_path("view_plan_path", self.view_plan_path)


@dataclass(frozen=True)
class InferenceWorkflowConfig:
    """Controles para seleccionar bundles, persistir y revisar inferencias."""

    allow_pilot_bundle: bool
    allow_experimental_bundle: bool
    persist_to_database: bool
    enable_human_review: bool
    review_mode: ReviewMode
    download_annotated_video: bool
    show_dashboard: bool
    hud_debug: bool
    view_plan_path: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "allow_pilot_bundle",
            "allow_experimental_bundle",
            "persist_to_database",
            "enable_human_review",
            "download_annotated_video",
            "show_dashboard",
            "hud_debug",
        ):
            _require_bool(name, getattr(self, name))
        if self.review_mode not in {"priority", "all"}:
            raise RuntimeConfigurationError("review_mode must be 'priority' or 'all'.")
        _optional_path("view_plan_path", self.view_plan_path)


@dataclass(frozen=True)
class TrainingWorkflowConfig:
    """Controles de entrenamiento validados sin estado mutable del notebook."""

    training_mode: TrainingModeName
    enable_postgres_ingestion: bool
    enable_data_upload: bool
    human_holdout_frozen: bool
    human_holdout_action: ArtifactActionName
    human_holdout_update_reason: str | None
    seed_artifact_action: ArtifactActionName
    seed_artifact_update_reason: str | None
    write_training_report: bool = True
    reference_training_run_id: str | None = None
    run_grouped_cross_validation: bool = False
    copy_bundle_to_drive: bool = False
    postgres_telemetry_read_mode: str = "current"

    def __post_init__(self) -> None:
        if self.training_mode not in {"seed_bootstrap", "hitl_retraining"}:
            raise RuntimeConfigurationError("training_mode is not supported.")
        for name in (
            "enable_postgres_ingestion",
            "enable_data_upload",
            "human_holdout_frozen",
            "write_training_report",
            "run_grouped_cross_validation",
            "copy_bundle_to_drive",
        ):
            _require_bool(name, getattr(self, name))
        if self.postgres_telemetry_read_mode not in {"current", "legacy"}:
            raise RuntimeConfigurationError(
                "postgres_telemetry_read_mode must be 'current' or 'legacy'."
            )
        if (
            self.training_mode == "hitl_retraining"
            and self.postgres_telemetry_read_mode == "legacy"
        ):
            raise RuntimeConfigurationError(
                "Legacy PostgreSQL reads are valid only for raw seed telemetry."
            )
        if self.human_holdout_frozen and self.training_mode != "hitl_retraining":
            raise RuntimeConfigurationError(
                "human_holdout_frozen is valid only for hitl_retraining."
            )
        self._validate_version_action(
            "human_holdout", self.human_holdout_action, self.human_holdout_update_reason
        )
        self._validate_version_action(
            "seed_artifact", self.seed_artifact_action, self.seed_artifact_update_reason
        )
        _optional_run_id("reference_training_run_id", self.reference_training_run_id)

    @staticmethod
    def _validate_version_action(name: str, action: str, update_reason: str | None) -> None:
        if action not in {"reuse_or_create", "create_new_version"}:
            raise RuntimeConfigurationError(f"{name}_action is not supported.")
        if action == "create_new_version" and not update_reason:
            raise RuntimeConfigurationError(
                f"{name}_update_reason is required when creating a new version."
            )


@dataclass(frozen=True)
class EvaluationWorkflowConfig:
    """Controles read-only para comparar bundles y analizar deriva."""

    run_model_evaluation: bool
    champion_bundle_dir: str
    challenger_bundle_dir: str
    holdout_snapshot_path: str
    bootstrap_samples: int
    run_drift_analysis: bool
    reference_feature_cohort_path: str
    operational_feature_cohort_path: str
    use_postgres_operational: bool
    postgres_start_utc: str
    postgres_end_utc: str
    postgres_pipeline_run_ids: tuple[str, ...] = ()
    postgres_clip_ids: tuple[str, ...] = ()
    drift_plot_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "run_model_evaluation",
            "run_drift_analysis",
            "use_postgres_operational",
        ):
            _require_bool(name, getattr(self, name))
        if self.bootstrap_samples < 1:
            raise RuntimeConfigurationError("bootstrap_samples must be positive.")
        if self.run_model_evaluation:
            if not all(
                (
                    self.champion_bundle_dir,
                    self.challenger_bundle_dir,
                    self.holdout_snapshot_path,
                )
            ):
                raise RuntimeConfigurationError(
                    "Model evaluation requires Champion, Challenger, and an exact holdout."
                )
            if self.holdout_snapshot_path.endswith("current.json"):
                raise RuntimeConfigurationError("The evaluation holdout must not be current.json.")
        if self.run_drift_analysis:
            if not self.reference_feature_cohort_path:
                raise RuntimeConfigurationError("Drift analysis requires a reference cohort.")
            if bool(self.operational_feature_cohort_path) == self.use_postgres_operational:
                raise RuntimeConfigurationError(
                    "Choose exactly one operational cohort: file or read-only PostgreSQL."
                )
            if self.use_postgres_operational and not (
                self.postgres_start_utc and self.postgres_end_utc
            ):
                raise RuntimeConfigurationError(
                    "PostgreSQL drift analysis requires explicit UTC bounds."
                )
        _string_tuple("postgres_pipeline_run_ids", self.postgres_pipeline_run_ids)
        _string_tuple("postgres_clip_ids", self.postgres_clip_ids)
        _string_tuple("drift_plot_features", self.drift_plot_features)
