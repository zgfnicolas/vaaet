# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contrato compartido de continuidad temporal para telemetría y estados."""

from __future__ import annotations

import pandas as pd

from vaaet.settings import CONTINUITY_MAX_GAP_SECONDS
from vaaet.timestamps import normalize_timestamp_series

CONTINUITY_COLUMN = "continuity_id"

__all__ = ["CONTINUITY_COLUMN", "normalize_continuity_frame"]


def normalize_continuity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Valida el orden y materializa tramos continuos deterministas.

    Un cambio explícito de continuidad o un hueco superior al contrato abre un
    tramo nuevo. Los datos legacy sin identificador se segmentan por clip y
    tiempo; nunca se transporta memoria a través de un hueco.
    """

    result = _validate_temporal_identity(frame)
    explicit = result.get(CONTINUITY_COLUMN)
    explicit_values = _explicit_values(explicit, result.index)
    result[CONTINUITY_COLUMN] = _assign_continuity(result, explicit_values)
    return result


def _validate_temporal_identity(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted({"clip_id", "record_time"} - set(frame.columns))
    if missing:
        raise ValueError(f"Telemetry is missing continuity columns: {missing}")

    result = frame.copy()
    clips = result["clip_id"]
    if clips.isna().any() or clips.astype(str).str.strip().eq("").any():
        raise ValueError("clip_id must be present for every telemetry record.")
    result["clip_id"] = clips.astype(str)
    result["record_time"] = normalize_timestamp_series(result["record_time"])
    if result.duplicated(["clip_id", "record_time"]).any():
        raise ValueError("Duplicate (clip_id, record_time) telemetry records are not allowed.")

    for clip_id, group in result.groupby("clip_id", sort=False):
        if not group["record_time"].is_monotonic_increasing:
            raise ValueError(f"record_time must be monotonic within clip_id={clip_id!r}.")

    result = result.sort_values(["clip_id", "record_time"], kind="stable").reset_index(drop=True)
    return result


def _explicit_values(explicit: pd.Series | None, index: pd.Index) -> pd.Series:
    if explicit is None:
        return pd.Series(pd.NA, index=index, dtype="string")
    values = explicit.astype("string")
    invalid = values.notna() & values.str.strip().eq("")
    if invalid.any():
        raise ValueError("continuity_id cannot be empty when it is provided.")
    return values


def _assign_continuity(result: pd.DataFrame, explicit_values: pd.Series) -> pd.Series:
    gap_limit = pd.Timedelta(seconds=CONTINUITY_MAX_GAP_SECONDS)
    assigned = pd.Series(index=result.index, dtype="string")
    for clip_id, positions in result.groupby("clip_id", sort=False).groups.items():
        indices = list(positions)
        prior_time: pd.Timestamp | None = None
        prior_explicit: str | None = None
        segment = 0
        seen_explicit: set[str] = set()
        active_id = ""
        for index in indices:
            current_time = result.at[index, "record_time"]
            raw_explicit = explicit_values.at[index]
            current_explicit = None if pd.isna(raw_explicit) else str(raw_explicit)
            gap = prior_time is not None and current_time - prior_time > gap_limit
            explicit_change = prior_time is not None and current_explicit != prior_explicit
            if prior_time is None or gap or explicit_change:
                segment += 1
                if (
                    explicit_change
                    and current_explicit is not None
                    and current_explicit in seen_explicit
                ):
                    raise ValueError(
                        f"continuity_id={current_explicit!r} reappears non-contiguously "
                        f"within clip_id={clip_id!r}."
                    )
                if current_explicit is not None:
                    seen_explicit.add(current_explicit)
                instant = current_time.strftime("%Y%m%dT%H%M%S%fZ")
                base = current_explicit or f"{clip_id}:continuity-{instant}"
                active_id = (
                    f"{base}:gap-{instant}"
                    # Si el identificador ya cambió, ese cambio representa el
                    # límite. Esto vuelve idempotente una segunda normalización.
                    if gap and current_explicit is not None and not explicit_change
                    else base
                )
            assigned.at[index] = active_id
            prior_time = current_time
            prior_explicit = current_explicit

    return assigned
