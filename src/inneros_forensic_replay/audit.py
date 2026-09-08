from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Literal

from .bundle import ArtifactRecord, EvidenceError, EvidenceManifest, canonical_json_bytes, sha256_bytes, utc_now_iso

MeasurementMode = Literal["MEASURED", "ESTIMATED"]
ReplayMode = Literal["audit", "deterministic", "counterfactual"]

AUDIT_SCHEMA_VERSION = "inneros.audit_envelope.v1"
HTR_SCHEMA_VERSION = "inneros.htr_record.v1"


@dataclass(frozen=True)
class SourceRef:
    """Pointer to immutable evidence without copying the raw payload."""

    logical_name: str
    sha256: str
    relative_path: str
    media_type: str
    size_bytes: int
    observed_at: str | None = None
    captured_at: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "sha256": self.sha256,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "observed_at": self.observed_at,
            "captured_at": self.captured_at,
            "source": self.source,
        }

    @classmethod
    def from_artifact(cls, artifact: ArtifactRecord) -> "SourceRef":
        return cls(
            logical_name=artifact.logical_name,
            sha256=artifact.sha256,
            relative_path=artifact.relative_path,
            media_type=artifact.media_type,
            size_bytes=artifact.size_bytes,
            observed_at=artifact.observed_at,
            captured_at=artifact.captured_at,
            source=artifact.source,
        )


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    model_ref: str
    model_output_ref: SourceRef | None = None
    normalized_decision_ref: SourceRef | None = None
    policy_ref: str | None = None
    action_refs: tuple[SourceRef, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "model_ref": self.model_ref,
            "model_output_ref": self.model_output_ref.to_dict() if self.model_output_ref else None,
            "normalized_decision_ref": self.normalized_decision_ref.to_dict()
            if self.normalized_decision_ref
            else None,
            "policy_ref": self.policy_ref,
            "action_refs": [item.to_dict() for item in self.action_refs],
            "summary": self.summary,
        }


@dataclass(frozen=True)
class RoutingEvidence:
    selected_agent: str
    selected_model: str
    route_reason: str
    queue_id: str | None = None
    worker_id: str | None = None
    local_seconds: Decimal | None = None
    cloud_seconds: Decimal | None = None
    cost_usd: Decimal | None = None
    trace_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_agent": self.selected_agent,
            "selected_model": self.selected_model,
            "route_reason": self.route_reason,
            "queue_id": self.queue_id,
            "worker_id": self.worker_id,
            "local_seconds": decimal_to_str(self.local_seconds),
            "cloud_seconds": decimal_to_str(self.cloud_seconds),
            "cost_usd": decimal_to_str(self.cost_usd),
            "trace_refs": list(self.trace_refs),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class HTRRecord:
    """Human Time Return record with explicit measurement quality."""

    task_id: str
    measurement_mode: MeasurementMode
    baseline_human_minutes: Decimal
    assisted_active_human_minutes: Decimal
    rework_human_minutes: Decimal = Decimal("0")
    returned_human_minutes: Decimal | None = None
    interventions: int = 0
    handoffs: int = 0
    local_compute_seconds: Decimal | None = None
    cloud_compute_seconds: Decimal | None = None
    external_cost_usd: Decimal | None = None
    measurement_source: str | None = None
    estimate_reason: str | None = None
    quality_notes: str | None = None
    schema_version: str = HTR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        baseline = as_decimal(self.baseline_human_minutes)
        assisted = as_decimal(self.assisted_active_human_minutes)
        rework = as_decimal(self.rework_human_minutes)
        returned = baseline - assisted - rework if self.returned_human_minutes is None else as_decimal(
            self.returned_human_minutes
        )

        object.__setattr__(self, "baseline_human_minutes", baseline)
        object.__setattr__(self, "assisted_active_human_minutes", assisted)
        object.__setattr__(self, "rework_human_minutes", rework)
        object.__setattr__(self, "returned_human_minutes", returned)
        object.__setattr__(self, "local_compute_seconds", optional_decimal(self.local_compute_seconds))
        object.__setattr__(self, "cloud_compute_seconds", optional_decimal(self.cloud_compute_seconds))
        object.__setattr__(self, "external_cost_usd", optional_decimal(self.external_cost_usd))
        self.validate()

    def validate(self) -> None:
        if self.measurement_mode not in ("MEASURED", "ESTIMATED"):
            raise EvidenceError(f"unsupported HTR measurement mode: {self.measurement_mode!r}")
        if self.measurement_mode == "MEASURED" and not self.measurement_source:
            raise EvidenceError("MEASURED HTR requires measurement_source")
        if self.measurement_mode == "ESTIMATED" and not self.estimate_reason:
            raise EvidenceError("ESTIMATED HTR requires estimate_reason")
        for name in ("baseline_human_minutes", "assisted_active_human_minutes", "rework_human_minutes"):
            if getattr(self, name) < 0:
                raise EvidenceError(f"HTR field must be non-negative: {name}")
        if self.interventions < 0 or self.handoffs < 0:
            raise EvidenceError("HTR interventions and handoffs must be non-negative")
        for name in ("local_compute_seconds", "cloud_compute_seconds", "external_cost_usd"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise EvidenceError(f"HTR field must be non-negative: {name}")

    def quality_gate(self) -> dict[str, Any]:
        gate = "measured" if self.measurement_mode == "MEASURED" else "estimated"
        confidence = "high" if self.measurement_mode == "MEASURED" else "medium"
        if self.returned_human_minutes is not None and self.returned_human_minutes < 0:
            gate = "negative_return"
            confidence = "needs_review"
        return {
            "gate": gate,
            "confidence": confidence,
            "measurement_mode": self.measurement_mode,
            "source": self.measurement_source,
            "estimate_reason": self.estimate_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "measurement_mode": self.measurement_mode,
            "baseline_human_minutes": decimal_to_str(self.baseline_human_minutes),
            "assisted_active_human_minutes": decimal_to_str(self.assisted_active_human_minutes),
            "rework_human_minutes": decimal_to_str(self.rework_human_minutes),
            "returned_human_minutes": decimal_to_str(self.returned_human_minutes),
            "interventions": self.interventions,
            "handoffs": self.handoffs,
            "local_compute_seconds": decimal_to_str(self.local_compute_seconds),
            "cloud_compute_seconds": decimal_to_str(self.cloud_compute_seconds),
            "external_cost_usd": decimal_to_str(self.external_cost_usd),
            "measurement_source": self.measurement_source,
            "estimate_reason": self.estimate_reason,
            "quality_notes": self.quality_notes,
            "quality_gate": self.quality_gate(),
        }


@dataclass(frozen=True)
class HTRSummary:
    total_baseline_human_minutes: Decimal
    total_assisted_active_human_minutes: Decimal
    total_rework_human_minutes: Decimal
    total_returned_human_minutes: Decimal
    measured_count: int
    estimated_count: int
    total_interventions: int
    total_handoffs: int
    total_local_compute_seconds: Decimal
    total_cloud_compute_seconds: Decimal
    total_external_cost_usd: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_baseline_human_minutes": decimal_to_str(self.total_baseline_human_minutes),
            "total_assisted_active_human_minutes": decimal_to_str(self.total_assisted_active_human_minutes),
            "total_rework_human_minutes": decimal_to_str(self.total_rework_human_minutes),
            "total_returned_human_minutes": decimal_to_str(self.total_returned_human_minutes),
            "measured_count": self.measured_count,
            "estimated_count": self.estimated_count,
            "total_interventions": self.total_interventions,
            "total_handoffs": self.total_handoffs,
            "total_local_compute_seconds": decimal_to_str(self.total_local_compute_seconds),
            "total_cloud_compute_seconds": decimal_to_str(self.total_cloud_compute_seconds),
            "total_external_cost_usd": decimal_to_str(self.total_external_cost_usd),
        }


