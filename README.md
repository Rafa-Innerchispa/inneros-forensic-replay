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

## Architecture direction

Phase 1 keeps the implementation deliberately small:

`Raw Capture -> Content-Addressed Evidence Bundle -> Manifest -> Replay API`

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

## Status

Bootstrap started September 2026. The repository is intentionally small while the evidence contract is stabilized before adding infrastructure dependencies.
