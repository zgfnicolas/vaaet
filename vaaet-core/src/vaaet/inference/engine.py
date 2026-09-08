# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptador tipado entre bundle validado y análisis de video sin I/O externo."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from vaaet.inference.bundle import LoadedTrafficBundle
from vaaet.inference.traffic_state import classify_raw_telemetry
from vaaet.vision.analysis import TrafficStatePrediction


@dataclass(frozen=True)
class TrafficStateEngine:
    """Clasificador reutilizable para notebooks y workers de API.

    No administra rutas de artefactos, DVC, base de datos ni tareas; recibe un
    bundle ya validado y devuelve resultados en memoria.
    """

    bundle: LoadedTrafficBundle

    def classify(self, telemetry: pd.DataFrame) -> pd.DataFrame:
        """Clasifica minutos completos mediante la política validada del bundle."""

        return classify_raw_telemetry(
            telemetry,
            self.bundle.model,
            self.bundle.scaler,
            label_mapping=self.bundle.label_mapping,
            model_version=str(self.bundle.manifest["model_version"]),
            model_revision=self.bundle.model_revision,
            input_policy=self.bundle.input_policy,
            decision_policy=self.bundle.manifest["decision_policy"],
        )

    def predict_latest(self, telemetry: pd.DataFrame) -> TrafficStatePrediction | None:
        """Devuelve la última predicción tipada al pipeline ordenado de video."""

        classified = self.classify(telemetry)
        if classified.empty:
            return None
        latest = classified.iloc[-1]
        return TrafficStatePrediction(
            state=int(latest["traffic_state"]),
            label=str(latest["state_label"]),
            confidence=float(latest["confidence"]),
            evidence=float(latest.get("accident_evidence_score", 0.0)),
            incident_candidate=bool(latest.get("accident_rule_triggered", False)),
        )
