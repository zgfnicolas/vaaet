# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Preserve float64 fidelity and make operational HITL lineage consistent.

Revision ID: 20260909_0004
Revises: 20260905_0003
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0004"
down_revision = "20260905_0003"
branch_labels = None
depends_on = None


_CONTINUOUS_COLUMNS = {
    "vaaet_raw.traffic_data": (
        "avg_speed",
        "speed_measurement_quality",
        "optical_flow_tracking_ratio",
    ),
    "vaaet_ml.telemetry_features": (
        "avg_speed",
        "heavy_vehicle_ratio",
        "delta_speed",
        "speed_variance",
        "cumulative_delta_speed",
        "low_speed_persistence",
        "speed_measurement_quality",
        "optical_flow_tracking_ratio",
        "near_zero_motion_ratio",
        "stationary_confirmed_ratio",
    ),
    "vaaet_ml.traffic_predictions": (
        "confidence",
        "model_confidence",
        "probability_margin",
        "accident_evidence_score",
    ),
}
_TABLE_CONSTRAINT_PREFIX = {
    "vaaet_raw.traffic_data": "raw",
    "vaaet_ml.telemetry_features": "features",
    "vaaet_ml.traffic_predictions": "predictions",
}


def upgrade() -> None:
    _drop_views()
    op.execute("ALTER TABLE vaaet_ops.pipeline_runs ADD COLUMN application_name TEXT")
    op.execute(
        "UPDATE vaaet_ops.pipeline_runs SET application_name = 'legacy-unknown' "
        "WHERE application_name IS NULL"
    )
    op.execute("ALTER TABLE vaaet_ops.pipeline_runs ALTER COLUMN application_name SET NOT NULL")
    op.execute(
        "ALTER TABLE vaaet_ops.pipeline_runs ADD CONSTRAINT ck_pipeline_application_name "
        "CHECK (btrim(application_name) <> '' AND application_name !~* '(password=|://)')"
    )
    op.execute(
        "ALTER TABLE vaaet_raw.traffic_data "
        "ALTER COLUMN telemetry_schema_version DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE vaaet_ml.telemetry_features "
        "ALTER COLUMN feature_schema_version DROP DEFAULT"
    )

    for table in _CONTINUOUS_COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN numeric_representation TEXT")
        op.execute(
            f"UPDATE {table} SET numeric_representation = 'legacy-rounded' "
            "WHERE numeric_representation IS NULL"
        )
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN numeric_representation "
            "SET DEFAULT 'float64'"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN numeric_representation SET NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT "
            f"ck_{_TABLE_CONSTRAINT_PREFIX[table]}_numeric_representation "
            "CHECK (numeric_representation IN ('legacy-rounded', 'float64'))"
        )

    for table, columns in _CONTINUOUS_COLUMNS.items():
        for column in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE DOUBLE PRECISION USING {column}::DOUBLE PRECISION"
            )
            constraint = f"ck_{_TABLE_CONSTRAINT_PREFIX[table]}_{column}_finite"
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ("
                f"{column} IS NULL OR {column} NOT IN ("
                "'NaN'::DOUBLE PRECISION, 'Infinity'::DOUBLE PRECISION, "
                "'-Infinity'::DOUBLE PRECISION)) NOT VALID"
            )

    _replace_pipeline_functions()
    _replace_validation_guard()
    _create_views()
    _apply_grants_and_comments()


def _drop_views() -> None:
    for view in (
        "public.traffic_classifications",
        "public.telemetry_raw",
        "public.traffic_data",
        "vaaet_feedback.review_queue",
        "vaaet_feedback.effective_human_labels",
        "vaaet_feedback.human_validation_conflicts",
    ):
        op.execute(f"DROP VIEW IF EXISTS {view}")


