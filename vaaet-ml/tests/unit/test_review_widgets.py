# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptador ipywidgets validado con controles falsos, sin notebook interactivo."""

from __future__ import annotations

import sys
from types import ModuleType

import pandas as pd

from vaaet_ml.data.review_widgets import build_review_widget


class _Control:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)
        options = kwargs.get("options", ())
        self.value = kwargs.get("value", options[0][1] if options else "")
        self.disabled = False


class _Button(_Control):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.callbacks: list[object] = []

    def on_click(self, callback: object) -> None:
        self.callbacks.append(callback)


class _Output(_Control):
    def __enter__(self) -> _Output:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Box(_Control):
    def __init__(self, children: list[object]) -> None:
        super().__init__(children=children)


def _install_fake_widgets(monkeypatch) -> None:
    widgets = ModuleType("ipywidgets")
    widgets.HTML = _Control
    widgets.Dropdown = _Control
    widgets.Textarea = _Control
    widgets.Checkbox = _Control
    widgets.Button = _Button
    widgets.Output = _Output
    widgets.VBox = _Box
    widgets.HBox = _Box
    display_module = ModuleType("IPython.display")
    display_module.display = lambda _widget: None
    monkeypatch.setitem(sys.modules, "ipywidgets", widgets)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)


def test_widget_submits_decision_and_completes_queue(monkeypatch) -> None:
    _install_fake_widgets(monkeypatch)
    decisions: list[object] = []
    queue = pd.DataFrame(
        [{"prediction_id": 1, "traffic_state": 1, "state_label": "Reduced", "clip_id": "clip"}]
    )

    widget = build_review_widget(queue, reviewer_id="reviewer", on_submit=decisions.append)
    assert widget is not None
    submit = widget.children[4].children[0]
    submit.callbacks[0](None)

    assert len(decisions) == 1
    assert submit.disabled


def test_widget_returns_none_for_empty_queue(monkeypatch) -> None:
    _install_fake_widgets(monkeypatch)

    assert build_review_widget(pd.DataFrame(), reviewer_id="reviewer", on_submit=lambda _: None) is None


def test_widget_keeps_identity_after_uncertain_submission(monkeypatch) -> None:
    _install_fake_widgets(monkeypatch)
    decisions: list[object] = []

    def interrupted(decision: object) -> None:
        decisions.append(decision)
        raise RuntimeError("simulated lost response")

    queue = pd.DataFrame(
        [{"prediction_id": 1, "traffic_state": 1, "state_label": "Reduced", "clip_id": "clip"}]
    )
    widget = build_review_widget(queue, reviewer_id="reviewer", on_submit=interrupted)
    assert widget is not None
    submit, skip = widget.children[4].children
    submit.callbacks[0](None)
    submit.callbacks[0](None)
    assert len(decisions) == 2
    assert decisions[0].validation_id == decisions[1].validation_id
    assert decisions[0].reviewed_at == decisions[1].reviewed_at
    assert skip.disabled
