# InnerOS Forensic Replay

A reusable forensic evidence and replay layer for governed AI agents.

## Purpose

InnerOS Forensic Replay captures the exact state an agent saw before a decision, binds it to the resulting reasoning, policy evaluation, actions, and artifacts, and makes the run auditable and replayable later.

The core question is:

> What did the agent know, what policy was active, and what exact state of the world produced that decision?

## Replay modes

1. **Audit Replay**: reconstruct the original run from preserved evidence without contacting live external systems.
2. **Deterministic Replay**: re-run deterministic transforms and policy code against the original captured inputs with network and side effects disabled.
3. **Counterfactual Replay**: evaluate the same historical evidence with a labeled alternative policy/model context and keep the result separate from the original audit record.

## Evidence bundle v1

Each run is keyed by `correlation_id` and should preserve:

- raw external inputs or canonical raw payloads
- normalized decision snapshot
- source timestamps and freshness
- prompt and model identity/version
- original model output
- deterministic policy version
- selected actions/contracts/artifacts
- execution result
- trace events
- SHA-256 hashes for every persisted artifact
- Git commit / build identity when available

The implementation in this repository stores evidence as a content-addressed
bundle:

```text
bundle/
  manifest.json
  artifacts/
    sha256/
      ab/
        abcd...json
```

`manifest.json` contains the schema version, run identity, capture metadata and
one entry per artifact. Every artifact is addressed by its SHA-256 digest and is
verified before replay. Missing or mutated evidence fails closed.

## Audit SDK and HTR

The package also exposes a small audit contract layer for Platform, Service Ops and domain adapters:

- `SourceRef`: points to immutable evidence by logical name, SHA-256, media type, size and path without copying raw payloads.
- `DecisionEvidence`: records decision id, model identity, policy reference, action references and summary.
- `RoutingEvidence`: records selected agent/model, route reason, queue/worker and trace references.
- `HTRRecord`: records Human Time Return with explicit `MEASURED` vs `ESTIMATED` quality gates.
- `AuditEnvelope`: binds a verified evidence manifest, decision, routing and HTR into one auditable payload.

`HTRRecord` preserves baseline human minutes, assisted active minutes, rework minutes, returned time, interventions, handoffs, local/cloud seconds and external cost when available. Measured HTR requires a measurement source; estimated HTR requires an estimate reason. Negative returned time is surfaced as `negative_return`, not hidden.

`write_audit_jsonl(...)` is an explicit JSONL fallback. Parquet/DuckDB can be added by a hosting runtime when available, but this core package does not pretend to emit Parquet without that dependency.

See `docs/platform_service_ops_integration.md` for the integration contract.

## Architecture direction

Phase 1 keeps the implementation deliberately small:

`Raw Capture -> Content-Addressed Evidence Bundle -> Manifest -> Audit Envelope -> Replay API`

Core APIs:

- `EvidenceBundleWriter.capture_raw(...)` persists raw bytes and records the
  digest in the manifest.
- `EvidenceBundleWriter.capture_json(...)` persists canonical JSON bytes so
  repeated captures are stable.
- `capture_tabular_dataset(...)` stores large row-oriented evidence as Parquet
  when `pyarrow` is available, otherwise as truthful JSONL fallback.
- `EvidenceBundleReader.verify()` checks the manifest and all artifact hashes.
- `build_audit_envelope(...)` references verified evidence and attaches decision,
  routing and HTR records without copying raw payloads.
- `AuditReplayer.load()` returns preserved evidence only; it never contacts
  live systems.
- `DeterministicReplayer.run_transform(...)` verifies evidence and runs a local
  deterministic transform with outbound network calls blocked.
- `CounterfactualReplayer.compare(...)` evaluates a new model/policy descriptor
  against the same historical evidence and preserves the original output.
- `CounterfactualReplayer.run_counterfactual(...)` requires a label and keeps
  what-if results separate from the original audit record.

Planned integrations are additive rather than mandatory:

- Apache Parquet / DuckDB for large historical datasets
- NATS JetStream for durable event capture and replay
- OpenTelemetry for distributed traces
- immudb for tamper-evident manifest anchoring
- Temporal for durable workflow histories
- NautilusTrader adapters for financial market-data replay

## Design rules

- Capture before transformation.
- Never silently replace missing evidence with current data.
- Replay is side-effect-free by default.
- Original LLM output is evidence; re-running an LLM is not proof of what happened originally.
- Hash evidence at ingestion and verify it before replay.
- Separate `observed_at`, `captured_at`, and `processed_at` timestamps.
- Keep domain adapters outside the replay core.
- Store source-of-truth references in audit envelopes instead of duplicating raw evidence.

## First target

The first adapter is **InnerOS Alpha / Alpaca** so a historical recommendation can be audited against the exact market snapshot, option-chain evidence, portfolio state, model output, and risk policy that produced it.

See `docs/alpaca_adapter_contract.md` for the capture contract. The replay core
does not import Alpaca clients or credentials; adapters must capture raw payloads
before normalization and pass bytes/JSON into the bundle writer.

## v2 additions

Forensic Replay v2 adds:

- recursive secret redaction before evidence persistence
- `manifest.sha256` verification
- Alpaca raw capture for latest trade, bars, option chain, option contracts,
  option snapshots and portfolio
- optional Parquet/DuckDB-aware dataset helpers with JSONL fallback that is
  explicitly labeled as fallback
- side-effect-free counterfactual replay that never overwrites original output

InnerOS Alpha should integrate this SDK through hooks at the market-data capture
boundary: immediately after a read-only Alpaca response returns and before any
normalization, scoring, recommendation, or order logic. This repository does not
perform broker writes, cloud calls, order placement, or live data refresh during
replay.

## Development

```bash
python -m unittest discover -s tests
```

The test suite covers SHA verification, missing-evidence fail-closed behavior,
replay execution with network disabled, HTR quality gates, JSONL fallback and a
capture -> verify -> audit -> HTR -> replay smoke path.

## Status

Bootstrap started September 2026. The repository remains intentionally small while the evidence contract is stabilized before adding infrastructure dependencies.
