# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Añade comprobantes transaccionales para recuperar auditorías verificables.

Revision ID: 20260920_0006
Revises: 20260911_0005
"""

from __future__ import annotations

from alembic import op

revision = "20260920_0006"
down_revision = "20260911_0005"
branch_labels = None
depends_on = None

_WORKFLOW_ROLES = (
    "vaaet_collection_role",
    "vaaet_inference_role",
    "vaaet_training_role",
    "vaaet_reviewer_role",
)


def upgrade() -> None:
    """Incorpora evidencia inmutable sin reconstruir corridas históricas."""

    op.execute(
        "ALTER TABLE vaaet_ops.pipeline_runs ADD COLUMN reconciles_run_id UUID "
        "REFERENCES vaaet_ops.pipeline_runs(id) ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pipeline_runs_reconciles_run ON "
        "vaaet_ops.pipeline_runs (reconciles_run_id) WHERE reconciles_run_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE vaaet_ops.persistence_receipts (
          pipeline_run_id UUID PRIMARY KEY
            REFERENCES vaaet_ops.pipeline_runs(id) ON DELETE RESTRICT,
          operation TEXT NOT NULL,
          fingerprint_algorithm TEXT NOT NULL,
          content_fingerprint CHAR(64) NOT NULL,
          processed_counts JSONB NOT NULL,
          inserted_counts JSONB NOT NULL,
          telemetry_schema_version TEXT,
          feature_schema_version TEXT,
          model_revision CHAR(64),
          confirmed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          database_user NAME NOT NULL,
          CONSTRAINT ck_receipt_operation CHECK (
            operation IN ('raw-telemetry', 'classified-telemetry', 'human-validation')
          ),
          CONSTRAINT ck_receipt_algorithm CHECK (
            fingerprint_algorithm = 'sha256-persistence-contract-v1'
          ),
          CONSTRAINT ck_receipt_fingerprint CHECK (
            content_fingerprint ~ '^[0-9a-f]{64}$'
          ),
          CONSTRAINT ck_receipt_model_revision CHECK (
            model_revision IS NULL OR model_revision ~ '^[0-9a-f]{64}$'
          ),
          CONSTRAINT ck_receipt_processed_object CHECK (
            jsonb_typeof(processed_counts) = 'object'
          ),
          CONSTRAINT ck_receipt_inserted_object CHECK (
            jsonb_typeof(inserted_counts) = 'object'
          )
        )
        """
    )
    op.execute("REVOKE ALL ON vaaet_ops.persistence_receipts FROM PUBLIC")
    op.execute(
        "COMMENT ON TABLE vaaet_ops.persistence_receipts IS "
        "'Immutable transactional proof of the exact contractual content written by a run'"
    )
    op.execute(
        "COMMENT ON COLUMN vaaet_ops.pipeline_runs.reconciles_run_id IS "
        "'Original incomplete run completed by this distinct reconciliation attempt'"
    )
    for column, description in (
        ("pipeline_run_id", "Writing run proven by this immutable receipt"),
        ("operation", "Contractual write operation covered by the receipt"),
        ("fingerprint_algorithm", "Versioned canonical fingerprint algorithm"),
        ("content_fingerprint", "SHA-256 of typed contractual observations"),
        ("processed_counts", "Entity counts presented by the writing operation"),
        ("inserted_counts", "Entity counts inserted for the first time"),
        ("telemetry_schema_version", "Telemetry contract covered by the receipt"),
        ("feature_schema_version", "Feature contract covered by the receipt"),
        ("model_revision", "Exact model revision covered by the receipt"),
        ("confirmed_at", "Database confirmation time inside the data transaction"),
        ("database_user", "Operational owner that confirmed the write"),
    ):
        op.execute(
            f"COMMENT ON COLUMN vaaet_ops.persistence_receipts.{column} IS '{description}'"
        )
    _create_receipt_function()
    _create_audit_state_function()
    _create_reconciliation_function()
    _create_pending_review_function()
    for role in _WORKFLOW_ROLES:
        _grant_when_role_exists(role)


