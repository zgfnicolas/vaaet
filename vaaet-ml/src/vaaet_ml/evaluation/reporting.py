# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada compatible 4.x para métricas, resúmenes y visuales de evaluación."""

from vaaet_ml.evaluation.reporting_metrics import (
    build_classification_support_table,
    expected_calibration_error,
    expected_confusion_cost,
    false_alert_rate_upper_bound,
    grouped_classification_intervals,
    select_validation_decision_policy,
)
from vaaet_ml.evaluation.reporting_summaries import (
    build_class_support_notes,
    format_inference_result_summary,
    summarize_data_origin,
    summarize_resampled_balance,
    summarize_state_balance,
)
from vaaet_ml.evaluation.reporting_visuals import (
    plot_training_evaluation,
    plot_training_history,
    show_inference_dashboard,
)
from vaaet_ml.evaluation.training_observability_visuals import save_training_run_diagnostics

__all__ = [
    "build_class_support_notes",
    "build_classification_support_table",
    "expected_calibration_error",
    "expected_confusion_cost",
    "false_alert_rate_upper_bound",
    "format_inference_result_summary",
    "grouped_classification_intervals",
    "plot_training_evaluation",
    "plot_training_history",
    "select_validation_decision_policy",
    "save_training_run_diagnostics",
    "show_inference_dashboard",
    "summarize_data_origin",
    "summarize_resampled_balance",
    "summarize_state_balance",
]
