-- Run once with the PostgreSQL administrator after `alembic upgrade head`.
-- These are NOLOGIN group roles; create provider-specific LOGIN users separately
-- and GRANT the appropriate group role to each user.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vaaet_collection_role') THEN CREATE ROLE vaaet_collection_role NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vaaet_inference_role') THEN CREATE ROLE vaaet_inference_role NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vaaet_training_role') THEN CREATE ROLE vaaet_training_role NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vaaet_reviewer_role') THEN CREATE ROLE vaaet_reviewer_role NOLOGIN; END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops FROM PUBLIC;

GRANT USAGE ON SCHEMA vaaet_raw, vaaet_ops TO vaaet_collection_role;
GRANT INSERT ON vaaet_raw.traffic_data TO vaaet_collection_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA vaaet_raw TO vaaet_collection_role;

GRANT USAGE ON SCHEMA vaaet_ml, vaaet_ops TO vaaet_inference_role;
REVOKE UPDATE, DELETE ON vaaet_ml.telemetry_features, vaaet_ml.traffic_predictions FROM vaaet_inference_role;
GRANT SELECT, INSERT ON vaaet_ml.telemetry_features, vaaet_ml.traffic_predictions TO vaaet_inference_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA vaaet_ml TO vaaet_inference_role;

GRANT USAGE ON SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops TO vaaet_training_role;
GRANT SELECT ON ALL TABLES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops TO vaaet_training_role;
GRANT SELECT ON public.alembic_version TO vaaet_training_role;

GRANT USAGE ON SCHEMA vaaet_ml, vaaet_feedback, vaaet_ops TO vaaet_reviewer_role;
GRANT SELECT ON vaaet_ml.telemetry_features, vaaet_ml.traffic_predictions TO vaaet_reviewer_role;
GRANT SELECT ON vaaet_feedback.review_queue TO vaaet_reviewer_role;
GRANT SELECT, INSERT ON vaaet_feedback.human_validations TO vaaet_reviewer_role;

GRANT SELECT ON public.traffic_data TO vaaet_collection_role, vaaet_training_role;
GRANT SELECT ON public.telemetry_raw TO vaaet_inference_role, vaaet_training_role;
GRANT SELECT ON public.traffic_classifications TO vaaet_training_role, vaaet_reviewer_role;

GRANT EXECUTE ON FUNCTION vaaet_ops.start_pipeline_run(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT)
  TO vaaet_collection_role, vaaet_inference_role, vaaet_training_role, vaaet_reviewer_role;
GRANT EXECUTE ON FUNCTION vaaet_ops.finish_pipeline_run(UUID, TEXT, BIGINT, TEXT, TEXT)
  TO vaaet_collection_role, vaaet_inference_role, vaaet_training_role, vaaet_reviewer_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops
  REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA vaaet_raw, vaaet_ml, vaaet_feedback, vaaet_ops
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

REVOKE INSERT, UPDATE, DELETE ON public.traffic_data, public.telemetry_raw, public.traffic_classifications FROM PUBLIC;
