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
    HitlCatalogPublicationError,
    HitlCatalogPublisher,
    HitlReviewCatalog,
    _deduplicate_uuid_rows,
    _resolve_validation_graph,
    _validation_leaf_with_chain,
    resolve_effective_human_feedback,
)


def _complete_validations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["reviewer_id"] = "reviewer"
    result["reviewed_at"] = "2026-08-29T01:00:00Z"
    result["review_source"] = "test"
    result["incident_context_reviewed"] = False
    return result


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
        ({"fingerprint_algorithm": "unknown"}, "fingerprint algorithm"),
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
    catalog = HitlReviewCatalog(tmp_path / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        with pytest.raises(ValueError, match=message):
            catalog.register(_entry(**overrides), publisher=publisher)


def test_catalog_registration_and_status_operations_are_idempotent(tmp_path) -> None:
    catalog = HitlReviewCatalog(tmp_path / "catalog.json")
    entry = _entry(status="quarantined")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        first = catalog.register(entry, publisher=publisher)

        assert catalog.register(entry, publisher=publisher) == first
        with pytest.raises(ValueError, match="conflicts"):
            catalog.register({**entry, "rows": {"features": 2}}, publisher=publisher)
        with pytest.raises(ValueError, match="not a valid CatalogSelection"):
            catalog.selected_entries(cast(CatalogSelection, "unknown"))
        with pytest.raises(ValueError, match="status"):
            catalog.set_status(str(entry["package_id"]), "deleted", publisher=publisher)
        with pytest.raises(KeyError, match="not found"):
            catalog.set_status(str(uuid.uuid4()), "active", publisher=publisher)
        with pytest.raises(FileNotFoundError, match="Cataloged HITL package not found"):
            catalog.set_status(str(entry["package_id"]), "active", publisher=publisher)
        assert catalog.load() == first


def test_catalog_mutation_requires_one_active_local_publisher(tmp_path) -> None:
    catalog = HitlReviewCatalog(tmp_path / "catalog.json")
    lock_directory = tmp_path / "locks"

    with pytest.raises(HitlCatalogPublicationError, match="active local publisher"):
        catalog.register(_entry())
    with HitlCatalogPublisher(catalog, lock_directory=lock_directory) as first:
        first.register(_entry(status="quarantined"))
        with pytest.raises(HitlCatalogPublicationError, match="already active"):
            with HitlCatalogPublisher(catalog, lock_directory=lock_directory):
                pass
    with HitlCatalogPublisher(catalog, lock_directory=lock_directory) as second:
        second.register(_entry(status="quarantined"))

    assert len(catalog.load()["entries"]) == 2


def test_publisher_cleanup_is_idempotent_without_deleting_another_lock(tmp_path) -> None:
    catalog = HitlReviewCatalog(tmp_path / "catalog.json")
    lock_directory = tmp_path / "locks"
    first = HitlCatalogPublisher(catalog, lock_directory=lock_directory)
    with first:
        assert first.lock_path.is_file()

    with HitlCatalogPublisher(catalog, lock_directory=lock_directory) as second:
        first.__exit__(None, None, None)
        assert second.active
        assert second.lock_path.is_file()


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


def test_original_feature_uuid_conflict_is_rejected_before_alias_resolution() -> None:
    feature_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    features = pd.DataFrame(
        {
            "id": [feature_id, feature_id],
            "clip_id": ["clip-a", "clip-b"],
            "record_time": ["2026-08-29T00:00:00Z"] * 2,
        }
    )
    predictions = pd.DataFrame(
        {
            "id": [prediction_id],
            "telemetry_feature_id": [feature_id],
        }
    )
    validations = _complete_validations(
        pd.DataFrame(
            {
                "id": [str(uuid.uuid4())],
                "prediction_id": [prediction_id],
                "validated_state": [1],
                "is_human_validated": [True],
                "supersedes_validation_id": [pd.NA],
            }
        )
    )

    with pytest.raises(ValueError, match="Conflicting catalog features"):
        resolve_effective_human_feedback(features, predictions, validations)


@pytest.mark.parametrize(
    ("name", "reference_column", "message"),
    [
        ("predictions", "telemetry_feature_id", "catalog predictions"),
        ("validations", "prediction_id", "human labels"),
    ],
)
def test_original_prediction_and_validation_uuids_cannot_change_reference(
    name: str, reference_column: str, message: str
) -> None:
    identifier = str(uuid.uuid4())
    frame = pd.DataFrame(
        {
            "id": [identifier, identifier],
            reference_column: [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    )

    with pytest.raises(ValueError, match=message):
        _deduplicate_uuid_rows(frame, name=name)


def test_feedback_and_validation_graph_reject_inconsistent_relations() -> None:
    identifier = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="no compatible"):
        resolve_effective_human_feedback(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    features = pd.DataFrame({"id": [identifier], "record_time": ["2026-08-29T00:00:00Z"]})
    predictions = pd.DataFrame({"id": [prediction_id], "telemetry_feature_id": [str(uuid.uuid4())]})
    validations = _complete_validations(
        pd.DataFrame(
            {
                "id": [str(uuid.uuid4())],
                "prediction_id": [prediction_id],
                "validated_state": [1],
                "is_human_validated": [True],
                "supersedes_validation_id": [pd.NA],
            }
        )
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
    unknown_parent = _complete_validations(
        pd.DataFrame(
            {
                "id": [first],
                "prediction_id": [prediction_id],
                "validated_state": [1],
                "is_human_validated": [True],
                "supersedes_validation_id": [str(uuid.uuid4())],
            }
        )
    )
    with pytest.raises(ValueError, match="unknown validation"):
        _resolve_validation_graph(unknown_parent)

    roots = _complete_validations(
        pd.DataFrame(
            {
                "id": [first, second],
                "prediction_id": [prediction_id, prediction_id],
                "validated_state": [1, 2],
                "is_human_validated": [True, True],
                "supersedes_validation_id": [pd.NA, pd.NA],
            }
        )
    )
    with pytest.raises(ValueError, match="conflicting roots"):
        _resolve_validation_graph(roots)
    with pytest.raises(ValueError, match="cycle"):
        _validation_leaf_with_chain(first, {first: [second], second: [first]}, prediction_id)


def test_validation_graph_rejects_disconnected_cycle_beside_valid_root() -> None:
    prediction_id = str(uuid.uuid4())
    root, first, second = (str(uuid.uuid4()) for _ in range(3))
    graph = _complete_validations(
        pd.DataFrame(
            {
                "id": [root, first, second],
                "prediction_id": [prediction_id] * 3,
                "validated_state": [0, 1, 2],
                "is_human_validated": [True] * 3,
                "supersedes_validation_id": [pd.NA, second, first],
            }
        )
    )

    with pytest.raises(ValueError, match="unreachable|disconnected"):
        _resolve_validation_graph(graph)
