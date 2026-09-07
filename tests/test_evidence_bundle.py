import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inneros_forensic_replay import (
    AuditReplayer,
    DeterministicReplayer,
    EvidenceBundleReader,
    EvidenceBundleWriter,
    EvidenceError,
    MissingEvidenceError,
    ReplayNetworkBlocked,
)
from inneros_forensic_replay.adapters.alpaca import AlpacaCapture, capture_alpaca_snapshot


class EvidenceBundleTests(unittest.TestCase):
    def test_capture_raw_writes_content_addressed_manifest(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="trade-run-1", run={"model": "local-gemma"})
            record = writer.capture_json("input.market.raw", {"symbol": "AAPL", "price": 202.5}, source="test")
            manifest = writer.write_manifest(policy={"risk_policy": "v1"})

            self.assertEqual(manifest.schema_version, "inneros.evidence_bundle.v1")
            self.assertIn(record.sha256, record.relative_path)
            self.assertTrue((tmp_path / "manifest.json").exists())
            self.assertTrue((tmp_path / record.relative_path).exists())

            manifest_data = json.loads((tmp_path / "manifest.json").read_text())
            self.assertEqual(manifest_data["artifacts"][0]["logical_name"], "input.market.raw")
            self.assertEqual(manifest_data["artifacts"][0]["sha256"], record.sha256)

    def test_verify_fails_closed_when_artifact_is_missing(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="run-missing")
            record = writer.capture_raw("raw.response", b"original", media_type="text/plain")
            writer.write_manifest()
            (tmp_path / record.relative_path).unlink()

            with self.assertRaises(MissingEvidenceError):
                EvidenceBundleReader(tmp_path).verify()

    def test_verify_fails_closed_when_artifact_hash_changes(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="run-corrupt")
            record = writer.capture_raw("raw.response", b"original", media_type="text/plain")
            writer.write_manifest()
            (tmp_path / record.relative_path).write_bytes(b"mutated")

            with self.assertRaisesRegex(EvidenceError, "hash mismatch"):
                EvidenceBundleReader(tmp_path).verify()

    def test_audit_replay_never_requires_network(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="audit-run")
            writer.capture_json("input.market.raw", {"symbol": "MSFT", "price": 411.0})
            writer.write_manifest()

            result = AuditReplayer(EvidenceBundleReader(tmp_path)).load(required_artifacts=["input.market.raw"])

            self.assertEqual(result["artifacts"]["input.market.raw"]["symbol"], "MSFT")

    def test_deterministic_replay_blocks_network_access(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="deterministic-run")
            writer.capture_json("input.market.raw", {"symbol": "NVDA"})
            writer.write_manifest()

            def transform(_evidence, _manifest):
                socket.create_connection(("example.com", 443), timeout=0.1)

            with self.assertRaises(ReplayNetworkBlocked):
                DeterministicReplayer(EvidenceBundleReader(tmp_path)).run_transform(
                    transform,
                    required_artifacts=["input.market.raw"],
                )

    def test_deterministic_replay_returns_transform_result(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="deterministic-pass")
            writer.capture_json("input.market.raw", {"symbol": "AMD", "price": 165})
            writer.write_manifest()

            def transform(evidence, manifest):
                return {
                    "correlation_id": manifest.correlation_id,
                    "symbol": evidence["input.market.raw"]["symbol"],
                    "decision": "audit-only",
                }

            self.assertEqual(
                DeterministicReplayer(EvidenceBundleReader(tmp_path)).run_transform(
                    transform,
                    required_artifacts=["input.market.raw"],
                ),
                {"correlation_id": "deterministic-pass", "symbol": "AMD", "decision": "audit-only"},
            )

    def test_missing_required_artifact_fails_closed(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="required-run")
            writer.capture_json("input.market.raw", {"symbol": "SPY"})
            writer.write_manifest()

            with self.assertRaisesRegex(MissingEvidenceError, "input.portfolio.raw"):
                AuditReplayer(EvidenceBundleReader(tmp_path)).load(
                    required_artifacts=["input.market.raw", "input.portfolio.raw"]
                )

    def test_alpaca_adapter_captures_required_raw_inputs(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="alpaca-run")
            capture_alpaca_snapshot(
                writer,
                AlpacaCapture(
                    latest_trade={"symbol": "AAPL", "price": 202.5},
                    bars={"symbol": "AAPL", "bars": [{"close": 201.1}]},
                    option_chain={"symbol": "AAPL", "contracts": []},
                    portfolio={"cash": "1000.00", "positions": []},
                    observed_at="2026-09-06T18:00:00Z",
                ),
            )
            writer.write_manifest()

            names = set(EvidenceBundleReader(tmp_path).artifacts_by_name())
            self.assertEqual(
                names,
                {
                    "alpaca.latest_trade.raw",
                    "alpaca.bars.raw",
                    "alpaca.option_chain.raw",
                    "alpaca.portfolio.raw",
                },
            )

    def test_repository_sample_manifest_verifies(self) -> None:
        sample_bundle = Path(__file__).resolve().parents[1] / "docs" / "sample_bundle"
        manifest = EvidenceBundleReader(sample_bundle).verify()
        self.assertEqual(manifest.correlation_id, "sample-alpaca-run")
        self.assertEqual(manifest.artifacts[0].logical_name, "alpaca.latest_trade.raw")

    @staticmethod
    def _tmpdir():
        import tempfile

        class TempPath:
            def __enter__(self):
                self._ctx = tempfile.TemporaryDirectory()
                return Path(self._ctx.__enter__())

            def __exit__(self, exc_type, exc, tb):
                return self._ctx.__exit__(exc_type, exc, tb)

        return TempPath()


if __name__ == "__main__":
    unittest.main()
