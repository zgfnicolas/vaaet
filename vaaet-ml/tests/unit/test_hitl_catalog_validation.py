# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos de borde del catálogo HITL independiente de widgets y notebooks."""

from __future__ import annotations

import uuid
from typing import cast

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.hitl_catalog import (
    CatalogSelection,
    HitlReviewCatalog,
    _deduplicate_uuid_rows,
    _resolve_validation_graph,
    _validation_leaf,
    resolve_effective_human_feedback,
)


def _entry(**overrides: object) -> dict[str, object]:
    package_id = str(uuid.uuid4())
    entry = {
        "package_id": package_id,
        "path": f"2026/08/29/{package_id}/vaaet-training-dataset-v1.zip",
        "created_at": "2026-08-29T12:00:00+00:00",
        "pipeline_run_id": str(uuid.uuid4()),
        "sha256": "a" * 64,
        "fingerprint": "b" * 64,
        "clips": 1,
        "rows": {"features": 1},
        "human_support": {"validated": 1},
        "status": "active",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_revision": "c" * 64,
        "vaaet_version": "4.6.1",
    }
    return {**entry, **overrides}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({}, "Unsupported HITL catalog contract"),
        ({"contract": "vaaet-dataset-catalog-v1", "revision": -1, "entries": []}, "revision"),
        ({"contract": "vaaet-dataset-catalog-v1", "revision": 0, "entries": {}}, "entries"),
    ],
)
def test_catalog_rejects_invalid_documents(document: object, message: str, tmp_path) -> None:
    with pytest.raises(ValueError, match=message):
        HitlReviewCatalog(tmp_path / "catalog.json")._validate(document)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"package_id": "not-uuid"}, "UUIDs"),
        ({"path": "other.zip"}, "contractual HITL filename"),
        ({"sha256": "bad"}, "checksums"),
        ({"status": "deleted"}, "status"),
        ({"feature_schema_version": "unknown"}, "schema"),
        ({"created_at": "2026-08-29T12:00:00"}, "timezone"),
        ({"clips": -1}, "clip count"),
        ({"rows": {"features": -1}}, "rows"),
        ({"human_support": []}, "human_support"),
        ({"vaaet_version": ""}, "VAAET version"),
    ],
)
def test_catalog_rejects_invalid_entry_fields(
    overrides: dict[str, object], message: str, tmp_path
) -> None:
    with pytest.raises(ValueError, match=message):
        HitlReviewCatalog(tmp_path / "catalog.json").register(_entry(**overrides))


def test_catalog_registration_and_status_operations_are_idempotent(tmp_path) -> None:
    catalog = HitlReviewCatalog(tmp_path / "catalog.json")
    entry = _entry()
    first = catalog.register(entry)

    assert catalog.register(entry) == first
    with pytest.raises(ValueError, match="conflicts"):
        catalog.register({**entry, "rows": {"features": 2}})
    with pytest.raises(ValueError, match="not a valid CatalogSelection"):
        catalog.selected_entries(cast(CatalogSelection, "unknown"))
    with pytest.raises(ValueError, match="status"):
        catalog.set_status(str(entry["package_id"]), "deleted")
    with pytest.raises(KeyError, match="not found"):
        catalog.set_status(str(uuid.uuid4()), "active")
    assert catalog.set_status(str(entry["package_id"]), "active") == first


def test_catalog_deduplication_rejects_invalid_or_conflicting_rows() -> None:
    identifier = str(uuid.uuid4())
    assert _deduplicate_uuid_rows(pd.DataFrame(), name="features").empty
    with pytest.raises(ValueError, match="require globally unique"):
        _deduplicate_uuid_rows(pd.DataFrame({"value": [1]}), name="features")
    with pytest.raises(ValueError, match="non-UUID"):
        _deduplicate_uuid_rows(pd.DataFrame({"id": ["bad"]}), name="features")
    conflicting = pd.DataFrame({"id": [identifier, identifier], "value": [1, 2]})
    with pytest.raises(ValueError, match="Conflicting"):
        _deduplicate_uuid_rows(conflicting, name="features")


def test_feedback_and_validation_graph_reject_inconsistent_relations() -> None:
    identifier = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="no compatible"):
        resolve_effective_human_feedback(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    features = pd.DataFrame({"id": [identifier], "record_time": ["2026-08-29T00:00:00Z"]})
    predictions = pd.DataFrame(
        {"id": [prediction_id], "telemetry_feature_id": [str(uuid.uuid4())]}
    )
    validations = pd.DataFrame(
        {
            "id": [str(uuid.uuid4())],
            "prediction_id": [prediction_id],
            "validated_state": [1],
            "is_human_validated": [True],
            "supersedes_validation_id": [pd.NA],
        }
    )
    with pytest.raises(ValueError, match="missing feature UUIDs"):
        resolve_effective_human_feedback(features, predictions, validations)

    assert _resolve_validation_graph(pd.DataFrame()).empty
    with pytest.raises(ValueError, match="missing fields"):
        _resolve_validation_graph(pd.DataFrame({"id": [identifier]}))
    with pytest.raises(ValueError, match="prediction_id values"):
        _resolve_validation_graph(validations.assign(prediction_id="bad"))


def test_validation_graph_rejects_invalid_topology() -> None:
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    unknown_parent = pd.DataFrame(
        {
            "id": [first],
            "prediction_id": [prediction_id],
            "validated_state": [1],
            "is_human_validated": [True],
            "supersedes_validation_id": [str(uuid.uuid4())],
        }
    )
    with pytest.raises(ValueError, match="unknown validation"):
        _resolve_validation_graph(unknown_parent)

    roots = pd.DataFrame(
        {
            "id": [first, second],
            "prediction_id": [prediction_id, prediction_id],
            "validated_state": [1, 2],
            "is_human_validated": [True, True],
            "supersedes_validation_id": [pd.NA, pd.NA],
        }
    )
    with pytest.raises(ValueError, match="conflicting roots"):
        _resolve_validation_graph(roots)
    with pytest.raises(ValueError, match="cycle"):
        _validation_leaf(first, {first: [second], second: [first]}, prediction_id)