def _replace_pipeline_functions() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS vaaet_ops.start_pipeline_run("
        "UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT)"
    )
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.start_pipeline_run(
          p_id UUID, p_workflow TEXT, p_application_name TEXT,
          p_application_version TEXT, p_git_commit TEXT DEFAULT NULL,
          p_telemetry_schema_version TEXT DEFAULT NULL,
          p_feature_schema_version TEXT DEFAULT NULL, p_model_version TEXT DEFAULT NULL,
          p_model_revision TEXT DEFAULT NULL, p_source_kind TEXT DEFAULT NULL,
          p_clip_id TEXT DEFAULT NULL, p_input_rows BIGINT DEFAULT NULL
        ) RETURNS UUID
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE allowed BOOLEAN; existing vaaet_ops.pipeline_runs%ROWTYPE;
        BEGIN
          IF p_application_name IS NULL OR p_application_version IS NULL OR
             btrim(p_application_name) = '' OR btrim(p_application_version) = '' OR
             concat_ws(' ', p_application_name, p_application_version, p_git_commit,
               p_telemetry_schema_version, p_feature_schema_version, p_model_version,
               p_model_revision, p_source_kind, p_clip_id) ~* '(password=|://)'
          THEN
            RAISE EXCEPTION 'Pipeline metadata is invalid or contains forbidden material'
              USING ERRCODE = '22023';
          END IF;
          IF p_model_revision IS NOT NULL AND p_model_revision !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'model_revision must be SHA-256' USING ERRCODE = '22023';
          END IF;
          allowed := CASE p_workflow
            WHEN 'collection' THEN pg_has_role(SESSION_USER, 'vaaet_collection_role', 'member')
            WHEN 'inference' THEN pg_has_role(SESSION_USER, 'vaaet_inference_role', 'member')
            WHEN 'training' THEN pg_has_role(SESSION_USER, 'vaaet_training_role', 'member')
            WHEN 'review' THEN pg_has_role(SESSION_USER, 'vaaet_reviewer_role', 'member')
            ELSE FALSE END;
          IF NOT allowed THEN
            RAISE EXCEPTION 'Role is not authorized for workflow %', p_workflow
              USING ERRCODE = '42501';
          END IF;

          PERFORM pg_advisory_xact_lock(hashtextextended(p_id::text, 0));

          SELECT * INTO existing FROM vaaet_ops.pipeline_runs WHERE id = p_id;
          IF FOUND THEN
            IF existing.database_user = SESSION_USER AND existing.workflow = p_workflow AND
               existing.application_name = p_application_name AND
               existing.application_version = p_application_version AND
               existing.git_commit IS NOT DISTINCT FROM p_git_commit AND
               existing.telemetry_schema_version IS NOT DISTINCT FROM p_telemetry_schema_version AND
               existing.feature_schema_version IS NOT DISTINCT FROM p_feature_schema_version AND
               existing.model_version IS NOT DISTINCT FROM p_model_version AND
               existing.model_revision IS NOT DISTINCT FROM p_model_revision AND
               existing.source_kind IS NOT DISTINCT FROM p_source_kind AND
               existing.clip_id IS NOT DISTINCT FROM p_clip_id AND
               existing.input_rows IS NOT DISTINCT FROM p_input_rows
            THEN RETURN p_id;
            END IF;
            RAISE EXCEPTION 'Immutable pipeline run identity conflict'
              USING ERRCODE = '23505';
          END IF;

          INSERT INTO vaaet_ops.pipeline_runs (
            id, workflow, application_name, application_version, git_commit,
            telemetry_schema_version, feature_schema_version, model_version,
            model_revision, source_kind, clip_id, input_rows, database_user
          ) VALUES (
            p_id, p_workflow, p_application_name, p_application_version, p_git_commit,
            p_telemetry_schema_version, p_feature_schema_version, p_model_version,
            p_model_revision, p_source_kind, p_clip_id, p_input_rows, SESSION_USER
          );
          RETURN p_id;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION vaaet_ops.finish_pipeline_run("
        "p_id UUID, p_status TEXT, p_output_rows BIGINT DEFAULT NULL, "
        "p_error_category TEXT DEFAULT NULL, p_model_revision TEXT DEFAULT NULL) RETURNS VOID "
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, vaaet_ops AS $$ "
        "DECLARE existing vaaet_ops.pipeline_runs%ROWTYPE; expected_error TEXT; "
        "BEGIN "
        "IF p_status NOT IN ('succeeded','failed') THEN RAISE EXCEPTION "
        "'Final status must be succeeded or failed' USING ERRCODE='22023'; END IF; "
        "IF p_model_revision IS NOT NULL AND p_model_revision !~ '^[0-9a-f]{64}$' THEN "
        "RAISE EXCEPTION 'model_revision must be SHA-256' USING ERRCODE='22023'; END IF; "
        "SELECT * INTO existing FROM vaaet_ops.pipeline_runs WHERE id=p_id FOR UPDATE; "
        "IF NOT FOUND OR existing.database_user <> SESSION_USER THEN RAISE EXCEPTION "
        "'Pipeline run is missing or owned by another user' USING ERRCODE='42501'; END IF; "
        "expected_error := CASE WHEN p_status='failed' THEN p_error_category ELSE NULL END; "
        "IF existing.status <> 'running' THEN "
        "IF existing.status=p_status AND existing.output_rows IS NOT DISTINCT FROM p_output_rows "
        "AND existing.error_category IS NOT DISTINCT FROM expected_error "
        "AND existing.model_revision IS NOT DISTINCT FROM COALESCE(p_model_revision, existing.model_revision) "
        "THEN RETURN; END IF; RAISE EXCEPTION 'Immutable terminal pipeline run conflict' "
        "USING ERRCODE='23505'; END IF; "
        "UPDATE vaaet_ops.pipeline_runs SET status=p_status, completed_at=CURRENT_TIMESTAMP, "
        "output_rows=p_output_rows, error_category=expected_error, "
        "model_revision=COALESCE(p_model_revision, model_revision) WHERE id=p_id; END $$"
    )