@dataclass(frozen=True)
class AuditEnvelope:
    correlation_id: str
    manifest_schema_version: str
    evidence_manifest_sha256: str
    evidence_refs: tuple[SourceRef, ...]
    decision: DecisionEvidence
    routing: RoutingEvidence
    htr: HTRRecord
    replay_mode: ReplayMode = "audit"
    created_at: str = field(default_factory=utc_now_iso)
    schema_version: str = AUDIT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "manifest_schema_version": self.manifest_schema_version,
            "evidence_manifest_sha256": self.evidence_manifest_sha256,
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "decision": self.decision.to_dict(),
            "routing": self.routing.to_dict(),
            "htr": self.htr.to_dict(),
            "replay_mode": self.replay_mode,
            "metadata": self.metadata,
        }

    def canonical_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))


def build_audit_envelope(
    manifest: EvidenceManifest,
    *,
    decision: DecisionEvidence,
    routing: RoutingEvidence,
    htr: HTRRecord,
    replay_mode: ReplayMode = "audit",
    metadata: dict[str, Any] | None = None,
) -> AuditEnvelope:
    if replay_mode not in ("audit", "deterministic", "counterfactual"):
        raise EvidenceError(f"unsupported replay mode: {replay_mode!r}")
    refs = tuple(SourceRef.from_artifact(artifact) for artifact in manifest.artifacts)
    return AuditEnvelope(
        correlation_id=manifest.correlation_id,
        manifest_schema_version=manifest.schema_version,
        evidence_manifest_sha256=sha256_bytes(canonical_json_bytes(manifest.to_dict())),
        evidence_refs=refs,
        decision=decision,
        routing=routing,
        htr=htr,
        replay_mode=replay_mode,
        metadata=dict(metadata or {}),
    )


def summarize_htr(records: Iterable[HTRRecord]) -> HTRSummary:
    items = list(records)
    return HTRSummary(
        total_baseline_human_minutes=sum_decimal(item.baseline_human_minutes for item in items),
        total_assisted_active_human_minutes=sum_decimal(item.assisted_active_human_minutes for item in items),
        total_rework_human_minutes=sum_decimal(item.rework_human_minutes for item in items),
        total_returned_human_minutes=sum_decimal(item.returned_human_minutes or Decimal("0") for item in items),
        measured_count=sum(1 for item in items if item.measurement_mode == "MEASURED"),
        estimated_count=sum(1 for item in items if item.measurement_mode == "ESTIMATED"),
        total_interventions=sum(item.interventions for item in items),
        total_handoffs=sum(item.handoffs for item in items),
        total_local_compute_seconds=sum_decimal(item.local_compute_seconds or Decimal("0") for item in items),
        total_cloud_compute_seconds=sum_decimal(item.cloud_compute_seconds or Decimal("0") for item in items),
        total_external_cost_usd=sum_decimal(item.external_cost_usd or Decimal("0") for item in items),
    )


def write_audit_jsonl(path: Path | str, envelopes: Iterable[AuditEnvelope]) -> dict[str, Any]:
    """Write JSONL fallback explicitly; callers may layer Parquet when available."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8") as handle:
        for envelope in envelopes:
            handle.write(json.dumps(envelope.to_dict(), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            count += 1
    return {
        "format": "jsonl",
        "parquet_available": False,
        "count": count,
        "path": str(target),
        "note": "JSONL fallback selected; no parquet runtime dependency is required by this package.",
    }


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def optional_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    return as_decimal(value)


def sum_decimal(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
