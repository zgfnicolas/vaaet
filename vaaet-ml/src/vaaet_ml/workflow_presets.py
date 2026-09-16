# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Presets tipados y resúmenes seguros para los notebooks VAAET."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, TypeAlias, TypeVar

from vaaet_ml.exceptions import RuntimeConfigurationError
from vaaet_ml.workflow_config import (
    CollectionWorkflowConfig,
    EvaluationWorkflowConfig,
    InferenceWorkflowConfig,
    TrainingWorkflowConfig,
)

__all__ = [
    "CollectionPreset",
    "EvaluationPreset",
    "EvaluationPresetInputs",
    "InferencePreset",
    "TrainingPreset",
    "collection_preset_config",
    "evaluation_preset_config",
    "inference_preset_config",
    "render_workflow_summary",
    "resolve_collection_config",
    "resolve_evaluation_config",
    "resolve_inference_config",
    "resolve_training_config",
    "training_preset_config",
]


class CollectionPreset(str, Enum):
    """Flujos estables de recolección de telemetría."""

    LOCAL = "collection-local-v1"
    POSTGRES = "collection-postgres-v1"
    TRACKING_DIAGNOSTIC = "collection-tracking-diagnostic-v1"
    CUSTOM = "collection-custom"


class TrainingPreset(str, Enum):
    """Flujos estables de inicio semilla y reentrenamiento HITL."""

    SEED_UPLOAD = "training-seed-upload-v1"
    SEED_POSTGRES = "training-seed-postgres-v1"
    HITL_CATALOG = "training-hitl-catalog-v1"
    HITL_CATALOG_POSTGRES = "training-hitl-catalog-postgres-v1"
    HITL_FROZEN_HOLDOUT = "training-hitl-frozen-holdout-v1"
    CUSTOM = "training-custom"


class InferencePreset(str, Enum):
    """Flujos estables de inferencia, persistencia y revisión."""

    PILOT_OFFLINE = "inference-pilot-offline-v1"
    PILOT_HITL = "inference-pilot-hitl-v1"
    PERSISTED_INFERENCE = "inference-persisted-v1"
    PERSISTED_HITL = "inference-persisted-hitl-v1"
    EXPERIMENTAL_OFFLINE = "inference-experimental-offline-v1"
    CUSTOM = "inference-custom"


class EvaluationPreset(str, Enum):
    """Flujos read-only de comparación y deriva."""

    CHECK_ONLY = "evaluation-check-only-v1"
    COMPARE_MODELS = "evaluation-compare-models-v1"
    FILE_DRIFT = "evaluation-file-drift-v1"
    POSTGRES_DRIFT = "evaluation-postgres-drift-v1"
    CUSTOM = "evaluation-custom"


WorkflowPreset: TypeAlias = (
    CollectionPreset | TrainingPreset | InferencePreset | EvaluationPreset
)
WorkflowConfig: TypeAlias = (
    CollectionWorkflowConfig
    | TrainingWorkflowConfig
    | InferenceWorkflowConfig
    | EvaluationWorkflowConfig
)


@dataclass(frozen=True)
class EvaluationPresetInputs:
    """Entradas explícitas que completan un preset read-only de evaluación."""

    champion_bundle_dir: str = ""
    challenger_bundle_dir: str = ""
    holdout_snapshot_path: str = ""
    bootstrap_samples: int = 1_000
    reference_feature_cohort_path: str = ""
    operational_feature_cohort_path: str = ""
    postgres_start_utc: str = ""
    postgres_end_utc: str = ""
    postgres_pipeline_run_ids: tuple[str, ...] = ()
    postgres_clip_ids: tuple[str, ...] = ()
    drift_plot_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.bootstrap_samples, int) or isinstance(
            self.bootstrap_samples, bool
        ):
            raise RuntimeConfigurationError("bootstrap_samples must be a positive integer.")
        if self.bootstrap_samples < 1:
            raise RuntimeConfigurationError("bootstrap_samples must be positive.")