def _replace_validation_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vaaet_feedback.validate_superseded_validation()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, vaaet_feedback
        AS $$
        DECLARE prior_prediction_id BIGINT;
        BEGIN
          PERFORM pg_advisory_xact_lock(NEW.prediction_id);
          IF EXISTS (
            SELECT 1 FROM vaaet_feedback.human_validations WHERE id = NEW.id
          ) THEN
            RETURN NEW;
          END IF;
          IF NEW.supersedes_validation_id IS NULL THEN
            IF EXISTS (
              SELECT 1 FROM vaaet_feedback.human_validations
              WHERE prediction_id = NEW.prediction_id
            ) THEN
              RAISE EXCEPTION 'A prediction may have only one root validation'
                USING ERRCODE = '23505';
            END IF;
            RETURN NEW;
          END IF;
          SELECT prediction_id INTO prior_prediction_id
          FROM vaaet_feedback.human_validations
          WHERE id = NEW.supersedes_validation_id FOR KEY SHARE;
          IF prior_prediction_id IS NULL OR prior_prediction_id <> NEW.prediction_id THEN
            RAISE EXCEPTION 'A validation may supersede only the same prediction'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1 FROM vaaet_feedback.human_validations
            WHERE supersedes_validation_id = NEW.supersedes_validation_id
          ) THEN
            RAISE EXCEPTION 'A validation may have only one direct successor'
              USING ERRCODE = '23505';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )


