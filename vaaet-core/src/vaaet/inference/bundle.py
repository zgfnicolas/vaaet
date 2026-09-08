# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Carga manifest-first de bundles compatibles de estados de tránsito."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from vaaet.artifacts import (
    LABEL_MAPPING_FILE,
    MODEL_FILE,
    SCALER_FILE,
    TrafficBundleManifest,
    validate_manifest,
)
from vaaet.inference.protocols import FeatureScaler, TrafficStateModel
from vaaet.settings import FEATURE_COLS, STATE_LABELS


@dataclass(frozen=True)
class LoadedTrafficBundle:
    """Representa un bundle validado antes de deserializar sus binarios."""

    manifest: TrafficBundleManifest
    model: TrafficStateModel
    scaler: FeatureScaler
    label_mapping: dict[int, str]
    deployment_stage: str
    input_policy: str
    model_revision: str
    historical_only: bool


class BundleLoadPurpose(str, Enum):
    """Declara si el bundle se usará operacionalmente o sólo para historia."""

    INFERENCE = "inference"
    HISTORICAL_EVALUATION = "historical-evaluation"


def authorize_bundle(
    manifest: Mapping[str, object],
    *,
    allow_pilot: bool,
    allow_experimental: bool,
    persist_to_database: bool,
) -> tuple[str, str]:
    """Rechaza etapas no autorizadas antes de cargar bytes del modelo."""

    lifecycle = manifest["training_lifecycle"]
    if not isinstance(lifecycle, Mapping):
        raise ValueError("The bundle training lifecycle is invalid.")
    stage = lifecycle.get("deployment_stage")
    input_policy = lifecycle.get("input_policy")
    if not isinstance(stage, str) or not isinstance(input_policy, str):
        raise ValueError("The bundle lifecycle lacks deployment stage or input policy.")
    if stage == "pilot" and not allow_pilot:
        raise RuntimeError("El bundle piloto no está autorizado. Usá ALLOW_PILOT_BUNDLE=True.")
    if stage == "candidate" and not allow_experimental:
        raise RuntimeError("El bundle candidato requiere autorización offline explícita.")
    if stage == "candidate" and persist_to_database:
        raise RuntimeError(
            "Los bundles candidatos son sólo offline. Usá PERSIST_TO_DATABASE=False."
        )
    return stage, input_policy


def load_traffic_bundle(
    directory: Path,
    *,
    allow_pilot: bool,
    allow_experimental: bool,
    persist_to_database: bool,
    purpose: BundleLoadPurpose | str = BundleLoadPurpose.INFERENCE,
) -> LoadedTrafficBundle:
    """Valida manifiesto y lifecycle antes de deserializar el bundle."""

    active_purpose = BundleLoadPurpose(purpose)
    historical_only = active_purpose is BundleLoadPurpose.HISTORICAL_EVALUATION
    if historical_only and persist_to_database:
        raise RuntimeError("Historical bundles cannot persist operational predictions.")
    manifest = validate_manifest(directory, allow_historical_revision=historical_only)
    stage, input_policy = authorize_bundle(
        manifest,
        allow_pilot=allow_pilot,
        allow_experimental=allow_experimental,
        persist_to_database=persist_to_database,
    )
    import joblib
    import tensorflow as tf

    model = cast(TrafficStateModel, tf.keras.models.load_model(directory / MODEL_FILE))
    scaler = cast(FeatureScaler, joblib.load(directory / SCALER_FILE))
    label_mapping = joblib.load(directory / LABEL_MAPPING_FILE)
    if dict(label_mapping) != dict(STATE_LABELS):
        raise RuntimeError("label_mapping.joblib no coincide con los cuatro estados públicos.")
    if int(model.output_shape[-1]) != 3:
        raise RuntimeError("El MLP del bundle debe exponer exactamente tres estados estables.")
    if int(getattr(scaler, "n_features_in_", -1)) != len(FEATURE_COLS):
        raise RuntimeError("El scaler del bundle no coincide con el contrato de 19 features.")
    return LoadedTrafficBundle(
        manifest=manifest,
        model=model,
        scaler=scaler,
        label_mapping=dict(label_mapping),
        deployment_stage=stage,
        input_policy=input_policy,
        model_revision=str(manifest["model_revision"]),
        historical_only=historical_only,
    )