def _create_receipt_function() -> None:
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.record_persistence_receipt(
          p_pipeline_run_id UUID,
          p_operation TEXT,
          p_fingerprint_algorithm TEXT,
          p_content_fingerprint TEXT,
          p_processed_counts JSONB,
          p_inserted_counts JSONB,
          p_telemetry_schema_version TEXT DEFAULT NULL,
          p_feature_schema_version TEXT DEFAULT NULL,
          p_model_revision TEXT DEFAULT NULL
        ) RETURNS TABLE (
          pipeline_run_id UUID, operation TEXT, fingerprint_algorithm TEXT,
          content_fingerprint TEXT, processed_counts JSONB, inserted_counts JSONB,
          receipt_telemetry_schema_version TEXT, receipt_feature_schema_version TEXT,
          receipt_model_revision TEXT, confirmed_at TIMESTAMPTZ,
          receipt_database_user TEXT
        )
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE
          run vaaet_ops.pipeline_runs%ROWTYPE;
          existing vaaet_ops.persistence_receipts%ROWTYPE;
          expected_workflow TEXT;
        BEGIN
          IF p_fingerprint_algorithm <> 'sha256-persistence-contract-v1' OR
             p_content_fingerprint !~ '^[0-9a-f]{64}$' OR
             jsonb_typeof(p_processed_counts) <> 'object' OR
             jsonb_typeof(p_inserted_counts) <> 'object' OR
             EXISTS (
               SELECT 1 FROM jsonb_each(p_processed_counts)
               WHERE jsonb_typeof(value) <> 'number' OR (value::text)::numeric < 0 OR
                     trunc((value::text)::numeric) <> (value::text)::numeric
             ) OR
             EXISTS (
               SELECT 1 FROM jsonb_each(p_inserted_counts)
               WHERE jsonb_typeof(value) <> 'number' OR (value::text)::numeric < 0 OR
                     trunc((value::text)::numeric) <> (value::text)::numeric
             ) OR
             (SELECT count(*) FROM jsonb_object_keys(p_processed_counts)) <>
               (SELECT count(*) FROM jsonb_object_keys(p_inserted_counts)) OR
             EXISTS (
               SELECT 1 FROM jsonb_each(p_inserted_counts) inserted
               WHERE NOT (p_processed_counts ? inserted.key) OR
                 (inserted.value::text)::numeric >
                   ((p_processed_counts -> inserted.key)::text)::numeric
             )
          THEN
            RAISE EXCEPTION 'Persistence receipt contract is invalid'
              USING ERRCODE = '22023';
          END IF;
          expected_workflow := CASE p_operation
            WHEN 'raw-telemetry' THEN 'collection'
            WHEN 'classified-telemetry' THEN 'inference'
            WHEN 'human-validation' THEN 'review'
            ELSE NULL END;
          IF expected_workflow IS NULL THEN
            RAISE EXCEPTION 'Persistence receipt operation is unsupported'
              USING ERRCODE = '22023';
          END IF;
          IF (p_operation = 'raw-telemetry' AND
              ((SELECT count(*) FROM jsonb_object_keys(p_processed_counts)) <> 1 OR
               NOT (p_processed_counts ? 'raw_telemetry'))) OR
             (p_operation = 'classified-telemetry' AND
              ((SELECT count(*) FROM jsonb_object_keys(p_processed_counts)) <> 2 OR
               NOT (p_processed_counts ? 'telemetry_features') OR
               NOT (p_processed_counts ? 'traffic_predictions'))) OR
             (p_operation = 'human-validation' AND
              ((SELECT count(*) FROM jsonb_object_keys(p_processed_counts)) <> 1 OR
               NOT (p_processed_counts ? 'human_validations')))
          THEN
            RAISE EXCEPTION 'Persistence receipt entity counts are incompatible'
              USING ERRCODE = '22023';
          END IF;

          PERFORM pg_advisory_xact_lock(hashtextextended(p_pipeline_run_id::text, 0));
          SELECT * INTO run FROM vaaet_ops.pipeline_runs
          WHERE id = p_pipeline_run_id FOR UPDATE;
          IF NOT FOUND OR run.database_user <> SESSION_USER OR
             run.workflow <> expected_workflow
          THEN
            RAISE EXCEPTION 'Pipeline run is missing, incompatible, or owned by another user'
              USING ERRCODE = '42501';
          END IF;

          SELECT * INTO existing FROM vaaet_ops.persistence_receipts
          WHERE vaaet_ops.persistence_receipts.pipeline_run_id = p_pipeline_run_id;
          IF FOUND THEN
            IF existing.operation = p_operation AND
               existing.fingerprint_algorithm = p_fingerprint_algorithm AND
               existing.content_fingerprint = p_content_fingerprint AND
               existing.processed_counts = p_processed_counts AND
               existing.telemetry_schema_version IS NOT DISTINCT FROM p_telemetry_schema_version AND
               existing.feature_schema_version IS NOT DISTINCT FROM p_feature_schema_version AND
               existing.model_revision IS NOT DISTINCT FROM p_model_revision
            THEN
              RETURN QUERY SELECT existing.pipeline_run_id, existing.operation,
                existing.fingerprint_algorithm, existing.content_fingerprint::TEXT,
                existing.processed_counts, existing.inserted_counts,
                existing.telemetry_schema_version, existing.feature_schema_version,
                existing.model_revision::TEXT, existing.confirmed_at,
                existing.database_user::TEXT;
              RETURN;
            END IF;
            RAISE EXCEPTION 'Immutable persistence receipt conflict'
              USING ERRCODE = '23505';
          END IF;
          IF run.status <> 'running' THEN
            RAISE EXCEPTION 'A receipt cannot be added to a terminal run'
              USING ERRCODE = '23505';
          END IF;

          INSERT INTO vaaet_ops.persistence_receipts (
            pipeline_run_id, operation, fingerprint_algorithm, content_fingerprint,
            processed_counts, inserted_counts, telemetry_schema_version,
            feature_schema_version, model_revision, database_user
          ) VALUES (
            p_pipeline_run_id, p_operation, p_fingerprint_algorithm,
            p_content_fingerprint, p_processed_counts, p_inserted_counts,
            p_telemetry_schema_version, p_feature_schema_version, p_model_revision,
            SESSION_USER
          ) RETURNING * INTO existing;
          RETURN QUERY SELECT existing.pipeline_run_id, existing.operation,
            existing.fingerprint_algorithm, existing.content_fingerprint::TEXT,
            existing.processed_counts, existing.inserted_counts,
            existing.telemetry_schema_version, existing.feature_schema_version,
            existing.model_revision::TEXT, existing.confirmed_at,
            existing.database_user::TEXT;
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_ops.record_persistence_receipt("
        "UUID,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT) FROM PUBLIC"
    )


