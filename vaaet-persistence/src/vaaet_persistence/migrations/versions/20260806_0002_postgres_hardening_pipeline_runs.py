# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Harden PostgreSQL contracts and add auditable pipeline runs.

Revision ID: 20260806_0002
Revises: 20260804_0001
Create Date: 2026-08-06
"""

from alembic import op

revision = "20260806_0002"
down_revision = "20260804_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS vaaet_ops")
    op.execute(
        """
        CREATE TABLE vaaet_ops.pipeline_runs (
          id UUID PRIMARY KEY,
          workflow TEXT NOT NULL CHECK (
            workflow IN ('collection', 'inference', 'training', 'review')
          ),
          status TEXT NOT NULL DEFAULT 'running' CHECK (
            status IN ('running', 'succeeded', 'failed')
          ),
          started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          completed_at TIMESTAMPTZ,
          database_user TEXT NOT NULL DEFAULT SESSION_USER,
          application_version TEXT NOT NULL,
          git_commit TEXT,
          telemetry_schema_version TEXT,
          feature_schema_version TEXT,
          model_version TEXT,
          source_kind TEXT,
          clip_id TEXT,
          input_rows BIGINT CHECK (input_rows IS NULL OR input_rows >= 0),
          output_rows BIGINT CHECK (output_rows IS NULL OR output_rows >= 0),
          error_category TEXT,
          CHECK (completed_at IS NULL OR completed_at >= started_at),
          CHECK (
            (status = 'running' AND completed_at IS NULL) OR
            (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
          ),
          CHECK (status = 'failed' OR error_category IS NULL)
          ,CHECK (git_commit IS NULL OR git_commit ~ '^[0-9a-fA-F]{7,40}$')
          ,CHECK (source_kind IS NULL OR source_kind !~ '[\\/]' )
          ,CHECK (clip_id IS NULL OR clip_id !~ '[\\/]' )
          ,CHECK (
            error_category IS NULL OR
            error_category ~ '^[A-Za-z_][A-Za-z0-9_.]{0,127}$'
          )
        )
        """
    )

    # Preserve every historical correlation id before adding referential integrity.
    op.execute(
        """
        INSERT INTO vaaet_ops.pipeline_runs (
          id, workflow, status, started_at, completed_at, database_user,
          application_version, telemetry_schema_version, source_kind, output_rows
        )
        SELECT pipeline_run_id, 'collection', 'succeeded', MIN(created_at), MAX(created_at),
               'legacy-migration', '4.1.0', MAX(telemetry_schema_version),
               'legacy-database', COUNT(*)
        FROM vaaet_raw.traffic_data
        GROUP BY pipeline_run_id
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vaaet_ops.pipeline_runs (
          id, workflow, status, started_at, completed_at, database_user,
          application_version, telemetry_schema_version, feature_schema_version,
          source_kind, output_rows
        )
        SELECT pipeline_run_id, 'inference', 'succeeded', MIN(created_at), MAX(created_at),
               'legacy-migration', '4.1.0', MAX(telemetry_schema_version),
               MAX(feature_schema_version), 'legacy-database', COUNT(*)
        FROM vaaet_ml.telemetry_features
        GROUP BY pipeline_run_id
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO vaaet_ops.pipeline_runs (
          id, workflow, status, started_at, completed_at, database_user,
          application_version, model_version, source_kind, output_rows
        )
        SELECT pipeline_run_id, 'inference', 'succeeded', MIN(classified_at),
               MAX(classified_at), 'legacy-migration', '4.1.0', MAX(model_version),
               'legacy-database', COUNT(*)
        FROM vaaet_ml.traffic_predictions
        GROUP BY pipeline_run_id
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        "ALTER TABLE vaaet_feedback.human_validations "
        "ADD COLUMN pipeline_run_id UUID"
    )
    for table in (
        "vaaet_raw.traffic_data",
        "vaaet_ml.telemetry_features",
        "vaaet_ml.traffic_predictions",
        "vaaet_feedback.human_validations",
    ):
        constraint = "fk_" + table.replace(".", "_") + "_pipeline_run"
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            "FOREIGN KEY (pipeline_run_id) REFERENCES vaaet_ops.pipeline_runs(id) "
            "ON DELETE RESTRICT NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION vaaet_ops.start_pipeline_run(
          p_id UUID,
          p_workflow TEXT,
          p_application_version TEXT,
          p_git_commit TEXT DEFAULT NULL,
          p_telemetry_schema_version TEXT DEFAULT NULL,
          p_feature_schema_version TEXT DEFAULT NULL,
          p_model_version TEXT DEFAULT NULL,
          p_source_kind TEXT DEFAULT NULL,
          p_clip_id TEXT DEFAULT NULL,
          p_input_rows BIGINT DEFAULT NULL
        ) RETURNS UUID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE allowed BOOLEAN;
        BEGIN
          IF concat_ws(' ', p_application_version, p_git_commit,
               p_telemetry_schema_version, p_feature_schema_version,
               p_model_version, p_source_kind, p_clip_id) ~* '(password=|://)'
          THEN
            RAISE EXCEPTION 'Pipeline metadata contains forbidden connection material'
              USING ERRCODE = '22023';
          END IF;
          allowed := CASE p_workflow
            WHEN 'collection' THEN pg_has_role(SESSION_USER, 'vaaet_collection_role', 'member')
            WHEN 'inference' THEN pg_has_role(SESSION_USER, 'vaaet_inference_role', 'member')
            WHEN 'training' THEN pg_has_role(SESSION_USER, 'vaaet_training_role', 'member')
            WHEN 'review' THEN pg_has_role(SESSION_USER, 'vaaet_reviewer_role', 'member')
            ELSE FALSE
          END;
          IF NOT allowed THEN
            RAISE EXCEPTION 'Role is not authorized for workflow %', p_workflow
              USING ERRCODE = '42501';
          END IF;
          INSERT INTO vaaet_ops.pipeline_runs (
            id, workflow, application_version, git_commit,
            telemetry_schema_version, feature_schema_version, model_version,
            source_kind, clip_id, input_rows, database_user
          ) VALUES (
            p_id, p_workflow, p_application_version, p_git_commit,
            p_telemetry_schema_version, p_feature_schema_version, p_model_version,
            p_source_kind, p_clip_id, p_input_rows, SESSION_USER
          );
          RETURN p_id;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vaaet_ops.finish_pipeline_run(
          p_id UUID,
          p_status TEXT,
          p_output_rows BIGINT DEFAULT NULL,
          p_error_category TEXT DEFAULT NULL
        ) RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        BEGIN
          IF p_status NOT IN ('succeeded', 'failed') THEN
            RAISE EXCEPTION 'Final status must be succeeded or failed'
              USING ERRCODE = '22023';
          END IF;
          UPDATE vaaet_ops.pipeline_runs
          SET status = p_status,
              completed_at = CURRENT_TIMESTAMP,
              output_rows = p_output_rows,
              error_category = CASE WHEN p_status = 'failed' THEN p_error_category ELSE NULL END
          WHERE id = p_id AND database_user = SESSION_USER AND status = 'running';
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Pipeline run is missing, owned by another user, or already finished'
              USING ERRCODE = '42501';
          END IF;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION vaaet_ops.start_pipeline_run(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION vaaet_ops.finish_pipeline_run(UUID, TEXT, BIGINT, TEXT) FROM PUBLIC")

    # Enforce semantic integrity for all new writes without rejecting legacy rows.
    op.execute(
        "ALTER TABLE vaaet_raw.traffic_data ADD CONSTRAINT ck_raw_total_matches_types "
        "CHECK (total_vehicles = count_car + count_truck + count_bus + "
        "count_motorcycle + count_bicycle) NOT VALID"
    )
    op.execute(
        "ALTER TABLE vaaet_ml.traffic_predictions ADD CONSTRAINT ck_prediction_state_label "
        "CHECK ((traffic_state = 0 AND state_label = 'Normal') OR "
        "(traffic_state = 1 AND state_label = 'Reduced') OR "
        "(traffic_state = 2 AND state_label = 'Congested')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE vaaet_ml.traffic_predictions ADD CONSTRAINT ck_model_state_label "
        "CHECK ((model_traffic_state IS NULL AND model_state_label IS NULL) OR "
        "(model_traffic_state = 0 AND model_state_label = 'Normal') OR "
        "(model_traffic_state = 1 AND model_state_label = 'Reduced') OR "
        "(model_traffic_state = 2 AND model_state_label = 'Congested')) NOT VALID"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vaaet_feedback.validate_superseded_validation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path = pg_catalog, vaaet_feedback
        AS $$
        DECLARE prior_prediction_id BIGINT;
        BEGIN
          IF NEW.supersedes_validation_id IS NULL THEN RETURN NEW; END IF;
          SELECT prediction_id INTO prior_prediction_id
          FROM vaaet_feedback.human_validations
          WHERE id = NEW.supersedes_validation_id;
          IF prior_prediction_id IS NULL OR prior_prediction_id <> NEW.prediction_id THEN
            RAISE EXCEPTION 'A validation may supersede only a validation for the same prediction'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_validate_superseded_validation "
        "BEFORE INSERT ON vaaet_feedback.human_validations FOR EACH ROW "
        "EXECUTE FUNCTION vaaet_feedback.validate_superseded_validation()"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_human_validations_superseded "
        "ON vaaet_feedback.human_validations (supersedes_validation_id) "
        "WHERE supersedes_validation_id IS NOT NULL"
    )

    # Retain exactly one index for each natural key and query pattern.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'vaaet_raw.traffic_data'::regclass AND contype = 'u'
              AND pg_get_constraintdef(oid) = 'UNIQUE (clip_id, record_time)'
          ) THEN
            ALTER TABLE vaaet_raw.traffic_data
              ADD CONSTRAINT uq_raw_clip_time UNIQUE (clip_id, record_time);
          END IF;
        END $$
        """
    )
    op.execute("DROP INDEX IF EXISTS vaaet_raw.idx_raw_clip_time")
    op.execute("DROP INDEX IF EXISTS vaaet_ml.idx_features_clip_time")
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'vaaet_ml.telemetry_features'::regclass AND contype = 'u'
              AND pg_get_constraintdef(oid) =
                  'UNIQUE (clip_id, record_time, feature_schema_version)'
          ) THEN
            ALTER TABLE vaaet_ml.telemetry_features
              ADD CONSTRAINT uq_features_contract
              UNIQUE USING INDEX uq_features_clip_time_schema;
          ELSE
            DROP INDEX IF EXISTS vaaet_ml.uq_features_clip_time_schema;
          END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'vaaet_ml.traffic_predictions'::regclass AND contype = 'u'
              AND pg_get_constraintdef(oid) =
                  'UNIQUE (telemetry_feature_id, model_version)'
          ) THEN
            ALTER TABLE vaaet_ml.traffic_predictions
              ADD CONSTRAINT uq_predictions_contract
              UNIQUE USING INDEX uq_predictions_feature_model;
          ELSE
            DROP INDEX IF EXISTS vaaet_ml.uq_predictions_feature_model;
          END IF;
        END $$
        """
    )
    op.execute("DROP INDEX IF EXISTS vaaet_feedback.idx_validations_prediction_time")
    op.execute(
        "CREATE INDEX idx_validations_prediction_time_id ON "
        "vaaet_feedback.human_validations (prediction_id, reviewed_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX idx_pipeline_runs_workflow_started ON "
        "vaaet_ops.pipeline_runs (workflow, started_at DESC)"
    )

    # Recreate active views with stable, explicit projections.
    op.execute("DROP VIEW IF EXISTS public.traffic_classifications")
    op.execute("DROP VIEW IF EXISTS public.telemetry_raw")
    op.execute("DROP VIEW IF EXISTS public.traffic_data")
    op.execute("DROP VIEW IF EXISTS vaaet_feedback.review_queue")
    op.execute("DROP VIEW IF EXISTS vaaet_feedback.effective_human_labels")
    op.execute(
        """
        CREATE VIEW vaaet_feedback.effective_human_labels AS
        SELECT f.id, f.source_record_id, f.pipeline_run_id, f.clip_id, f.record_time,
               f.feature_schema_version, f.avg_speed, f.total_vehicles,
               f.count_car, f.count_truck, f.count_bus, f.count_motorcycle,
               f.count_bicycle, f.heavy_vehicle_ratio, f.delta_speed, f.delta_count,
               f.transition_flag, f.speed_variance, f.cumulative_delta_speed,
               f.low_speed_persistence, f.speed_measurement_quality,
               f.optical_flow_tracking_ratio, f.near_zero_motion_ratio,
               f.stationary_confirmed_ratio, f.near_zero_motion_count,
               f.stationary_confirmed_count, f.rejected_speed_count,
               f.recovered_track_count, f.speed_sample_count,
               f.telemetry_schema_version, f.data_origin, f.synthetic_scenario,
               f.hour_of_day, f.weather_condition, f.created_at,
               p.id AS prediction_id, p.model_version,
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
        SELECT p.id AS prediction_id, p.pipeline_run_id, f.clip_id, f.record_time,
               p.traffic_state, p.state_label, p.confidence, p.model_version,
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
        SELECT id, pipeline_run_id, clip_id, record_time, avg_speed, count_car,
               count_truck, count_bus, count_motorcycle, count_bicycle,
               total_vehicles, near_zero_motion_count, stationary_confirmed_count,
               rejected_speed_count, recovered_track_count, speed_sample_count,
               speed_measurement_quality, optical_flow_tracking_ratio,
               telemetry_schema_version, created_at
        FROM vaaet_raw.traffic_data
        """
    )
    op.execute(
        """
        CREATE VIEW public.telemetry_raw AS
        SELECT id, source_record_id, pipeline_run_id, clip_id, record_time,
               feature_schema_version, avg_speed, total_vehicles, count_car,
               count_truck, count_bus, count_motorcycle, count_bicycle,
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
               p.confidence, p.model_version, p.model_traffic_state,
               p.model_state_label, p.model_confidence, p.probability_margin,
               p.decision_abstained, p.measurement_reliable,
               p.accident_rule_triggered, p.accident_alert_started,
               p.accident_evidence_score,
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

    op.execute(
        """
        DO $$ DECLARE item RECORD;
        BEGIN
          FOR item IN
            SELECT n.nspname AS schema_name, c.relname AS table_name,
                   a.attname AS column_name
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_description d
              ON d.objoid = c.oid AND d.objsubid = a.attnum
            WHERE n.nspname IN ('vaaet_raw', 'vaaet_ml', 'vaaet_feedback', 'vaaet_ops')
              AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
              AND d.description IS NULL
          LOOP
            EXECUTE format(
              'COMMENT ON COLUMN %I.%I.%I IS %L',
              item.schema_name, item.table_name, item.column_name,
              'VAAET managed contract field: ' || replace(item.column_name, '_', ' ')
            );
          END LOOP;
        END $$
        """
    )

    for statement in (
        "COMMENT ON SCHEMA vaaet_raw IS 'Source telemetry captured from complete one-minute video windows'",
        "COMMENT ON SCHEMA vaaet_ml IS 'Reproducible feature snapshots and immutable model-version predictions'",
        "COMMENT ON SCHEMA vaaet_feedback IS 'Append-only human validation and review projections'",
        "COMMENT ON SCHEMA vaaet_ops IS 'Security-scoped operational lineage for VAAET workflows'",
        "COMMENT ON TABLE vaaet_raw.traffic_data IS 'Canonical raw traffic telemetry; one row per clip and complete minute'",
        "COMMENT ON TABLE vaaet_ml.telemetry_features IS 'Denormalized, versioned 19-feature snapshot used for train/serve parity'",
        "COMMENT ON TABLE vaaet_ml.traffic_predictions IS 'Automatic stable-state predictions; Accident is forbidden here'",
        "COMMENT ON TABLE vaaet_feedback.human_validations IS 'Append-only human ground truth and explicit corrections'",
        "COMMENT ON TABLE vaaet_ops.pipeline_runs IS 'Redacted lifecycle record for collection, inference, training, and review runs'",
        "COMMENT ON COLUMN vaaet_raw.traffic_data.record_time IS 'UTC end timestamp of the complete one-minute window'",
        "COMMENT ON COLUMN vaaet_raw.traffic_data.avg_speed IS 'Robust mean vehicle speed in kilometres per hour'",
        "COMMENT ON COLUMN vaaet_raw.traffic_data.telemetry_schema_version IS 'Versioned telemetry data contract identifier'",
        "COMMENT ON COLUMN vaaet_ml.telemetry_features.feature_schema_version IS 'Versioned feature semantics and exact column-order contract'",
        "COMMENT ON COLUMN vaaet_ml.traffic_predictions.traffic_state IS 'Automatic stable state: 0 Normal, 1 Reduced, 2 Congested'",
        "COMMENT ON COLUMN vaaet_feedback.human_validations.validated_state IS 'Human state: 0 Normal, 1 Reduced, 2 Congested, 3 Accident'",
        "COMMENT ON COLUMN vaaet_feedback.human_validations.supersedes_validation_id IS 'Prior validation replaced by this append-only correction'",
        "COMMENT ON COLUMN vaaet_ops.pipeline_runs.error_category IS 'Exception class only; messages and secrets are never stored'",
    ):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError(
        "PostgreSQL hardening and pipeline lineage are intentionally irreversible. "
        "Restore a pre-4.2 backup if rollback is required."
    )
