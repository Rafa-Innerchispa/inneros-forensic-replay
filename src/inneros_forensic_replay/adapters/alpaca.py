from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inneros_forensic_replay.bundle import EvidenceBundleWriter


@dataclass(frozen=True)
class AlpacaCapture:
    latest_trade: dict[str, Any]
    bars: dict[str, Any]
    option_chain: dict[str, Any]
    portfolio: dict[str, Any]
    observed_at: str


def capture_alpaca_snapshot(writer: EvidenceBundleWriter, snapshot: AlpacaCapture) -> None:
    """Persist raw Alpaca evidence without importing an Alpaca API client."""

    writer.capture_json(
        "alpaca.latest_trade.raw",
        snapshot.latest_trade,
        observed_at=snapshot.observed_at,
        source="alpaca.latest_trade",
    )
    writer.capture_json(
        "alpaca.bars.raw",
        snapshot.bars,
        observed_at=snapshot.observed_at,
        source="alpaca.bars",
    )
    writer.capture_json(
        "alpaca.option_chain.raw",
        snapshot.option_chain,
        observed_at=snapshot.observed_at,
        source="alpaca.option_chain",
    )
    writer.capture_json(
        "alpaca.portfolio.raw",
        snapshot.portfolio,
        observed_at=snapshot.observed_at,
        source="alpaca.portfolio",
    )
