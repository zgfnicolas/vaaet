# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Corrige la serialización HITL para el rol reviewer de mínimo privilegio.

Revision ID: 20260911_0005
Revises: 20260909_0004
"""

from __future__ import annotations

from alembic import op

revision = "20260911_0005"
down_revision = "20260909_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Conserva append-only sin exigir UPDATE al usuario revisor."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION vaaet_feedback.validate_superseded_validation()
        RETURNS TRIGGER LANGUAGE plpgsql SECURITY INVOKER
        SET search_path = pg_catalog, vaaet_feedback, vaaet_ml
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
          WHERE id = NEW.supersedes_validation_id;
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
    op.execute(
        "REVOKE ALL ON FUNCTION vaaet_feedback.validate_superseded_validation() FROM PUBLIC"
    )
    op.execute(
        "COMMENT ON FUNCTION vaaet_feedback.validate_superseded_validation() IS "
        "'Serializes append-only review chains using an advisory lock without UPDATE privilege'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "The least-privilege HITL correction is forward-only; restore a pre-0005 backup "
        "or apply a governed forward correction."
    )
