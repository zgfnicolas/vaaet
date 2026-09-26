# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptador opcional ipywidgets para presentar una cola de revisión en Colab."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pandas as pd
from vaaet.settings import STATE_LABELS

from vaaet_ml.data.review_domain import HumanValidation
from vaaet_ml.data.review_orchestration import (
    ManagedReviewSession,
    ReviewSubmissionController,
    ReviewSubmissionResult,
    ReviewSubmissionStatus,
)


def build_review_widget(  # noqa: C901 - adapta el controlador al widget opcional.
    queue: pd.DataFrame,
    *,
    reviewer_id: str,
    on_submit: Callable[[HumanValidation], ReviewSubmissionResult | None],
    session: ManagedReviewSession | None = None,
) -> object | None:
    """Construye UI diferida; ``print`` queda limitado a la presentación notebook."""

    import ipywidgets as widgets
    from IPython.display import display

    if queue.empty:
        print("No pending rows match the selected review mode.")
        return None
    position = {"value": 0}
    heading = widgets.HTML()
    state = widgets.Dropdown(
        options=[(label, code) for code, label in STATE_LABELS.items()],
        description="Validated:",
    )
    notes = widgets.Textarea(description="Notes:")
    context = widgets.Checkbox(description="I reviewed temporal context")
    submit = widgets.Button(description="Save validation", button_style="success")
    skip = widgets.Button(description="Skip")
    output = widgets.Output()
    controller = ReviewSubmissionController(session=session)

    def render() -> None:
        row = queue.iloc[position["value"]]
        current_state = row.get("current_validated_state")
        state.value = int(
            row["traffic_state"] if current_state is None or pd.isna(current_state) else current_state
        )
        notes.value = ""
        context.value = False
        controller.reset()
        for field in (state, notes, context):
            field.disabled = False
        skip.disabled = False
        submit.description = "Save validation"
        heading.value = (
            f"<b>{position['value'] + 1}/{len(queue)}</b> — {row.get('clip_id')} "
            f"{row.get('record_time')} — predicted {row.get('state_label')} "
            f"(confidence={float(row.get('confidence', 0)):.3f}, "
            f"incident={bool(row.get('accident_rule_triggered', False))})"
        )

    def advance() -> None:
        controller.reset()
        if position["value"] + 1 < len(queue):
            position["value"] += 1
            render()
            return
        heading.value = "<b>Review queue completed.</b>"
        submit.disabled = True
        skip.disabled = True

    def submit_row(_button: object) -> None:
        row = queue.iloc[position["value"]]
        decision = controller.prepare(
            lambda: HumanValidation(
                prediction_id=int(row["prediction_id"]),
                validated_state=int(state.value),
                reviewer_id=reviewer_id,
                notes=notes.value.strip() or None,
                incident_context_reviewed=bool(context.value),
                supersedes_validation_id=(
                    UUID(str(row["latest_validation_id"]))
                    if pd.notna(row.get("latest_validation_id"))
                    else None
                ),
            )
        )
        for field in (state, notes, context):
            field.disabled = True
        skip.disabled = True
        with output:
            try:
                result = controller.submit(on_submit)
            except Exception as exc:
                submit.description = "Check same decision"
                print(
                    "No confirmado. Conservá esta validación y comprobá su UUID antes "
                    f"de reintentar: {decision.validation_id} ({type(exc).__name__})."
                )
                return
            if controller.status is ReviewSubmissionStatus.AUDIT_PENDING:
                submit.description = "Complete audit"
                print(
                    "Guardado; auditoría pendiente. Volvé a pulsar Complete audit "
                    "para reconciliar la misma decisión."
                )
                return
            print(
                f"Saved {STATE_LABELS[(result.decision if result else decision).validated_state]} "
                f"for {row.get('record_time')}"
            )
        advance()

    submit.on_click(submit_row)
    def skip_row(_button: object) -> None:
        if controller.decision is not None:
            raise RuntimeError("Resolve the current review decision before skipping.")
        advance()

    cast(Callable[[Callable[[object], None]], None], skip.on_click)(skip_row)
    render()
    widget = widgets.VBox([heading, state, notes, context, widgets.HBox([submit, skip]), output])
    display(widget)
    return widget


__all__ = ["build_review_widget"]