def _create_views() -> None:
    op.execute(
        """
        CREATE VIEW vaaet_feedback.human_validation_conflicts AS
        WITH RECURSIVE reachable AS (
          SELECT root.id, root.prediction_id
          FROM vaaet_feedback.human_validations root
          WHERE root.supersedes_validation_id IS NULL
          UNION
          SELECT child.id, child.prediction_id
          FROM vaaet_feedback.human_validations child
          JOIN reachable parent
            ON child.supersedes_validation_id = parent.id
           AND child.prediction_id = parent.prediction_id
        )
        SELECT p.id AS prediction_id,
               count(DISTINCT hv.id) FILTER (WHERE hv.supersedes_validation_id IS NULL) AS root_count,
               count(DISTINCT hv.id) FILTER (WHERE child.id IS NULL) AS terminal_count,
               count(DISTINCT hv.id) FILTER (
                 WHERE parent.id IS NOT NULL AND parent.prediction_id <> hv.prediction_id
               ) AS cross_prediction_edges,
               count(DISTINCT hv.id) FILTER (WHERE successor.successor_count > 1) AS branch_points,
               count(DISTINCT hv.id) FILTER (WHERE reachable.id IS NULL) AS unreachable_nodes
        FROM vaaet_ml.traffic_predictions p
        JOIN vaaet_feedback.human_validations hv ON hv.prediction_id = p.id
        LEFT JOIN vaaet_feedback.human_validations child
          ON child.supersedes_validation_id = hv.id
        LEFT JOIN vaaet_feedback.human_validations parent
          ON parent.id = hv.supersedes_validation_id
        LEFT JOIN reachable ON reachable.id = hv.id
        LEFT JOIN LATERAL (
          SELECT count(*) AS successor_count
          FROM vaaet_feedback.human_validations candidate
          WHERE candidate.supersedes_validation_id = hv.id
        ) successor ON TRUE
        GROUP BY p.id
        HAVING count(DISTINCT hv.id) FILTER (WHERE hv.supersedes_validation_id IS NULL) <> 1
            OR count(DISTINCT hv.id) FILTER (WHERE child.id IS NULL) <> 1
            OR count(DISTINCT hv.id) FILTER (
                 WHERE parent.id IS NOT NULL AND parent.prediction_id <> hv.prediction_id
               ) > 0
            OR count(DISTINCT hv.id) FILTER (WHERE successor.successor_count > 1) > 0
            OR count(DISTINCT hv.id) FILTER (WHERE reachable.id IS NULL) > 0
        """
    )
    op.execute(
        """
        CREATE VIEW vaaet_feedback.effective_human_labels AS
        SELECT f.id, f.source_record_id, f.pipeline_run_id, f.clip_id,
               f.continuity_id, f.record_time, f.feature_schema_version,
               f.avg_speed, f.total_vehicles, f.count_car, f.count_truck,
               f.count_bus, f.count_motorcycle, f.count_bicycle,
               f.heavy_vehicle_ratio, f.delta_speed, f.delta_count,
               f.transition_flag, f.speed_variance, f.cumulative_delta_speed,
               f.low_speed_persistence, f.speed_measurement_quality,
               f.optical_flow_tracking_ratio, f.near_zero_motion_ratio,
               f.stationary_confirmed_ratio, f.near_zero_motion_count,
               f.stationary_confirmed_count, f.rejected_speed_count,
               f.recovered_track_count, f.speed_sample_count,
               f.telemetry_schema_version, f.data_origin, f.synthetic_scenario,
               f.hour_of_day, f.weather_condition, f.created_at,
               f.numeric_representation AS feature_numeric_representation,
               p.id AS prediction_id, p.model_version, p.model_revision,
               p.numeric_representation AS prediction_numeric_representation,
               terminal.validated_state AS traffic_state,
               TRUE AS is_human_validated, terminal.reviewer_id,
               terminal.reviewed_at, terminal.notes
        FROM vaaet_ml.telemetry_features f
        JOIN vaaet_ml.traffic_predictions p ON p.telemetry_feature_id = f.id
        JOIN LATERAL (
          SELECT hv.validated_state, hv.reviewer_id, hv.reviewed_at, hv.notes
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id AND NOT EXISTS (
            SELECT 1 FROM vaaet_feedback.human_validations child
            WHERE child.supersedes_validation_id = hv.id
          )
        ) terminal ON TRUE
        WHERE NOT EXISTS (
          SELECT 1 FROM vaaet_feedback.human_validation_conflicts conflict
          WHERE conflict.prediction_id = p.id
        )
        """
    )
    op.execute(
        """
        CREATE VIEW vaaet_feedback.review_queue AS
        SELECT p.id AS prediction_id, p.pipeline_run_id, f.clip_id,
               f.continuity_id, f.record_time, p.traffic_state, p.state_label,
               p.confidence, p.model_version, p.model_revision,
               p.probability_margin, p.decision_abstained, p.measurement_reliable,
               p.accident_rule_triggered, p.accident_alert_started,
               p.accident_evidence_score, terminal.id AS latest_validation_id,
               terminal.validated_state AS current_validated_state,
               terminal.reviewer_id AS current_reviewer_id,
               terminal.reviewed_at AS current_reviewed_at,
               (conflict.prediction_id IS NOT NULL) AS validation_conflict
        FROM vaaet_ml.traffic_predictions p
        JOIN vaaet_ml.telemetry_features f ON f.id = p.telemetry_feature_id
        LEFT JOIN vaaet_feedback.human_validation_conflicts conflict
          ON conflict.prediction_id = p.id
        LEFT JOIN LATERAL (
          SELECT hv.id, hv.validated_state, hv.reviewer_id, hv.reviewed_at
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id AND conflict.prediction_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM vaaet_feedback.human_validations child
            WHERE child.supersedes_validation_id = hv.id
          )
        ) terminal ON TRUE
        """
    )
    op.execute(
        """
        CREATE VIEW public.traffic_data AS
        SELECT id, pipeline_run_id, clip_id, continuity_id, record_time,
               avg_speed, count_car, count_truck, count_bus, count_motorcycle,
               count_bicycle, total_vehicles, near_zero_motion_count,
               stationary_confirmed_count, rejected_speed_count,
               recovered_track_count, speed_sample_count,
               speed_measurement_quality, optical_flow_tracking_ratio,
               telemetry_schema_version, created_at
        FROM vaaet_raw.traffic_data
        """
    )
    op.execute(
        """
        CREATE VIEW public.telemetry_raw AS
        SELECT id, source_record_id, pipeline_run_id, clip_id, continuity_id,
               record_time, feature_schema_version, avg_speed, total_vehicles,
               count_car, count_truck, count_bus, count_motorcycle, count_bicycle,
               heavy_vehicle_ratio, delta_speed, delta_count, transition_flag,
               speed_variance, cumulative_delta_speed, low_speed_persistence,
               speed_measurement_quality, optical_flow_tracking_ratio,
               near_zero_motion_ratio, stationary_confirmed_ratio,
               near_zero_motion_count, stationary_confirmed_count,
               rejected_speed_count, recovered_track_count, speed_sample_count,
               telemetry_schema_version, data_origin, synthetic_scenario,
               hour_of_day, weather_condition, created_at
        FROM vaaet_ml.telemetry_features
        """
    )
    op.execute(
        """
        CREATE VIEW public.traffic_classifications AS
        SELECT p.id, p.telemetry_feature_id AS telemetry_id, p.classified_at,
               COALESCE(terminal.validated_state, p.traffic_state) AS traffic_state,
               CASE COALESCE(terminal.validated_state, p.traffic_state)
                 WHEN 0 THEN 'Normal' WHEN 1 THEN 'Reduced'
                 WHEN 2 THEN 'Congested' ELSE 'Accident' END AS state_label,
               p.confidence, p.model_version, p.model_revision,
               p.model_traffic_state, p.model_state_label, p.model_confidence,
               p.probability_margin, p.decision_abstained,
               p.measurement_reliable, p.accident_rule_triggered,
               p.accident_alert_started, p.accident_evidence_score,
               (terminal.id IS NOT NULL) AS is_human_validated,
               terminal.validated_state AS human_override_state,
               terminal.reviewed_at AS validated_at
        FROM vaaet_ml.traffic_predictions p
        LEFT JOIN vaaet_feedback.human_validation_conflicts conflict
          ON conflict.prediction_id = p.id
        LEFT JOIN LATERAL (
          SELECT hv.id, hv.validated_state, hv.reviewed_at
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id AND conflict.prediction_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM vaaet_feedback.human_validations child
            WHERE child.supersedes_validation_id = hv.id
          )
        ) terminal ON TRUE
        """
    )


