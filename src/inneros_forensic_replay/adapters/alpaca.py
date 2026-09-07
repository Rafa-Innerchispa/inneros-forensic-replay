from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inneros_forensic_replay.bundle import EvidenceBundleWriter, sanitize_for_evidence


@dataclass(frozen=True)
class AlpacaCapture:
    latest_trade: dict[str, Any]
    bars: dict[str, Any]
    portfolio: dict[str, Any]
    observed_at: str
    option_chain: dict[str, Any] | None = None
    option_contracts: dict[str, Any] | None = None
    option_snapshots: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


def capture_alpaca_snapshot(writer: EvidenceBundleWriter, snapshot: AlpacaCapture) -> None:
    """Persist raw Alpaca evidence without importing an Alpaca API client."""

    metadata = {
        "adapter_version": "alpaca-capture-v2",
        **sanitize_for_evidence(snapshot.metadata or {}),
    }
    writer.capture_json(
        "alpaca.latest_trade.raw",
        sanitize_for_evidence(snapshot.latest_trade),
        observed_at=snapshot.observed_at,
        source="alpaca.latest_trade",
        metadata=metadata,
    )
    writer.capture_json(
        "alpaca.bars.raw",
        sanitize_for_evidence(snapshot.bars),
        observed_at=snapshot.observed_at,
        source="alpaca.bars",
        metadata=metadata,
    )
    if snapshot.option_chain is not None:
        writer.capture_json(
            "alpaca.option_chain.raw",
            sanitize_for_evidence(snapshot.option_chain),
            observed_at=snapshot.observed_at,
            source="alpaca.option_chain",
            metadata=metadata,
        )
    if snapshot.option_contracts is not None:
        writer.capture_json(
            "alpaca.option_contracts.raw",
            sanitize_for_evidence(snapshot.option_contracts),
            observed_at=snapshot.observed_at,
            source="alpaca.option_contracts",
            metadata=metadata,
        )
    if snapshot.option_snapshots is not None:
        writer.capture_json(
            "alpaca.option_snapshots.raw",
            sanitize_for_evidence(snapshot.option_snapshots),
            observed_at=snapshot.observed_at,
            source="alpaca.option_snapshots",
            metadata=metadata,
        )
    writer.capture_json(
        "alpaca.portfolio.raw",
        sanitize_for_evidence(snapshot.portfolio),
        observed_at=snapshot.observed_at,
        source="alpaca.portfolio",
        metadata=metadata,
    )
