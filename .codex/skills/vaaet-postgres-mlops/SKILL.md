---
name: vaaet-postgres-mlops
description: Configure, review, diagnose, or safely evolve VAAET PostgreSQL persistence for MLOps. Use for SQLAlchemy connections, Colab Secrets, TLS, least-privilege roles, Alembic migrations, idempotent batch persistence, pipeline lineage, HITL data, backups, or PostgreSQL performance decisions.
---

# VAAET PostgreSQL MLOps

## Preserve the database contract

Use PostgreSQL 14+ through `vaaet-persistence` and preserve the existing VAAET contracts. Read ADR-0024 and ADR-0028 before changing persistence behavior. `vaaet-core` must not depend on PostgreSQL and `vaaet-persistence` must not depend on ML, Colab, DVC, Drive, YOLO, or TensorFlow. Do not change schemas, tables, views, grants, roles, migrations, the 19 features, or state semantics without explicit authorization and an ADR.

Use qualified names and their responsibilities:

| Namespace | Responsibility |
| --- | --- |
| `vaaet_raw` | Telemetry acquired from video |
| `vaaet_ml` | Canonical 19-feature snapshots and automatic predictions |
| `vaaet_feedback` | Append-only human validations and review views |
| `vaaet_ops` | Redacted, auditable pipeline runs |

Keep `public` views read-only compatibility only. Treat PostgreSQL as the operational authority; portable ZIPs are checksum-protected snapshots, not an alternate mutable database.

## Connect securely with least privilege

Use `DatabaseProfile` and `load_database_settings()` from `vaaet_persistence`. Select exactly one of `collection`, `inference`, `training`, or `review` per operation and provide the consumer's application name and version. In notebooks, keep Secrets-to-environment adaptation in `vaaet_ml`; never move Colab imports into persistence or display, serialize, or log credentials.

Build URLs through `sqlalchemy.URL.create()` and engines through the project factory. Reuse its small `QueuePool`, pre-ping, timeout, health check, redacted `DatabaseSettings`, and cleanup behavior. Do not open one connection per row or build a DSN with string interpolation.

Require `sslmode=verify-full` and a provider CA for remote endpoints. Permit `require` only as an explicit documented fallback when the provider cannot expose a CA. Permit `disable` only for explicit localhost. Do not use administrative credentials in Colab or notebooks.

## Separate administration from workflows

Run Alembic upgrades, role provisioning, grants, backups, restores, and schema diagnostics with an administrative identity outside notebooks. Notebooks consume the migrated schema with their least-privilege workflow profile and must fail clearly if it is missing or unauthorized.

Do not call `Base.metadata.create_all()`, `drop_all()`, ad-hoc DDL, `ALTER TABLE`, or Alembic from a notebook. Never restore a logical backup over a live production database. Test restores in an isolated database, preserve provider backups/PITR, and use the controlled PostgreSQL-client/TOC workflow for legacy backup ingestion.

`SECURITY DEFINER` functions used to start and finish pipeline runs are deliberate contract enforcement, not arbitrary business logic. Preserve their role checks and redaction guards.

## Persist atomically and idempotently

Use the concrete `vaaet_persistence` persistence and pipeline-run APIs. The `vaaet_ml.data` paths are compatibility facades only and must not contain duplicate SQL. Start a run before an enabled workflow, attach its UUID to raw/features/predictions or review data as applicable, and finish it with only typed, redacted metadata. Without PostgreSQL, retain the local redacted manifest and outputs.

Write related telemetry, features, and predictions in bounded batches and transactional units. Use the existing natural keys and upsert contracts; do not commit per frame, silently overwrite append-only feedback, or make persistence an implicit side effect of offline analysis.

Treat database constraints, foreign keys, explicit views, state/label checks, and append-only validation chains as the integrity boundary. Catch expected SQLAlchemy exceptions only to provide safe context, preserve the original exception chain, roll back the transaction, and propagate a domain-meaningful failure. Never log a DSN, certificate, password, private path, or raw database exception in pipeline metadata.

Automatic predictions are never human labels. Accident remains outside the MLP target and can be public only after a valid human confirmation.

## Measure before optimizing

Use indexes for demonstrated query patterns and inspect `EXPLAIN` without `ANALYZE` in production-like environments. Measure batch throughput, latency, row counts, lock behavior, query plan, peak connections, and endpoint/network conditions before proposing changes.

Treat targets such as a 1,000-row batch latency or 10,000-row ingestion rate as benchmarks to establish on a representative remote database, not as local guarantees. Do not add partitioning before the documented volume threshold or evidence of degradation. Do not introduce tables, indexes, triggers, stored procedures, or denormalization beyond the existing contract without authorization.

## Review checklist

Before accepting a PostgreSQL change, confirm:

- The workflow profile, TLS mode, and endpoint are appropriate and no secret is exposed.
- The latest Alembic revision and grants already exist; no notebook attempts schema creation.
- Alembic discovers one revision chain from installed persistence resources, and administration runs outside notebooks.
- Schema-qualified SQL, parameter binding, transaction scope, batch size, idempotency, and rollback behavior are explicit.
- `pipeline_run` lineage and local fallback metadata are complete and redacted.
- Constraints and immutable HITL relationships remain intact.
- Integration testing uses a disposable PostgreSQL instance; unit tests mock engines or sessions rather than live credentials.

Reject hardcoded credentials, global/admin profiles in notebooks, string-formatted SQL, per-row commits, unbounded bulk writes, unqualified table names, disabled TLS for remote databases, `SELECT *` in active views, DDL in data workflows, and silent recovery from integrity failures.
