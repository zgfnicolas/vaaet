---
name: vaaet-resilient-async-architecture
description: Diseñá y revisá flujos VAAET resilientes entre Python, API, web y aceleración nativa futura, sin adelantar componentes no aprobados.
---

# Arquitectura asíncrona y resiliente de VAAET

## Position and current state

Read ADR-0021 and ADR-0013 through ADR-0019 before changing workflow behavior. Read ADR-0022 for a future serving proposal. Use
`vaaet-pipeline-architecture` for vision-stage boundaries and
`vaaet-postgres-mlops` for database profiles, transactions, TLS, and schema
governance.

Describe the current implementation accurately: `vaaet.vision.analyze_video()`
is an ordered, synchronous Python per-clip loop. It has no runtime queues,
Redis, Celery, `asyncpg`, FastAPI, React, Next.js, C++, remote workers, or
distributed cache. `pipeline_run` can emit a redacted local lifecycle manifest
when PostgreSQL is unavailable; it is not a telemetry spool.

Preserve the stateful vision chain in one ordered execution context:

```text
frame -> optical flow -> YOLO -> SORT -> speed and motion
-> complete-minute telemetry -> optional prediction -> rendering
```

Do not parallelize, reorder, or externalize SORT state, optical flow, speed
smoothing, stationary detection, minute accumulation, classification policy,
or incident handling. Preserve the 19 features, bundle v3, three MLP outputs,
and human-only Accident publication.

## Keep boundaries explicit across runtimes

`vaaet-core` remains the portable Python owner of ordered vision, telemetry,
bundle validation, and inference. `vaaet-ml` remains the Python laboratory for
training, evaluation, DVC, PostgreSQL, and notebooks; it is never a serving
dependency. `vaaet-app/` remains reserved until a versioned HTTP contract,
approved scope, and the ADR-0022 serving path exist.

A future FastAPI component may be the HTTP adapter, job-status surface, and
worker coordinator. A future React or Next.js component may present request,
loading, retry, cancellation, and result states. Both consume only the approved
HTTP contract: they never import Python, read a bundle, access DVC or Drive,
connect to PostgreSQL, or expose secrets and private paths.

A future C++ component is an optional internal accelerator behind a stable
`vaaet-core` interface with an equivalent Python fallback. It does not receive
web traffic, replace public domain APIs, alter the bundle v3, or share mutable
tracker state across runtimes.

## Introduce local decoupling only with evidence

Profile a representative clip before proposing concurrency. The first allowed
candidate boundary is after a complete ordered minute of telemetry:

```text
ordered telemetry producer -> bounded queue.Queue -> one persistence consumer
```

Keep persistence opt-in and outside the vision hot path. Use a bounded,
thread-safe `queue.Queue`, a single consumer, monotonic per-clip sequence
information, explicit sentinels, cancellation, error propagation, and
deterministic shutdown. Do not use a shared `deque` or list with ad-hoc locks.

Keep tracking state in the process that owns the tracker. Let the existing
track lifecycle prune it; do not use Redis to share or mutate tracker state.
Treat cleanup jobs as a future operational concern. They may remove only
acknowledged, expired operational cache or spool entries and must never delete
pending data, governed artifacts, datasets, locks, or HITL feedback.

Ask for authorization before introducing this boundary: it is a major
architectural refactor. Reject it if it cannot preserve output ordering,
telemetry equivalence, Colab memory limits, or explicit persistence semantics.

## Persist, spool, and replay safely

Use the existing ML-laboratory workflow-specific `DatabaseProfile`, settings loader,
SQLAlchemy engine factory, TLS policy, `pipeline_run` lineage, qualified SQL,
natural keys, and transactional idempotent persistence contracts. Do not add
`asyncpg` or replace the synchronous engine merely because a worker exists.

On a future consumer failure, keep retries away from the vision thread. Apply
bounded retries only to idempotent operations. Model the circuit breaker as
`closed -> open -> half-open`: while open, stop connection attempts; permit a
controlled probe in half-open state; close only after it succeeds.

For recovery that survives a Colab reset, treat local disk as a transient
buffer, not durable storage. A future spool must:

- Write append-only batches atomically, checksum them, and checkpoint verified
  bytes to a configured persistent root before claiming durability.
- Bind each batch to its `pipeline_run` identity, workflow, schema version,
  natural keys, source ordering, and replay-safe payload identity.
- Retain a batch until its database transaction succeeds and its acknowledgement
  is durable; never silently drop, overwrite, or mix batches.