@dataclass(frozen=True)
class WorkflowSummary:
    """Descripción segura de los efectos observables de una configuración."""

    preset_id: str
    title: str
    objective: str
    inputs: tuple[str, ...]
    requirements: tuple[str, ...]
    writes: tuple[str, ...]
    transfers: tuple[str, ...]
    warnings: tuple[str, ...]

    def render(self) -> str:
        """Renderiza un resumen legible sin incluir valores privados."""

        rows = (
            "✅ Configuración validada",
            f"🧭 Preset: {self.title} [{self.preset_id}]",
            f"   Objetivo: {self.objective}",
            f"   Entradas: {_render_items(self.inputs)}",
            f"   Requisitos: {_render_items(self.requirements)}",
            f"   Escrituras: {_render_items(self.writes)}",
            f"   Transferencias: {_render_items(self.transfers)}",
            f"   Advertencias: {_render_items(self.warnings)}",
            "➡️ Siguiente paso: continuá con la selección explícita de entradas.",
        )
        return "\n".join(rows)


_COLLECTION_PRESETS: Final[Mapping[CollectionPreset, CollectionWorkflowConfig]] = (
    MappingProxyType(
        {
            CollectionPreset.LOCAL: CollectionWorkflowConfig(False, False),
            CollectionPreset.POSTGRES: CollectionWorkflowConfig(True, False),
            CollectionPreset.TRACKING_DIAGNOSTIC: CollectionWorkflowConfig(False, True),
        }
    )
)

_TRAINING_PRESETS: Final[Mapping[TrainingPreset, TrainingWorkflowConfig]] = MappingProxyType(
    {
        TrainingPreset.SEED_UPLOAD: TrainingWorkflowConfig(
            "seed_bootstrap",
            False,
            True,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
        ),
        TrainingPreset.SEED_POSTGRES: TrainingWorkflowConfig(
            "seed_bootstrap",
            True,
            False,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
        ),
        TrainingPreset.HITL_CATALOG: TrainingWorkflowConfig(
            "hitl_retraining",
            False,
            False,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
        ),
        TrainingPreset.HITL_CATALOG_POSTGRES: TrainingWorkflowConfig(
            "hitl_retraining",
            True,
            False,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
        ),
        TrainingPreset.HITL_FROZEN_HOLDOUT: TrainingWorkflowConfig(
            "hitl_retraining",
            False,
            False,
            True,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
        ),
    }
)

_INFERENCE_PRESETS: Final[Mapping[InferencePreset, InferenceWorkflowConfig]] = (
    MappingProxyType(
        {
            InferencePreset.PILOT_OFFLINE: InferenceWorkflowConfig(
                True, False, False, False, "priority", False, True, False
            ),
            InferencePreset.PILOT_HITL: InferenceWorkflowConfig(
                True, False, False, True, "priority", False, True, False
            ),
            InferencePreset.PERSISTED_INFERENCE: InferenceWorkflowConfig(
                True, False, True, False, "priority", False, True, False
            ),
            InferencePreset.PERSISTED_HITL: InferenceWorkflowConfig(
                True, False, True, True, "priority", False, True, False
            ),
            InferencePreset.EXPERIMENTAL_OFFLINE: InferenceWorkflowConfig(
                False, True, False, False, "priority", False, True, False
            ),
        }
    )
)

