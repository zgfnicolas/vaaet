# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Add temporal continuity and immutable model revisions.

Revision ID: 20260905_0003
Revises: 20260806_0002
Create Date: 2026-09-05
"""

from alembic import op

revision = "20260905_0003"
down_revision = "20260806_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for view in (
        "public.traffic_classifications",
        "public.telemetry_raw",
        "public.traffic_data",
        "vaaet_feedback.review_queue",
        "vaaet_feedback.effective_human_labels",
    ):
        op.execute(f"DROP VIEW IF EXISTS {view}")

    op.execute("ALTER TABLE vaaet_raw.traffic_data ADD COLUMN continuity_id TEXT")
    op.execute("ALTER TABLE vaaet_ml.telemetry_features ADD COLUMN continuity_id TEXT")
    op.execute("ALTER TABLE vaaet_ml.traffic_predictions ADD COLUMN model_revision TEXT")
    op.execute("ALTER TABLE vaaet_ops.pipeline_runs ADD COLUMN model_revision TEXT")
    op.execute(
        "ALTER TABLE vaaet_raw.traffic_data ALTER COLUMN telemetry_schema_version "
        "SET DEFAULT 'traffic-telemetry-v3'"
    )
    op.execute(
        "ALTER TABLE vaaet_ml.telemetry_features ALTER COLUMN feature_schema_version "
        "SET DEFAULT 'traffic-features-v3'"
    )

    for table in ("vaaet_raw.traffic_data", "vaaet_ml.telemetry_features"):
        op.execute(
            f"""
            WITH ordered AS (
              SELECT id, clip_id, record_time,
                     CASE WHEN lag(record_time) OVER (
                       PARTITION BY clip_id ORDER BY record_time, id
                     ) IS NULL OR record_time - lag(record_time) OVER (
                       PARTITION BY clip_id ORDER BY record_time, id
                     ) > interval '90 seconds' THEN 1 ELSE 0 END AS starts
              FROM {table}
            ), segmented AS (
              SELECT id, clip_id,
                     sum(starts) OVER (PARTITION BY clip_id ORDER BY record_time, id) AS segment
              FROM ordered
            )
            UPDATE {table} target
            SET continuity_id = segmented.clip_id || ':legacy-' ||
                lpad(segmented.segment::text, 4, '0')
            FROM segmented WHERE target.id = segmented.id
            """
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN continuity_id SET NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table.replace('.', '_')}_continuity "
            "CHECK (btrim(continuity_id) <> '')"
        )

    op.execute(
        "UPDATE vaaet_ml.traffic_predictions SET model_revision = "
        "repeat(md5(coalesce(model_version, 'legacy')), 2)"
    )
    op.execute(
        "UPDATE vaaet_ops.pipeline_runs SET model_revision = "
        "repeat(md5(model_version), 2) WHERE model_version IS NOT NULL"
    )
    op.execute("ALTER TABLE vaaet_ml.traffic_predictions ALTER COLUMN model_revision SET NOT NULL")
    op.execute(
        "ALTER TABLE vaaet_ml.traffic_predictions ADD CONSTRAINT ck_prediction_model_revision "
        "CHECK (model_revision ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        "ALTER TABLE vaaet_ops.pipeline_runs ADD CONSTRAINT ck_pipeline_model_revision "
        "CHECK (model_revision IS NULL OR model_revision ~ '^[0-9a-f]{64}$')"
    )

    _replace_unique_constraint(
        "vaaet_ml.telemetry_features",
        "UNIQUE (clip_id, record_time, feature_schema_version)",
    )
    _replace_unique_constraint(
        "vaaet_ml.traffic_predictions",
        "UNIQUE (telemetry_feature_id, model_version)",
    )
    op.execute(
        "ALTER TABLE vaaet_ml.telemetry_features ADD CONSTRAINT uq_features_run_contract "
        "UNIQUE (pipeline_run_id, clip_id, record_time, feature_schema_version)"
    )
    op.execute(
        "ALTER TABLE vaaet_ml.traffic_predictions ADD CONSTRAINT uq_predictions_revision "
        "UNIQUE (telemetry_feature_id, model_revision)"
    )
    op.execute(
        "CREATE INDEX idx_predictions_model_revision "
        "ON vaaet_ml.traffic_predictions (model_revision)"
    )
    _execute_for_existing_role(
        "vaaet_inference_role",
        "REVOKE UPDATE, DELETE ON vaaet_ml.telemetry_features, "
        "vaaet_ml.traffic_predictions FROM vaaet_inference_role",
    )

    op.execute(
        "DROP FUNCTION IF EXISTS vaaet_ops.start_pipeline_run("
        "UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT)"
    )
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.start_pipeline_run(
          p_id UUID, p_workflow TEXT, p_application_version TEXT,
          p_git_commit TEXT DEFAULT NULL, p_telemetry_schema_version TEXT DEFAULT NULL,
          p_feature_schema_version TEXT DEFAULT NULL, p_model_version TEXT DEFAULT NULL,
          p_model_revision TEXT DEFAULT NULL, p_source_kind TEXT DEFAULT NULL,
          p_clip_id TEXT DEFAULT NULL, p_input_rows BIGINT DEFAULT NULL
        ) RETURNS UUID
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE allowed BOOLEAN;
        BEGIN
          IF concat_ws(' ', p_application_version, p_git_commit,
               p_telemetry_schema_version, p_feature_schema_version,
               p_model_version, p_model_revision, p_source_kind, p_clip_id)
               ~* '(password=|://)'
          THEN
            RAISE EXCEPTION 'Pipeline metadata contains forbidden connection material'
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
          INSERT INTO vaaet_ops.pipeline_runs (
            id, workflow, application_version, git_commit,
            telemetry_schema_version, feature_schema_version, model_version,
            model_revision, source_kind, clip_id, input_rows, database_user
          ) VALUES (
            p_id, p_workflow, p_application_version, p_git_commit,
            p_telemetry_schema_version, p_feature_schema_version, p_model_version,
            p_model_revision, p_source_kind, p_clip_id, p_input_rows, SESSION_USER
          );
          RETURN p_id;
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_ops.start_pipeline_run("
        "UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT) FROM PUBLIC"
    )
    for role in (
        "vaaet_collection_role",
        "vaaet_inference_role",
        "vaaet_training_role",
        "vaaet_reviewer_role",
    ):
        _execute_for_existing_role(
            role,
            "GRANT EXECUTE ON FUNCTION vaaet_ops.start_pipeline_run("
            "UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT) "
            f"TO {role}",
        )

    op.execute(
        "DROP FUNCTION IF EXISTS vaaet_ops.finish_pipeline_run(UUID, TEXT, BIGINT, TEXT)"
    )
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.finish_pipeline_run(
          p_id UUID, p_status TEXT, p_output_rows BIGINT DEFAULT NULL,
          p_error_category TEXT DEFAULT NULL, p_model_revision TEXT DEFAULT NULL
        ) RETURNS VOID
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        BEGIN
          IF p_status NOT IN ('succeeded', 'failed') THEN
            RAISE EXCEPTION 'Final status must be succeeded or failed'
              USING ERRCODE = '22023';
          END IF;
          IF p_model_revision IS NOT NULL AND p_model_revision !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'model_revision must be SHA-256' USING ERRCODE = '22023';
          END IF;
          UPDATE vaaet_ops.pipeline_runs
          SET status = p_status, completed_at = CURRENT_TIMESTAMP,
              output_rows = p_output_rows,
              error_category = CASE WHEN p_status = 'failed' THEN p_error_category ELSE NULL END,
              model_revision = COALESCE(p_model_revision, model_revision)
          WHERE id = p_id AND database_user = SESSION_USER AND status = 'running';
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Pipeline run is missing, owned by another user, or already finished'
              USING ERRCODE = '42501';
          END IF;
        END
        $$
        """
    )
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
            "GRANT EXECUTE ON FUNCTION vaaet_ops.finish_pipeline_run("
            f"UUID, TEXT, BIGINT, TEXT, TEXT) TO {role}",
        )

    _create_views()
    _execute_for_existing_role(
        "vaaet_training_role",
        "GRANT SELECT ON vaaet_feedback.effective_human_labels TO vaaet_training_role",
    )
    _execute_for_existing_role(
        "vaaet_reviewer_role",
        "GRANT SELECT ON vaaet_feedback.review_queue TO vaaet_reviewer_role",
    )
    _execute_for_existing_role(
        "vaaet_collection_role",
        "GRANT SELECT ON public.traffic_data TO vaaet_collection_role",
    )
    _execute_for_existing_role(
        "vaaet_training_role",
        "GRANT SELECT ON public.traffic_data, public.telemetry_raw, "
        "public.traffic_classifications TO vaaet_training_role",
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
        "COMMENT ON COLUMN vaaet_raw.traffic_data.continuity_id IS 'Continuous camera/view interval; resets after a view change or gap over 90 seconds'",
        "COMMENT ON COLUMN vaaet_ml.telemetry_features.continuity_id IS 'Continuity boundary used by feature engineering, state hysteresis and incident policy'",
        "COMMENT ON COLUMN vaaet_ml.traffic_predictions.model_revision IS 'SHA-256 identity of exact model, scaler, mapping, policy and training input lock'",
        "COMMENT ON COLUMN vaaet_ops.pipeline_runs.model_revision IS 'Optional exact bundle revision used by this workflow run'",
    ):
        op.execute(statement)


