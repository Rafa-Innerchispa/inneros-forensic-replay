# Platform and Service Ops Audit Integration

This repository owns the small forensic replay SDK. Platform and Service Ops should import or adapt these contracts instead of redefining audit payloads in each runtime.

## Minimal Capture Flow

1. Capture raw external inputs with `EvidenceBundleWriter` before normalization.
2. Capture model output and selected action contract as raw artifacts.
3. Write the evidence manifest.
4. Build one `AuditEnvelope` that references evidence by SHA-256 and relative path.
5. Store or emit the envelope to the coordination/audit fabric.
6. Run deterministic replay only against preserved evidence.

```python
from inneros_forensic_replay import (
    DecisionEvidence,
    EvidenceBundleWriter,
    HTRRecord,
    RoutingEvidence,
    build_audit_envelope,
)

writer = EvidenceBundleWriter(bundle_dir, correlation_id=correlation_id)
writer.capture_json("external.input.raw", raw_payload, source="service.connector")
writer.capture_json("model.output.raw", model_output, source=model_ref)
manifest = writer.write_manifest(trace={"otel_trace_id": trace_id})

envelope = build_audit_envelope(
    manifest,
    decision=DecisionEvidence(
        decision_id=decision_id,
        model_ref=model_ref,
        policy_ref=policy_version,
        summary={"result": "approved"},
    ),
    routing=RoutingEvidence(
        selected_agent=agent_name,
        selected_model=model_ref,
        route_reason="local-first route selected by Resource Fabric",
        queue_id="nats.audit.events",
        worker_id=worker_id,
        trace_refs=(trace_id,),
    ),
    htr=HTRRecord(
        task_id=task_id,
        measurement_mode="MEASURED",
        baseline_human_minutes="60",
        assisted_active_human_minutes="12",
        rework_human_minutes="3",
        measurement_source="agent_activity_report + task timer",
        interventions=1,
        handoffs=1,
    ),
)
```

## HTR Quality Gate

`HTRRecord` supports two modes:

- `MEASURED`: requires `measurement_source` and is high-confidence evidence.
- `ESTIMATED`: requires `estimate_reason` and is allowed, but remains marked as estimated.

HTR must preserve:

- `baseline_human_minutes`
- `assisted_active_human_minutes`
- `rework_human_minutes`
- `returned_human_minutes`
- `interventions`
- `handoffs`
- `local_compute_seconds`
- `cloud_compute_seconds`
- `external_cost_usd`

Negative returned time is not hidden. It is emitted with quality gate `negative_return` so dashboards can show rework instead of pretending there was a saving.

## Evidence Boundary

`AuditEnvelope` does not copy raw event payloads. It stores `SourceRef` pointers with logical name, SHA-256, media type, size, source and relative path. Raw payloads remain in the evidence bundle and are verified before replay.

Replay modes stay separate:

- Audit replay loads preserved evidence.
- Deterministic replay runs local transforms with network disabled.
- Counterfactual replay requires a label and returns a separate result object.

## Parquet / JSONL

This SDK has no hard dependency on Parquet. `write_audit_jsonl` provides an explicit JSONL fallback. Platform may add Parquet/DuckDB writers when that runtime is available, but it must not imply Parquet was used when the SDK emitted JSONL.

## Recommended Platform Hook

Platform should emit the envelope after task execution reaches an auditable state:

- task accepted or selected
- worker/model selected
- external/local inputs captured
- model output captured
- action/result captured
- HTR measurement or estimate recorded

The envelope can then be mirrored into Mongo, NATS JetStream, object storage or OpenTelemetry-linked traces without changing the source bundle.

## Canonical JSON Interop

Non-Python consumers, including Service Ops JS, should use the canonical snake_case JSON shape documented in `docs/audit_envelope_interop_schema.json`. `docs/sample_audit_envelope.json` is the executable fixture generated from the Python SDK. UI adapters may map to camelCase at the edge, but persisted audit envelopes, evidence bundles and replay fixtures remain snake_case.