_PRESET_TITLES: Final[Mapping[WorkflowPreset, str]] = MappingProxyType(
    {
        CollectionPreset.LOCAL: "Recolección local",
        CollectionPreset.POSTGRES: "Recolección con PostgreSQL",
        CollectionPreset.TRACKING_DIAGNOSTIC: "Diagnóstico de tracking",
        CollectionPreset.CUSTOM: "Recolección personalizada",
        TrainingPreset.SEED_UPLOAD: "Semilla desde upload",
        TrainingPreset.SEED_POSTGRES: "Semilla desde PostgreSQL",
        TrainingPreset.HITL_CATALOG: "HITL desde catálogo",
        TrainingPreset.HITL_CATALOG_POSTGRES: "HITL con catálogo y PostgreSQL",
        TrainingPreset.HITL_FROZEN_HOLDOUT: "HITL con holdout congelado",
        TrainingPreset.CUSTOM: "Entrenamiento personalizado",
        InferencePreset.PILOT_OFFLINE: "Piloto offline",
        InferencePreset.PILOT_HITL: "Piloto con revisión HITL",
        InferencePreset.PERSISTED_INFERENCE: "Inferencia persistida",
        InferencePreset.PERSISTED_HITL: "Inferencia persistida con HITL",
        InferencePreset.EXPERIMENTAL_OFFLINE: "Candidato experimental offline",
        InferencePreset.CUSTOM: "Inferencia personalizada",
        EvaluationPreset.CHECK_ONLY: "Verificación del entorno",
        EvaluationPreset.COMPARE_MODELS: "Comparación Champion--Challenger",
        EvaluationPreset.FILE_DRIFT: "Deriva entre archivos",
        EvaluationPreset.POSTGRES_DRIFT: "Deriva contra PostgreSQL",
        EvaluationPreset.CUSTOM: "Evaluación personalizada",
    }
)

PresetT = TypeVar("PresetT", bound=Enum)
ConfigT = TypeVar("ConfigT")


def _resolve_named_config(
    preset: PresetT,
    *,
    custom_member: PresetT,
    presets: Mapping[PresetT, ConfigT],
    custom_config: ConfigT | None,
) -> ConfigT:
    if preset == custom_member:
        if custom_config is None:
            raise RuntimeConfigurationError("CUSTOM requires an explicit typed configuration.")
        return custom_config
    if custom_config is not None:
        raise RuntimeConfigurationError(
            "custom_config is valid only when the selected preset is CUSTOM."
        )
    try:
        return presets[preset]
    except KeyError as exc:
        raise RuntimeConfigurationError("The selected workflow preset is not supported.") from exc


def collection_preset_config(preset: CollectionPreset) -> CollectionWorkflowConfig:
    """Devuelve la configuración inmutable de un preset de recolección."""

    return _resolve_named_config(
        preset,
        custom_member=CollectionPreset.CUSTOM,
        presets=_COLLECTION_PRESETS,
        custom_config=None,
    )


def resolve_collection_config(
    preset: CollectionPreset,
    *,
    custom_config: CollectionWorkflowConfig | None = None,
) -> CollectionWorkflowConfig:
    """Resuelve un preset o una configuración personalizada de recolección."""

    return _resolve_named_config(
        preset,
        custom_member=CollectionPreset.CUSTOM,
        presets=_COLLECTION_PRESETS,
        custom_config=custom_config,
    )


def training_preset_config(preset: TrainingPreset) -> TrainingWorkflowConfig:
    """Devuelve la configuración inmutable de un preset de entrenamiento."""

    return _resolve_named_config(
        preset,
        custom_member=TrainingPreset.CUSTOM,
        presets=_TRAINING_PRESETS,
        custom_config=None,
    )


def resolve_training_config(
    preset: TrainingPreset,
    *,
    custom_config: TrainingWorkflowConfig | None = None,
) -> TrainingWorkflowConfig:
    """Resuelve un preset o una configuración personalizada de entrenamiento."""

    return _resolve_named_config(
        preset,
        custom_member=TrainingPreset.CUSTOM,
        presets=_TRAINING_PRESETS,
        custom_config=custom_config,
    )


def inference_preset_config(preset: InferencePreset) -> InferenceWorkflowConfig:
    """Devuelve la configuración inmutable de un preset de inferencia."""

    return _resolve_named_config(
        preset,
        custom_member=InferencePreset.CUSTOM,
        presets=_INFERENCE_PRESETS,
        custom_config=None,
    )


