# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Auditoría read-only del contrato y la operación PostgreSQL de VAAET."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from vaaet_persistence import __version__
from vaaet_persistence.connection import database_engine
from vaaet_persistence.settings import (
    DatabaseProfile,
    load_database_settings,
)


def _rows(connection: Connection, statement: str) -> list[dict[str, Any]]:
    try:
        with connection.begin_nested():
            return [dict(row) for row in connection.execute(text(statement)).mappings()]
    except Exception as exc:  # El informe aísla permisos y objetos opcionales por sección.
        return [{"audit_error": type(exc).__name__}]


def _mapping(connection: Connection, statement: str) -> dict[str, Any]:
    try:
        with connection.begin_nested():
            return dict(connection.execute(text(statement)).mappings().one())
    except Exception as exc:
        return {"audit_error": type(exc).__name__}


def _scalar(connection: Connection, statement: str) -> object:
    try:
        with connection.begin_nested():
            return connection.execute(text(statement)).scalar_one()
    except Exception as exc:
        return {"audit_error": type(exc).__name__}


def audit_database(connection: Connection) -> dict[str, Any]:
    """Recolecta evidencia de catálogo, integridad, tamaño y planes sin mutar datos."""
    revision = None
    try:
        with connection.begin_nested():
            present = connection.execute(
                text("SELECT to_regclass('public.alembic_version')")
            ).scalar()
            if present is not None:
                revision = connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar()
    except Exception:  # El auditor informa permisos o instalaciones legadas; no los elude.
        revision = "unavailable"

    return {
        "alembic_revision": revision,
        "server": _mapping(
            connection,
            "SELECT current_setting('server_version') AS version, "
            "current_user AS role, "
            "COALESCE((SELECT ssl FROM pg_stat_ssl "
            "WHERE pid = pg_backend_pid()), FALSE) AS tls",
        ),
        "schemas": _rows(
            connection,
            "SELECT nspname AS schema_name, pg_get_userbyid(nspowner) AS owner, "
            "obj_description(oid, 'pg_namespace') AS comment "
            "FROM pg_namespace WHERE nspname LIKE 'vaaet_%' ORDER BY nspname",
        ),
        "relations": _rows(
            connection,
            "SELECT schemaname AS schema_name, relname AS relation_name, "
            "n_live_tup AS estimated_rows, n_dead_tup AS dead_rows, "
            "last_autovacuum, last_autoanalyze "
            "FROM pg_stat_user_tables WHERE schemaname LIKE 'vaaet_%' "
            "ORDER BY schemaname, relname",
        ),
        "sizes": _rows(
            connection,
            "SELECT n.nspname AS schema_name, c.relname AS relation_name, "
            "pg_total_relation_size(c.oid) AS total_bytes, "
            "pg_indexes_size(c.oid) AS index_bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname LIKE 'vaaet_%' AND c.relkind = 'r' "
            "ORDER BY pg_total_relation_size(c.oid) DESC",
        ),
        "unvalidated_constraints": _rows(
            connection,
            "SELECT n.nspname AS schema_name, c.relname AS relation_name, "
            "con.conname AS constraint_name, pg_get_constraintdef(con.oid) AS definition "
            "FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname LIKE 'vaaet_%' AND NOT con.convalidated "
            "ORDER BY n.nspname, c.relname, con.conname",
        ),
        "undocumented_columns": _rows(
            connection,
            "SELECT n.nspname AS schema_name, c.relname AS relation_name, a.attname AS column_name "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum "
            "WHERE n.nspname LIKE 'vaaet_%' AND c.relkind = 'r' "
            "AND a.attnum > 0 AND NOT a.attisdropped AND d.description IS NULL "
            "ORDER BY n.nspname, c.relname, a.attnum",
        ),
        "indexes": _rows(
            connection,
            "SELECT schemaname AS schema_name, tablename AS relation_name, "
            "indexname AS index_name, indexdef AS definition "
            "FROM pg_indexes WHERE schemaname LIKE 'vaaet_%' "
            "ORDER BY schemaname, tablename, indexname",
        ),
        "grants": _rows(
            connection,
            "SELECT grantee, table_schema, table_name, privilege_type "
            "FROM information_schema.role_table_grants "
            "WHERE table_schema LIKE 'vaaet_%' ORDER BY grantee, table_schema, table_name",
        ),
        "default_privileges": _rows(
            connection,
            "SELECT pg_get_userbyid(d.defaclrole) AS owner, n.nspname AS schema_name, "
            "d.defaclobjtype AS object_type, d.defaclacl::text AS privileges "
            "FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace "
            "WHERE n.nspname LIKE 'vaaet_%' ORDER BY owner, schema_name, object_type",
        ),
        "numeric_representations": _rows(
            connection,
            "SELECT 'vaaet_raw.traffic_data' AS relation_name, "
            "numeric_representation, count(*) AS rows "
            "FROM vaaet_raw.traffic_data GROUP BY numeric_representation UNION ALL "
            "SELECT 'vaaet_ml.telemetry_features', numeric_representation, count(*) "
            "FROM vaaet_ml.telemetry_features GROUP BY numeric_representation UNION ALL "
            "SELECT 'vaaet_ml.traffic_predictions', numeric_representation, count(*) "
            "FROM vaaet_ml.traffic_predictions GROUP BY numeric_representation "
            "ORDER BY relation_name, numeric_representation",
        ),
        "incomplete_pipeline_runs": _rows(
            connection,
            "SELECT id, workflow, application_name, application_version, started_at "
            "FROM vaaet_ops.pipeline_runs WHERE status = 'running' "
            "ORDER BY started_at, id",
        ),
        "human_validation_conflicts": _rows(
            connection,
            "SELECT prediction_id, root_count, terminal_count, "
            "cross_prediction_edges, branch_points, unreachable_nodes "
            "FROM vaaet_feedback.human_validation_conflicts "
            "ORDER BY prediction_id",
        ),
        "integrity": _mapping(
            connection,
            "SELECT "
            "(SELECT count(*) FROM vaaet_raw.traffic_data "
            " WHERE total_vehicles <> count_car + count_truck + count_bus + "
            " count_motorcycle + count_bicycle) AS invalid_raw_totals, "
            "(SELECT count(*) FROM vaaet_ml.traffic_predictions "
            " WHERE state_label <> CASE traffic_state WHEN 0 THEN 'Normal' "
            " WHEN 1 THEN 'Reduced' WHEN 2 THEN 'Congested' END) "
            "AS invalid_prediction_labels, "
            "(SELECT count(*) FROM vaaet_ml.traffic_predictions "
            " WHERE traffic_state = 3) AS automatic_accident_states, "
            "(SELECT count(*) FROM vaaet_raw.traffic_data "
            " WHERE btrim(continuity_id) = '') AS invalid_raw_continuity, "
            "(SELECT count(*) FROM vaaet_ml.telemetry_features "
            " WHERE btrim(continuity_id) = '') AS invalid_feature_continuity, "
            "(SELECT count(*) FROM vaaet_ml.traffic_predictions "
            " WHERE model_revision !~ '^[0-9a-f]{64}$') "
            "AS invalid_model_revisions, "
            "(SELECT count(*) FROM vaaet_feedback.human_validation_conflicts) "
            "AS conflicting_validation_chains",
        ),
        "query_plans": {
            "raw_training_scan": _scalar(
                connection,
                "EXPLAIN (FORMAT JSON) SELECT id, clip_id, record_time, avg_speed "
                "FROM vaaet_raw.traffic_data ORDER BY clip_id, record_time",
            ),
            "review_queue_by_run": _scalar(
                connection,
                "EXPLAIN (FORMAT JSON) SELECT prediction_id, record_time "
                "FROM vaaet_feedback.review_queue "
                "WHERE pipeline_run_id = "
                "CAST('00000000-0000-0000-0000-000000000000' AS UUID) "
                "ORDER BY record_time",
            ),
            "prediction_by_exact_revision": _scalar(
                connection,
                "EXPLAIN (FORMAT JSON) SELECT id, telemetry_feature_id, traffic_state "
                "FROM vaaet_ml.traffic_predictions "
                "WHERE model_revision = repeat('0', 64)",
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    settings = load_database_settings(
        DatabaseProfile.TRAINING,
        application_name="vaaet-postgres-audit",
        application_version=__version__,
    )
    with database_engine(settings) as engine, engine.connect() as connection:
        report = audit_database(connection)
    rendered = json.dumps(report, indent=2, default=str, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Audit written to {args.output}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
