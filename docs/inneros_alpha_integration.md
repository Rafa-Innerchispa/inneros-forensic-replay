# InnerOS Alpha Integration Notes

Status: SDK contract only. No broker writes. No trading runtime changes.

## Hook Point

InnerOS Alpha should call this SDK immediately after each read-only Alpaca API
response is received and before normalization or recommendation logic runs.

Recommended artifacts:

- `alpaca.latest_trade.raw`
- `alpaca.bars.raw`
- `alpaca.option_chain.raw`
- `alpaca.option_contracts.raw`
- `alpaca.option_snapshots.raw`
- `alpaca.portfolio.raw`
- `llm.output.original`

Large bars/options datasets can use `capture_tabular_dataset`. If `pyarrow` is
installed, the artifact media type is `application/x-parquet`; otherwise it is
`application/x-ndjson` with `storage_status=fallback_jsonl`.

## Replay Boundary

Audit replay loads preserved evidence only. Deterministic replay and
counterfactual replay run with network calls blocked. A replay must never fetch
fresh Alpaca data, place orders, mutate positions, or overwrite the original
LLM/model output.

## Counterfactual Flow

1. Load the original Evidence Bundle.
2. Verify manifest and artifact hashes.
3. Preserve `llm.output.original`.
4. Run a new local evaluator with a new model/policy descriptor.
5. Store or inspect the comparison separately from the original bundle.

This supports questions like: "What would the newer policy have recommended on
the exact historical evidence?" It does not prove that a stochastic model would
reproduce identical text.