def resolve_inference_config(
    preset: InferencePreset,
    *,
    custom_config: InferenceWorkflowConfig | None = None,
) -> InferenceWorkflowConfig:
    """Resuelve un preset o una configuración personalizada de inferencia."""

    return _resolve_named_config(
        preset,
        custom_member=InferencePreset.CUSTOM,
        presets=_INFERENCE_PRESETS,
        custom_config=custom_config,
    )


def _has_values(values: tuple[object, ...]) -> bool:
    return any(bool(value) for value in values)


def _reject_inputs(preset: EvaluationPreset, values: tuple[object, ...]) -> None:
    if _has_values(values):
        raise RuntimeConfigurationError(
            f"{preset.value} received inputs that belong to another evaluation flow."
        )


def _evaluation_check_config(inputs: EvaluationPresetInputs) -> EvaluationWorkflowConfig:
    _reject_inputs(
        EvaluationPreset.CHECK_ONLY,
        (
            inputs.champion_bundle_dir,
            inputs.challenger_bundle_dir,
            inputs.holdout_snapshot_path,
            inputs.reference_feature_cohort_path,
            inputs.operational_feature_cohort_path,
            inputs.postgres_start_utc,
            inputs.postgres_end_utc,
            inputs.postgres_pipeline_run_ids,
            inputs.postgres_clip_ids,
            inputs.drift_plot_features,
        ),
    )
    return EvaluationWorkflowConfig(False, "", "", "", inputs.bootstrap_samples, False, "", "", False, "", "")


def _evaluation_comparison_config(
    inputs: EvaluationPresetInputs,
) -> EvaluationWorkflowConfig:
    _reject_inputs(
        EvaluationPreset.COMPARE_MODELS,
        (
            inputs.reference_feature_cohort_path,
            inputs.operational_feature_cohort_path,
            inputs.postgres_start_utc,
            inputs.postgres_end_utc,
            inputs.postgres_pipeline_run_ids,
            inputs.postgres_clip_ids,
            inputs.drift_plot_features,
        ),
    )
    return EvaluationWorkflowConfig(
        True,
        inputs.champion_bundle_dir,
        inputs.challenger_bundle_dir,
        inputs.holdout_snapshot_path,
        inputs.bootstrap_samples,
        False,
        "",
        "",
        False,
        "",
        "",
    )


def _evaluation_file_drift_config(
    inputs: EvaluationPresetInputs,
) -> EvaluationWorkflowConfig:
    _reject_inputs(
        EvaluationPreset.FILE_DRIFT,
        (
            inputs.champion_bundle_dir,
            inputs.challenger_bundle_dir,
            inputs.holdout_snapshot_path,
            inputs.postgres_start_utc,
            inputs.postgres_end_utc,
            inputs.postgres_pipeline_run_ids,
            inputs.postgres_clip_ids,
        ),
    )
    return EvaluationWorkflowConfig(
        False,
        "",
        "",
        "",
        inputs.bootstrap_samples,
        True,
        inputs.reference_feature_cohort_path,
        inputs.operational_feature_cohort_path,
        False,
        "",
        "",
        drift_plot_features=inputs.drift_plot_features,
    )


def _evaluation_postgres_drift_config(
    inputs: EvaluationPresetInputs,
) -> EvaluationWorkflowConfig:
    _reject_inputs(
        EvaluationPreset.POSTGRES_DRIFT,
        (
            inputs.champion_bundle_dir,
            inputs.challenger_bundle_dir,
            inputs.holdout_snapshot_path,
            inputs.operational_feature_cohort_path,
        ),
    )
    return EvaluationWorkflowConfig(
        False,
        "",
        "",
        "",
        inputs.bootstrap_samples,
        True,
        inputs.reference_feature_cohort_path,
        "",
        True,
        inputs.postgres_start_utc,
        inputs.postgres_end_utc,
        postgres_pipeline_run_ids=inputs.postgres_pipeline_run_ids,
        postgres_clip_ids=inputs.postgres_clip_ids,
        drift_plot_features=inputs.drift_plot_features,
    )


