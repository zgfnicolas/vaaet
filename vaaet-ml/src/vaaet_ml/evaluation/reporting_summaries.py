# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Resúmenes tabulares de soporte y procedencia sin representación gráfica."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np
import pandas as pd
from vaaet.settings import DATA_ORIGIN_COL, STATE_LABELS, SYNTHETIC_SCENARIO_COL


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")


def summarize_data_origin(frame: pd.DataFrame) -> pd.DataFrame:
    """Resume soporte real y sintético sin alterar la muestra de entrada."""

    _require_columns(frame, (DATA_ORIGIN_COL, SYNTHETIC_SCENARIO_COL))
    summary = (
        frame.groupby([DATA_ORIGIN_COL, SYNTHETIC_SCENARIO_COL], dropna=False)
        .size()
        .rename("records")
        .reset_index()
        .sort_values([DATA_ORIGIN_COL, SYNTHETIC_SCENARIO_COL])
        .reset_index(drop=True)
    )
    summary["percentage"] = (summary["records"] / max(len(frame), 1) * 100.0).round(2)
    return summary


def summarize_state_balance(
    frame: pd.DataFrame,
    *,
    state_col: str = "traffic_state",
) -> pd.DataFrame:
    """Resume la distribución por estado y procedencia cuando está disponible."""

    _require_columns(frame, (state_col,))
    if DATA_ORIGIN_COL in frame.columns:
        counts = frame.groupby([state_col, DATA_ORIGIN_COL], dropna=False).size().unstack(fill_value=0)
    else:
        counts = pd.DataFrame(index=sorted(frame[state_col].dropna().unique()))
    for origin in ("real", "synthetic"):
        if origin not in counts.columns:
            counts[origin] = 0
    counts = counts[["real", "synthetic"]]
    counts["total"] = counts.sum(axis=1)
    counts["pct_total"] = (counts["total"] / max(int(counts["total"].sum()), 1) * 100.0).round(2)
    summary = counts.reset_index().rename(columns={state_col: "traffic_state"})
    summary["state_label"] = summary["traffic_state"].map(STATE_LABELS)
    return summary[
        ["traffic_state", "state_label", "real", "synthetic", "total", "pct_total"]
    ].sort_values("traffic_state", ignore_index=True)


def summarize_resampled_balance(
    labels_before: Sequence[int] | np.ndarray,
    labels_after: Sequence[int] | np.ndarray,
) -> pd.DataFrame:
    """Compara soporte previo y posterior a SMOTE u otro remuestreo."""

    before = pd.Series(list(labels_before), dtype=int).value_counts().sort_index()
    after = pd.Series(list(labels_after), dtype=int).value_counts().sort_index()
    rows = [
        {
            "traffic_state": int(code),
            "state_label": STATE_LABELS.get(int(code), f"Unknown-{code}"),
            "before": int(before.get(code, 0)),
            "after": int(after.get(code, 0)),
            "delta": int(after.get(code, 0) - before.get(code, 0)),
        }
        for code in sorted(set(before.index).union(after.index))
    ]
    return pd.DataFrame(rows)


def build_class_support_notes(
    frame: pd.DataFrame,
    *,
    state_col: str = "traffic_state",
) -> list[str]:
    """Genera advertencias breves para soporte escaso o de origen sintético."""

    notes = [
        note
        for row in summarize_state_balance(frame, state_col=state_col).itertuples(index=False)
        if (note := _support_note(row)) is not None
    ]
    return notes or [
        "All present classes currently have real support, but per-class metrics should still be reported separately."
    ]


def format_inference_result_summary(
    frame: pd.DataFrame,
    *,
    state_labels: Mapping[int, str] = STATE_LABELS,
) -> str:
    """Formatea el resumen público de una clasificación ya validada."""

    _require_columns(frame, ("traffic_state",))
    if frame.empty:
        raise ValueError("Inference summary requires at least one classified minute.")
    lines = ["✅ Minutos clasificados por estado:"]
    for code in sorted(frame["traffic_state"].unique()):
        count = int(frame["traffic_state"].eq(code).sum())
        lines.append(f"   {state_labels.get(int(code), 'Desconocido'):>10}: {count} minutos")
    automatic_accidents = int(frame["traffic_state"].eq(3).sum())
    incident_candidates = int(
        frame.get("accident_alert_started", pd.Series(False, index=frame.index)).sum()
    )
    lines.extend(
        (
            f"   Accident automáticos: {automatic_accidents} (siempre debe ser cero)",
            f"   Posibles incidentes: {incident_candidates} (el estado permanece Congested)",
        )
    )
    return "\n".join(lines)


class _BalanceRow(Protocol):
    total: int
    state_label: str
    real: int
    synthetic: int


def _support_note(row: _BalanceRow) -> str | None:
    if row.total == 0:
        return f"{row.state_label} has no support in the current dataset and should be excluded from claims."
    if row.state_label == "Accident" and row.real == 0 and row.synthetic > 0:
        return "Accident is currently supported only by synthetic sequences and rule-based proxies; treat recall claims conservatively."
    if row.state_label == "Accident" and row.real > 0 and row.synthetic > 0:
        return "Accident mixes real and synthetic support; keep its evaluation separated from the frequent classes."
    if row.state_label != "Accident" and row.synthetic > row.real and row.synthetic > 0:
        return f"{row.state_label} relies more on synthetic than real support; report that dependency explicitly."
    return None


__all__ = [
    "build_class_support_notes",
    "format_inference_result_summary",
    "summarize_data_origin",
    "summarize_resampled_balance",
    "summarize_state_balance",
]