def _replace_unique_constraint(table: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$ DECLARE item RECORD;
        BEGIN
          FOR item IN SELECT conname FROM pg_constraint
            WHERE conrelid = '{table}'::regclass AND contype = 'u'
              AND pg_get_constraintdef(oid) = '{definition}'
          LOOP
            EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', item.conname);
          END LOOP;
        END $$
        """
    )


def _execute_for_existing_role(role: str, statement: str) -> None:
    """Aplica grants de actualización sin exigir roles en una base nueva."""

    escaped = statement.replace("'", "''")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            EXECUTE '{escaped}';
          END IF;
        END $$
        """
    )


def _create_views() -> None:
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
               p.id AS prediction_id, p.model_version, p.model_revision,
               v.validated_state AS traffic_state, TRUE AS is_human_validated,
               v.reviewer_id, v.reviewed_at, v.notes
        FROM vaaet_ml.telemetry_features f
        JOIN vaaet_ml.traffic_predictions p ON p.telemetry_feature_id = f.id
        JOIN LATERAL (
          SELECT hv.validated_state, hv.reviewer_id, hv.reviewed_at, hv.notes, hv.id
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id
          ORDER BY hv.reviewed_at DESC, hv.id DESC LIMIT 1
        ) v ON TRUE
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
               p.accident_evidence_score, v.id AS latest_validation_id,
               v.validated_state AS current_validated_state,
               v.reviewer_id AS current_reviewer_id,
               v.reviewed_at AS current_reviewed_at
        FROM vaaet_ml.traffic_predictions p
        JOIN vaaet_ml.telemetry_features f ON f.id = p.telemetry_feature_id
        LEFT JOIN LATERAL (
          SELECT hv.id, hv.validated_state, hv.reviewer_id, hv.reviewed_at
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id
          ORDER BY hv.reviewed_at DESC, hv.id DESC LIMIT 1
        ) v ON TRUE
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
               COALESCE(v.validated_state, p.traffic_state) AS traffic_state,
               CASE COALESCE(v.validated_state, p.traffic_state)
                 WHEN 0 THEN 'Normal' WHEN 1 THEN 'Reduced'
                 WHEN 2 THEN 'Congested' ELSE 'Accident' END AS state_label,
               p.confidence, p.model_version, p.model_revision,
               p.model_traffic_state, p.model_state_label, p.model_confidence,
               p.probability_margin, p.decision_abstained,
               p.measurement_reliable, p.accident_rule_triggered,
               p.accident_alert_started, p.accident_evidence_score,
               (v.id IS NOT NULL) AS is_human_validated,
               v.validated_state AS human_override_state,
               v.reviewed_at AS validated_at
        FROM vaaet_ml.traffic_predictions p
        LEFT JOIN LATERAL (
          SELECT hv.id, hv.validated_state, hv.reviewed_at
          FROM vaaet_feedback.human_validations hv
          WHERE hv.prediction_id = p.id
          ORDER BY hv.reviewed_at DESC, hv.id DESC LIMIT 1
        ) v ON TRUE
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Temporal continuity and immutable model revisions are intentionally irreversible. "
        "Restore a pre-4.6 backup if rollback is required."
    )