def evaluation_preset_config(
    preset: EvaluationPreset,
    *,
    inputs: EvaluationPresetInputs | None = None,
) -> EvaluationWorkflowConfig:
    """Construye un flujo de evaluación con sus entradas explícitas."""

    active_inputs = inputs or EvaluationPresetInputs()
    if preset is EvaluationPreset.CHECK_ONLY:
        return _evaluation_check_config(active_inputs)
    if preset is EvaluationPreset.COMPARE_MODELS:
        return _evaluation_comparison_config(active_inputs)
    if preset is EvaluationPreset.FILE_DRIFT:
        return _evaluation_file_drift_config(active_inputs)
    if preset is EvaluationPreset.POSTGRES_DRIFT:
        return _evaluation_postgres_drift_config(active_inputs)
    raise RuntimeConfigurationError("CUSTOM requires an explicit typed configuration.")


def resolve_evaluation_config(
    preset: EvaluationPreset,
    *,
    preset_inputs: EvaluationPresetInputs | None = None,
    custom_config: EvaluationWorkflowConfig | None = None,
) -> EvaluationWorkflowConfig:
    """Resuelve un preset o una configuración personalizada de evaluación."""

    if preset is EvaluationPreset.CUSTOM:
        if custom_config is None:
            raise RuntimeConfigurationError("CUSTOM requires an explicit typed configuration.")
        if preset_inputs is not None:
            raise RuntimeConfigurationError("CUSTOM does not accept preset_inputs.")
        return custom_config
    if custom_config is not None:
        raise RuntimeConfigurationError(
            "custom_config is valid only when the selected preset is CUSTOM."
        )
    return evaluation_preset_config(preset, inputs=preset_inputs)