- Replay in the applicable clip order through existing idempotent writes, and
  quarantine malformed or incompatible payloads instead of guessing.

Do not put DSNs, credentials, certificates, private paths, unredacted database
exceptions, or arbitrary raw payloads in logs, lifecycle metadata, or spool
names. Use parameter binding through SQLAlchemy; never interpolate SQL strings.
Do not use administrative database credentials in a notebook or worker.

When a future HTTP request starts a persistent workflow, correlate its job
identity with `pipeline_run` only where the versioned contract authorizes it.
Define idempotency, backpressure, timeout, cancellation, retry,
acknowledgement, retention, and recovery at that boundary before coding.

## Keep distributed services future and governed

Redis, Celery, distributed caching, external schedulers, remote durable brokers,
`asyncpg`, and workers under a future approved API in `vaaet-app/` are proposals, not current
VAAET components. Those workers must use `vaaet-core`, not `vaaet-ml`. Before selecting one, obtain explicit authorization and
document the dependency, deployment identity, encryption and authentication,
retention, backpressure, failure recovery, monitoring, cost, and ADR impact.

FastAPI is a future HTTP adapter, not a durable queue or the owner of vision.
`async def` does not make `analyze_video()` non-blocking: do not run the ordered
core loop in an API event loop. Do not present `FastAPI BackgroundTasks` as
durable persistence or a substitute for a governed worker, queue, or spool.
Define job creation, cancellation, status queries, load limits, and event
transport in the HTTP contract before implementation.

React and Next.js may render explicit API states but must not duplicate work or
decide replays. Server-side rendering, route handlers, polling, SSE, and
WebSockets are future options, not default architecture. Require a use case,
authorization, resource limits, and security review before choosing one.

Use C++ only for a measured bottleneck and retain a Python fallback. Before
adopting a native binding or ML library, define data representation and layout,
units, memory ownership, copies between runtimes, cleanup, cancellation, error
translation, ABI/platform compatibility, and failure fallback. Do not assume a
GPU, released GIL, or native kernel improves the representative workload.

ONNX Runtime, TensorRT, LibTorch, C/C++ bindings, FastAPI, JavaScript,
TypeScript, React, Next.js, Redis, Celery, brokers, and additional libraries
all require explicit authorization, profiling where relevant, licensing and
redistribution review, security, deployment identity, observability, CI impact,
cost evaluation, and an ADR when architecture or contracts change.

Do not treat CAP as a reason to weaken PostgreSQL integrity. CAP is relevant
when replicated distributed services partition; PostgreSQL writes retain their
transactional consistency. A non-authoritative telemetry dashboard may be
eventually consistent while the vision pipeline continues and pending records
are durably recoverable. Human validation, artifact integrity, input locks, and
promotion remain consistency-sensitive.

Use ISO/IEC 25010 as a review lens for performance efficiency, reliability,
recoverability, and security. Use OWASP guidance to review secret handling,
least privilege, input validation, parameter binding, dependency changes, and
operational exposure. Do not claim formal compliance without an assessed scope
and evidence.

## Evaluate a proposed change

Before accepting a local queue, spool, or future broker proposal:

1. Record the baseline and the exact measured bottleneck on the same clip.
2. Define the ownership, capacity, backpressure, ordering, retry, shutdown,
   spool, acknowledgement, and replay behavior before coding.
3. Inject a PostgreSQL connection failure without blocking the vision loop and
   verify that only complete, durable batches are later replayed.
4. Compare output video, complete-minute telemetry, classifications, dropped or
   reordered records, FPS, latency, peak RAM/VRAM, backlog, and recovery time.
5. Treat less than 5% FPS degradation and zero acknowledged-data loss as
   benchmarks to measure, not current guarantees.
6. Add focused tests for ordering, queue saturation, shutdown, circuit states,
   atomic spool recovery, idempotent replay, and redaction; then run all VAAET
   repository gates.
7. For a native accelerator, compare outputs and rejection paths against the
   Python fallback with small inputs and boundary cases, including memory and
   binding failures.
8. For an API or web proposal, validate the versioned contract, authorization,
   cancellation, retries, redaction, and absence of internal-resource leakage.

Reject blocking network I/O in the vision thread, unbounded queues, commits per
frame, long-lived transactions, automatic promotion, mutable or ephemeral-only
recovery claims, SQL interpolation, concurrent tracker mutation, and unmeasured
availability or performance claims. Also reject API event loops that execute
vision directly, UI retries that duplicate work, and native acceleration without
measured evidence and a validated fallback.