def _create_audit_state_function() -> None:
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.read_pipeline_run_audit_state(p_pipeline_run_id UUID)
        RETURNS TABLE (
          pipeline_run_id UUID, workflow TEXT, application_name TEXT,
          application_version TEXT, database_user TEXT, status TEXT,
          source_kind TEXT, clip_id TEXT, input_rows BIGINT, output_rows BIGINT,
          telemetry_schema_version TEXT, feature_schema_version TEXT,
          model_version TEXT, model_revision TEXT, reconciles_run_id UUID,
          operation TEXT, fingerprint_algorithm TEXT, content_fingerprint TEXT,
          processed_counts JSONB, inserted_counts JSONB,
          receipt_telemetry_schema_version TEXT, receipt_feature_schema_version TEXT,
          receipt_model_revision TEXT, confirmed_at TIMESTAMPTZ,
          receipt_database_user TEXT
        )
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE run vaaet_ops.pipeline_runs%ROWTYPE;
        BEGIN
          SELECT * INTO run FROM vaaet_ops.pipeline_runs WHERE id = p_pipeline_run_id;
          IF NOT FOUND OR NOT (
            run.database_user = SESSION_USER OR
            pg_has_role(SESSION_USER, 'vaaet_training_role', 'member')
          ) THEN
            RAISE EXCEPTION 'Pipeline run is missing or not visible to this user'
              USING ERRCODE = '42501';
          END IF;
          RETURN QUERY
          SELECT r.id, r.workflow, r.application_name, r.application_version,
            r.database_user::TEXT, r.status, r.source_kind, r.clip_id,
            r.input_rows, r.output_rows, r.telemetry_schema_version,
            r.feature_schema_version, r.model_version, r.model_revision,
            r.reconciles_run_id, p.operation, p.fingerprint_algorithm,
            p.content_fingerprint::TEXT, p.processed_counts, p.inserted_counts,
            p.telemetry_schema_version, p.feature_schema_version,
            p.model_revision::TEXT, p.confirmed_at, p.database_user::TEXT
          FROM vaaet_ops.pipeline_runs r
          LEFT JOIN vaaet_ops.persistence_receipts p ON p.pipeline_run_id = r.id
          WHERE r.id = p_pipeline_run_id;
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_ops.read_pipeline_run_audit_state(UUID) FROM PUBLIC"
    )