def _render_items(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "ninguna"


def _collection_summary(config: CollectionWorkflowConfig) -> WorkflowSummary:
    requirements = ["GPU y YOLO"]
    writes = ["video anotado y CSV raw en el runtime"]
    warnings: list[str] = []
    if config.persist_to_database:
        requirements.append("perfil PostgreSQL collection")
        writes.append("telemetría raw idempotente en PostgreSQL")
    if config.hud_debug:
        warnings.append("el HUD incluye señales técnicas")
    if config.view_plan_path is not None:
        requirements.append("plan privado de vistas configurado")
    transfers = ("descarga explícita de video y CSV",) if config.download_outputs else ()
    return WorkflowSummary(
        "",
        "",
        "Generar telemetría cruda y un video anotado.",
        ("video MP4",),
        tuple(requirements),
        tuple(writes),
        transfers,
        tuple(warnings),
    )


def _training_summary(config: TrainingWorkflowConfig) -> WorkflowSummary:
    inputs = [
        "backup o CSV raw"
        if config.training_mode == "seed_bootstrap"
        else "semilla inmutable y catálogo HITL"
    ]
    requirements = ["GPU TensorFlow", "Google Drive para objetos gobernados"]
    writes = ["bundle local", "input lock y objetos inmutables en Drive"]
    warnings: list[str] = []
    if config.enable_postgres_ingestion:
        inputs.append("PostgreSQL read-only")
        requirements.append("perfil PostgreSQL training")
        if config.postgres_telemetry_read_mode == "legacy":
            warnings.append("telemetría PostgreSQL legacy seleccionada explícitamente")
    if config.enable_data_upload:
        requirements.append("upload explícito del archivo raw")
    if config.write_training_report:
        writes.append("informe inmutable y diagnósticos")
    if config.copy_bundle_to_drive:
        writes.append("copia validada del bundle en Drive")
    if config.run_grouped_cross_validation:
        warnings.append("validación cruzada adicional habilitada")
    if config.training_mode == "hitl_retraining" and not config.human_holdout_frozen:
        warnings.append("holdout humano todavía no congelado")
    if "create_new_version" in (
        config.human_holdout_action,
        config.seed_artifact_action,
    ):
        warnings.append("se creará una nueva generación inmutable")
    return WorkflowSummary(
        "",
        "",
        "Entrenar y evaluar un candidato MLP gobernado.",
        tuple(inputs),
        tuple(requirements),
        tuple(writes),
        (),
        tuple(warnings),
    )


def _inference_summary(config: InferenceWorkflowConfig) -> WorkflowSummary:
    allowed = ["production"]
    if config.allow_pilot_bundle:
        allowed.append("pilot")
    if config.allow_experimental_bundle:
        allowed.append("candidate offline")
    requirements = ["GPU y YOLO"]
    writes = ["video anotado y resultados en el runtime"]
    warnings: list[str] = []
    if config.persist_to_database:
        requirements.append("perfil PostgreSQL inference")
        writes.append("features y predicciones idempotentes en PostgreSQL")
    if config.enable_human_review:
        requirements.extend(("VAAET_REVIEWER_ID", "Drive al finalizar la revisión"))
        writes.append("paquete HITL inmutable")
        if config.persist_to_database:
            requirements.append("perfil PostgreSQL review")
            writes.append("validaciones humanas append-only")
    if config.allow_experimental_bundle:
        warnings.append("los candidatos experimentales nunca se persisten")
    if config.hud_debug:
        warnings.append("el HUD incluye señales técnicas")
    if config.view_plan_path is not None:
        requirements.append("plan privado de vistas configurado")
    transfers = (
        ("descarga explícita del video anotado",)
        if config.download_annotated_video
        else ()
    )
    return WorkflowSummary(
        "",
        "",
        "Clasificar un video con un bundle validado.",
        ("video MP4", f"bundle permitido: {', '.join(allowed)}"),
        tuple(requirements),
        tuple(writes),
        transfers,
        tuple(warnings),
    )


def _evaluation_summary(config: EvaluationWorkflowConfig) -> WorkflowSummary:
    inputs: list[str] = []
    requirements = ["runtime Python; GPU no obligatoria"]
    if config.run_model_evaluation:
        inputs.append("Champion, Challenger y holdout humano exacto")
    if config.run_drift_analysis:
        inputs.append("cohorte de referencia")
        if config.use_postgres_operational:
            inputs.append("telemetría PostgreSQL acotada")
            requirements.append("perfil PostgreSQL training read-only")
        else:
            inputs.append("cohorte operacional por archivo")
    if not inputs:
        inputs.append("sin datos; sólo verificación del entorno")
    return WorkflowSummary(
        "",
        "",
        "Auditar modelos o deriva sin modificar artefactos.",
        tuple(inputs),
        tuple(requirements),
        (),
        (),
        ("evaluación read-only; la promoción continúa siendo humana",),
    )


def render_workflow_summary(preset: WorkflowPreset, config: WorkflowConfig) -> str:
    """Describe la configuración final y redacta rutas o valores privados."""

    if isinstance(preset, CollectionPreset) and isinstance(
        config, CollectionWorkflowConfig
    ):
        summary = _collection_summary(config)
    elif isinstance(preset, TrainingPreset) and isinstance(config, TrainingWorkflowConfig):
        summary = _training_summary(config)
    elif isinstance(preset, InferencePreset) and isinstance(
        config, InferenceWorkflowConfig
    ):
        summary = _inference_summary(config)
    elif isinstance(preset, EvaluationPreset) and isinstance(
        config, EvaluationWorkflowConfig
    ):
        summary = _evaluation_summary(config)
    else:
        raise RuntimeConfigurationError("The preset and workflow configuration do not match.")
    return WorkflowSummary(
        preset_id=preset.value,
        title=_PRESET_TITLES[preset],
        objective=summary.objective,
        inputs=summary.inputs,
        requirements=summary.requirements,
        writes=summary.writes,
        transfers=summary.transfers,
        warnings=summary.warnings,
    ).render()