def _apply_grants_and_comments() -> None:
    start_signature = (
        "vaaet_ops.start_pipeline_run(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, "
        "TEXT, TEXT, TEXT, TEXT, BIGINT)"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {start_signature} FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_ops.finish_pipeline_run("
        "UUID, TEXT, BIGINT, TEXT, TEXT) FROM PUBLIC"
    )
    for role in (
        "vaaet_collection_role",
        "vaaet_inference_role",
        "vaaet_training_role",
        "vaaet_reviewer_role",
    ):
        _execute_for_existing_role(
            role,
            f"GRANT SELECT ON public.alembic_version TO {role}",
        )
        _execute_for_existing_role(role, f"GRANT EXECUTE ON FUNCTION {start_signature} TO {role}")
        _execute_for_existing_role(
            role,
            "GRANT EXECUTE ON FUNCTION vaaet_ops.finish_pipeline_run("
            f"UUID, TEXT, BIGINT, TEXT, TEXT) TO {role}",
        )
    _execute_for_existing_role(
        "vaaet_collection_role",
        "GRANT SELECT ON vaaet_raw.traffic_data TO vaaet_collection_role",
    )
    _execute_for_existing_role(
        "vaaet_training_role",
        "GRANT SELECT ON vaaet_feedback.effective_human_labels, "
        "vaaet_feedback.human_validation_conflicts TO vaaet_training_role",
    )
    _execute_for_existing_role(
        "vaaet_reviewer_role",
        "GRANT SELECT ON vaaet_feedback.review_queue, "
        "vaaet_feedback.human_validation_conflicts TO vaaet_reviewer_role",
    )
    _execute_for_existing_role(
        "vaaet_training_role",
        "GRANT SELECT ON public.traffic_data, public.telemetry_raw, "
        "public.traffic_classifications TO vaaet_training_role",
    )
    _execute_for_existing_role(
        "vaaet_collection_role",
        "GRANT SELECT ON public.traffic_data TO vaaet_collection_role",
    )
    _execute_for_existing_role(
        "vaaet_inference_role",
        "GRANT SELECT ON public.telemetry_raw TO vaaet_inference_role",
    )
    _execute_for_existing_role(
        "vaaet_reviewer_role",
        "GRANT SELECT ON public.traffic_classifications TO vaaet_reviewer_role",
    )
    for statement in (
        "COMMENT ON COLUMN vaaet_ops.pipeline_runs.application_name IS 'Explicit consumer identity; version is stored separately'",
        "COMMENT ON COLUMN vaaet_raw.traffic_data.numeric_representation IS 'float64 for new calculations; legacy-rounded for NUMERIC history'",
        "COMMENT ON COLUMN vaaet_ml.telemetry_features.numeric_representation IS 'Numeric provenance without reconstructing rounded historical values'",
        "COMMENT ON COLUMN vaaet_ml.traffic_predictions.numeric_representation IS 'Numeric provenance for probabilities and decision evidence'",
        "COMMENT ON VIEW vaaet_feedback.human_validation_conflicts IS 'Historical invalid HITL graphs excluded from effective supervision'",
    ):
        op.execute(statement)


def _execute_for_existing_role(role: str, statement: str) -> None:
    escaped = statement.replace("'", "''")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
        f"THEN EXECUTE '{escaped}'; END IF; END $$"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Float64 fidelity and immutable HITL lineage cannot be downgraded safely. "
        "Restore a pre-0004 backup or apply a governed forward correction."
    )