def _create_reconciliation_function() -> None:
    op.execute(
        """
        CREATE FUNCTION vaaet_ops.complete_verified_reconciliation(
          p_original_run_id UUID, p_reconciliation_run_id UUID,
          p_application_version TEXT, p_operation TEXT,
          p_content_fingerprint TEXT, p_output_rows BIGINT,
          p_model_revision TEXT DEFAULT NULL
        ) RETURNS UUID
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_ops
        AS $$
        DECLARE
          original vaaet_ops.pipeline_runs%ROWTYPE;
          receipt vaaet_ops.persistence_receipts%ROWTYPE;
          existing vaaet_ops.pipeline_runs%ROWTYPE;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended(p_original_run_id::text, 0));
          SELECT * INTO original FROM vaaet_ops.pipeline_runs
          WHERE id = p_original_run_id FOR UPDATE;
          IF NOT FOUND OR original.database_user <> SESSION_USER THEN
            RAISE EXCEPTION 'Original run is missing or owned by another user'
              USING ERRCODE = '42501';
          END IF;
          SELECT * INTO receipt FROM vaaet_ops.persistence_receipts
          WHERE pipeline_run_id = p_original_run_id;
          IF NOT FOUND OR receipt.operation <> p_operation OR
             receipt.content_fingerprint <> p_content_fingerprint OR
             receipt.model_revision IS DISTINCT FROM p_model_revision
          THEN
            RAISE EXCEPTION 'Reconciliation evidence does not match the original receipt'
              USING ERRCODE = '23514';
          END IF;
          IF original.input_rows IS DISTINCT FROM p_output_rows OR
             original.model_revision IS DISTINCT FROM p_model_revision
          THEN
            RAISE EXCEPTION 'Reconciliation metadata contradicts the original run'
              USING ERRCODE = '23514';
          END IF;
          IF (p_operation = 'raw-telemetry' AND
              (receipt.processed_counts ->> 'raw_telemetry')::BIGINT <> p_output_rows) OR
             (p_operation = 'classified-telemetry' AND
              ((receipt.processed_counts ->> 'telemetry_features')::BIGINT <> p_output_rows OR
               (receipt.processed_counts ->> 'traffic_predictions')::BIGINT <> p_output_rows)) OR
             (p_operation = 'human-validation' AND
              (receipt.processed_counts ->> 'human_validations')::BIGINT <> p_output_rows)
          THEN
            RAISE EXCEPTION 'Reconciliation support contradicts the original receipt'
              USING ERRCODE = '23514';
          END IF;
          IF original.status = 'succeeded' AND
             original.output_rows IS DISTINCT FROM p_output_rows
          THEN
            RAISE EXCEPTION 'Terminal run output contradicts reconciliation evidence'
              USING ERRCODE = '23514';
          END IF;

          SELECT * INTO existing FROM vaaet_ops.pipeline_runs
          WHERE reconciles_run_id = p_original_run_id;
          IF FOUND THEN
            IF existing.id = p_reconciliation_run_id AND existing.status = 'succeeded' THEN
              RETURN existing.id;
            END IF;
            RAISE EXCEPTION 'A different reconciliation already exists'
              USING ERRCODE = '23505';
          END IF;
          IF original.status = 'succeeded' THEN
            RETURN p_original_run_id;
          END IF;
          IF original.status <> 'running' THEN
            RAISE EXCEPTION 'Only an incomplete running run can be reconciled'
              USING ERRCODE = '23505';
          END IF;

          INSERT INTO vaaet_ops.pipeline_runs (
            id, workflow, application_name, application_version,
            telemetry_schema_version, feature_schema_version, model_version,
            model_revision, source_kind, clip_id, input_rows, output_rows,
            database_user, status, completed_at, reconciles_run_id
          ) VALUES (
            p_reconciliation_run_id, original.workflow,
            'vaaet-persistence-reconciliation', p_application_version,
            original.telemetry_schema_version, original.feature_schema_version,
            original.model_version, original.model_revision,
            'audit-reconciliation', original.clip_id, original.input_rows,
            p_output_rows, SESSION_USER, 'succeeded', CURRENT_TIMESTAMP,
            p_original_run_id
          );
          UPDATE vaaet_ops.pipeline_runs SET status = 'succeeded',
            completed_at = CURRENT_TIMESTAMP, output_rows = p_output_rows,
            error_category = NULL
          WHERE id = p_original_run_id;
          RETURN p_reconciliation_run_id;
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_ops.complete_verified_reconciliation("
        "UUID,UUID,TEXT,TEXT,TEXT,BIGINT,TEXT) FROM PUBLIC"
    )


def _create_pending_review_function() -> None:
    op.execute(
        """
        CREATE FUNCTION vaaet_feedback.list_pending_validation_audits(
          p_feature_schema_version TEXT DEFAULT NULL
        ) RETURNS TABLE (validation_id UUID, pipeline_run_id UUID)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, vaaet_feedback, vaaet_ml, vaaet_ops
        AS $$
        BEGIN
          IF NOT (
            pg_has_role(SESSION_USER, 'vaaet_training_role', 'member') OR
            pg_has_role(SESSION_USER, 'vaaet_reviewer_role', 'member')
          ) THEN
            RAISE EXCEPTION 'Role is not authorized to inspect review audit state'
              USING ERRCODE = '42501';
          END IF;
          RETURN QUERY
          SELECT hv.id, hv.pipeline_run_id
          FROM vaaet_feedback.human_validations hv
          JOIN vaaet_ml.traffic_predictions p ON p.id = hv.prediction_id
          JOIN vaaet_ml.telemetry_features f ON f.id = p.telemetry_feature_id
          JOIN vaaet_ops.pipeline_runs r ON r.id = hv.pipeline_run_id
          LEFT JOIN vaaet_ops.persistence_receipts pr
            ON pr.pipeline_run_id = hv.pipeline_run_id
          WHERE (p_feature_schema_version IS NULL OR
                 f.feature_schema_version = p_feature_schema_version)
            AND (r.status <> 'succeeded' OR pr.pipeline_run_id IS NULL OR
                 pr.operation <> 'human-validation');
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_feedback.list_pending_validation_audits(TEXT) "
        "FROM PUBLIC"
    )


def _grant_when_role_exists(role: str) -> None:
    pending_audit_grant = (
        "GRANT EXECUTE ON FUNCTION "
        "vaaet_feedback.list_pending_validation_audits(TEXT) "
        f"TO {role};"
        if role in {"vaaet_training_role", "vaaet_reviewer_role"}
        else ""
    )
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            GRANT EXECUTE ON FUNCTION vaaet_ops.record_persistence_receipt(
              UUID,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT
            ) TO {role};
            GRANT EXECUTE ON FUNCTION vaaet_ops.read_pipeline_run_audit_state(UUID)
              TO {role};
            GRANT EXECUTE ON FUNCTION vaaet_ops.complete_verified_reconciliation(
              UUID,UUID,TEXT,TEXT,TEXT,BIGINT,TEXT
            ) TO {role};
            {pending_audit_grant}
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Transactional persistence receipts are forward-only; restore a pre-0006 backup "
        "or apply a governed forward correction."
    )
