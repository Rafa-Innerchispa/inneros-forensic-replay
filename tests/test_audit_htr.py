import json
import socket
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inneros_forensic_replay import (
    AuditEnvelope,
    CounterfactualReplayer,
    DecisionEvidence,
    DeterministicReplayer,
    EvidenceBundleReader,
    EvidenceBundleWriter,
    EvidenceError,
    HTRRecord,
    RoutingEvidence,
    build_audit_envelope,
    summarize_htr,
    write_audit_jsonl,
)


class AuditHTRTests(unittest.TestCase):
    def test_measured_htr_requires_source_and_computes_returned_time(self) -> None:
        record = HTRRecord(
            task_id="ops-audit",
            measurement_mode="MEASURED",
            baseline_human_minutes=Decimal("120"),
            assisted_active_human_minutes=Decimal("35"),
            rework_human_minutes=Decimal("10"),
            interventions=2,
            handoffs=1,
            local_compute_seconds=Decimal("240"),
            cloud_compute_seconds=Decimal("0"),
            external_cost_usd=Decimal("0.00"),
            measurement_source="agent_activity_report:2026-09-08",
        )

        self.assertEqual(record.returned_human_minutes, Decimal("75"))
        self.assertEqual(record.quality_gate()["gate"], "measured")
        self.assertEqual(record.quality_gate()["confidence"], "high")

    def test_measured_htr_without_source_fails_closed(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "measurement_source"):
            HTRRecord(
                task_id="ops-measured",
                measurement_mode="MEASURED",
                baseline_human_minutes=60,
                assisted_active_human_minutes=15,
            )

    def test_estimated_htr_requires_reason(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "estimate_reason"):
            HTRRecord(
                task_id="ops-estimated",
                measurement_mode="ESTIMATED",
                baseline_human_minutes=60,
                assisted_active_human_minutes=15,
            )

    def test_negative_htr_return_is_flagged_for_review_not_hidden(self) -> None:
        record = HTRRecord(
            task_id="ops-rework",
            measurement_mode="ESTIMATED",
            baseline_human_minutes=10,
            assisted_active_human_minutes=15,
            rework_human_minutes=5,
            estimate_reason="rough post-incident estimate",
        )

        self.assertEqual(record.returned_human_minutes, Decimal("-10"))
        self.assertEqual(record.quality_gate()["gate"], "negative_return")

    def test_audit_envelope_references_manifest_without_copying_raw_payloads(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="audit-sdk-run")
            raw = {"payload": "sensitive raw data", "symbol": "AAPL"}
            writer.capture_json("alpaca.latest_trade.raw", raw, source="alpaca.latest_trade")
            writer.capture_json("model.output.raw", {"decision": "hold"}, source="local-model")
            manifest = writer.write_manifest(policy={"redaction": "source-store-only"})

            refs = {artifact.logical_name: artifact for artifact in manifest.artifacts}
            envelope = build_audit_envelope(
                manifest,
                decision=DecisionEvidence(
                    decision_id="decision-1",
                    model_ref="local-gemma:27b",
                    model_output_ref=None,
                    policy_ref="risk-policy-v1",
                    summary={"decision": "hold"},
                ),
                routing=RoutingEvidence(
                    selected_agent="audit-worker-1",
                    selected_model="local-gemma:27b",
                    route_reason="local-first audit lane",
                    queue_id="nats.audit",
                    worker_id="worker-a",
                ),
                htr=HTRRecord(
                    task_id="ops-audit",
                    measurement_mode="MEASURED",
                    baseline_human_minutes=30,
                    assisted_active_human_minutes=8,
                    measurement_source="timer-log",
                ),
                metadata={"artifact_count": len(refs)},
            )

            payload = envelope.to_dict()
            self.assertIsInstance(envelope, AuditEnvelope)
            self.assertEqual(payload["schema_version"], "inneros.audit_envelope.v1")
            self.assertEqual(payload["evidence_refs"][0]["logical_name"], "alpaca.latest_trade.raw")
            self.assertNotIn("sensitive raw data", json.dumps(payload))
            self.assertEqual(len(envelope.canonical_sha256()), 64)

    def test_htr_summary_keeps_measured_and_estimated_counts(self) -> None:
        measured = HTRRecord(
            task_id="ops-1",
            measurement_mode="MEASURED",
            baseline_human_minutes=100,
            assisted_active_human_minutes=20,
            measurement_source="timer",
            local_compute_seconds=10,
        )
        estimated = HTRRecord(
            task_id="ops-2",
            measurement_mode="ESTIMATED",
            baseline_human_minutes=50,
            assisted_active_human_minutes=10,
            estimate_reason="no timer for legacy run",
            cloud_compute_seconds=5,
            external_cost_usd="0.25",
        )

        summary = summarize_htr([measured, estimated]).to_dict()

        self.assertEqual(summary["measured_count"], 1)
        self.assertEqual(summary["estimated_count"], 1)
        self.assertEqual(summary["total_returned_human_minutes"], "120")
        self.assertEqual(summary["total_external_cost_usd"], "0.25")

    def test_jsonl_fallback_is_explicit(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path / "bundle", correlation_id="jsonl-run")
            writer.capture_json("input.raw", {"ok": True})
            manifest = writer.write_manifest()
            envelope = build_audit_envelope(
                manifest,
                decision=DecisionEvidence(decision_id="d1", model_ref="local"),
                routing=RoutingEvidence(selected_agent="codex", selected_model="local", route_reason="test"),
                htr=HTRRecord(
                    task_id="ops-jsonl",
                    measurement_mode="ESTIMATED",
                    baseline_human_minutes=5,
                    assisted_active_human_minutes=1,
                    estimate_reason="unit test",
                ),
            )

            result = write_audit_jsonl(tmp_path / "audit" / "records.jsonl", [envelope])

            self.assertEqual(result["format"], "jsonl")
            self.assertFalse(result["parquet_available"])
            self.assertEqual(result["count"], 1)
            self.assertTrue((tmp_path / "audit" / "records.jsonl").exists())

    def test_smoke_capture_verify_audit_htr_replay_and_counterfactual(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="smoke-run", run={"git_sha": "abc123"})
            writer.capture_json("input.market.raw", {"symbol": "AMD", "price": 165})
            writer.capture_json("model.output.raw", {"recommendation": "review"})
            manifest = writer.write_manifest(trace={"otel_trace_id": "trace-1"})

            decision = DecisionEvidence(decision_id="decision-smoke", model_ref="local-gemma:27b")
            routing = RoutingEvidence(
                selected_agent="audit-worker",
                selected_model="local-gemma:27b",
                route_reason="capacity available local-first",
                trace_refs=("trace-1",),
            )
            htr = HTRRecord(
                task_id="ops-smoke",
                measurement_mode="MEASURED",
                baseline_human_minutes=45,
                assisted_active_human_minutes=12,
                rework_human_minutes=3,
                measurement_source="manual stopwatch + task log",
            )
            envelope = build_audit_envelope(manifest, decision=decision, routing=routing, htr=htr)

            verified = EvidenceBundleReader(tmp_path).verify()
            replay_result = DeterministicReplayer(EvidenceBundleReader(tmp_path)).run_transform(
                lambda evidence, replay_manifest: {
                    "correlation_id": replay_manifest.correlation_id,
                    "symbol": evidence["input.market.raw"]["symbol"],
                    "audit_sha": envelope.canonical_sha256(),
                },
                required_artifacts=["input.market.raw"],
            )
            counterfactual = CounterfactualReplayer(EvidenceBundleReader(tmp_path)).run_counterfactual(
                lambda evidence, _manifest, cf: {"symbol": evidence["input.market.raw"]["symbol"], "policy": cf["policy"]},
                required_artifacts=["input.market.raw"],
                counterfactual={"label": "policy-v2-check", "policy": "risk-v2"},
            )

            self.assertEqual(verified.correlation_id, "smoke-run")
            self.assertEqual(replay_result["symbol"], "AMD")
            self.assertEqual(counterfactual["mode"], "counterfactual")
            self.assertEqual(counterfactual["result"]["policy"], "risk-v2")

    def test_audit_envelope_interop_schema_and_fixture_are_canonical_snake_case(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "audit_envelope_interop_schema.json").read_text())
        sample = json.loads((Path(__file__).resolve().parents[1] / "docs" / "sample_audit_envelope.json").read_text())

        self.assertEqual(schema["properties"]["schema_version"]["const"], "inneros.audit_envelope.v1")
        self.assertEqual(sample["schema_version"], "inneros.audit_envelope.v1")
        self.assertEqual(sample["manifest_schema_version"], "inneros.evidence_bundle.v1")
        self.assertRegex(sample["evidence_manifest_sha256"], r"^[a-f0-9]{64}$")
        self.assertIn("evidence_refs", sample)
        self.assertNotIn("evidenceRefs", sample)
        self.assertNotIn("raw_payload", json.dumps(sample))
        self.assertEqual(sample["htr"]["measurement_mode"], "MEASURED")
        self.assertEqual(sample["htr"]["measurement_source"], "synthetic timer fixture")

    def test_counterfactual_replay_blocks_network_and_requires_label(self) -> None:
        with self._tmpdir() as tmp_path:
            writer = EvidenceBundleWriter(tmp_path, correlation_id="cf-run")
            writer.capture_json("input.raw", {"ok": True})
            writer.write_manifest()
            replayer = CounterfactualReplayer(EvidenceBundleReader(tmp_path))

            with self.assertRaisesRegex(EvidenceError, "label"):
                replayer.run_counterfactual(lambda *_args: None, required_artifacts=["input.raw"], counterfactual={})

            def transform(_evidence, _manifest, _counterfactual):
                socket.create_connection(("example.com", 443), timeout=0.1)

            with self.assertRaises(Exception) as caught:
                replayer.run_counterfactual(
                    transform,
                    required_artifacts=["input.raw"],
                    counterfactual={"label": "network-check"},
                )
            self.assertEqual(type(caught.exception).__name__, "ReplayNetworkBlocked")

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
