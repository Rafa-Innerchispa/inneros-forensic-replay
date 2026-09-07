# InnerOS Forensic Replay

A reusable forensic evidence and replay layer for governed AI agents.

## Purpose

InnerOS Forensic Replay captures the exact state an agent saw before a decision, binds it to the resulting reasoning, policy evaluation, actions, and artifacts, and makes the run auditable and replayable later.

The core question is:

> What did the agent know, what policy was active, and what exact state of the world produced that decision?

## Replay modes

1. **Audit Replay**: reconstruct the original run from preserved evidence without contacting live external systems.
2. **Deterministic Replay**: re-run deterministic transforms and policy code against the original captured inputs with network and side effects disabled.
3. **Counterfactual Replay**: evaluate the same historical evidence with a different model or policy version and compare outcomes.

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

## Architecture direction

Phase 1 keeps the implementation deliberately small:

`Raw Capture -> Content-Addressed Evidence Bundle -> Manifest -> Replay API`

Core APIs:

- `EvidenceBundleWriter.capture_raw(...)` persists raw bytes and records the
  digest in the manifest.
- `EvidenceBundleWriter.capture_json(...)` persists canonical JSON bytes so
  repeated captures are stable.
- `EvidenceBundleReader.verify()` checks the manifest and all artifact hashes.
- `AuditReplayer.load()` returns preserved evidence only; it never contacts
  live systems.
- `DeterministicReplayer.run_transform(...)` verifies evidence and runs a local
  deterministic transform with outbound network calls blocked.

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

## First target

The first adapter will be **InnerOS Alpha / Alpaca** so a historical recommendation can be audited against the exact market snapshot, option-chain evidence, portfolio state, model output, and risk policy that produced it.

See `docs/alpaca_adapter_contract.md` for the capture contract. The replay core
does not import Alpaca clients or credentials; adapters must capture raw payloads
before normalization and pass bytes/JSON into the bundle writer.

## Development

```bash
python -m unittest discover -s tests
```

The test suite covers SHA verification, missing-evidence fail-closed behavior
and replay execution with network disabled.

## Status

Bootstrap started September 2026. The repository is intentionally small while the evidence contract is stabilized before adding infrastructure dependencies.
