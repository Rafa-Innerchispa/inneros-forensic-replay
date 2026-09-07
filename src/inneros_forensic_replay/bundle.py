from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "inneros.evidence_bundle.v1"


class EvidenceError(RuntimeError):
    """Base error for evidence bundle failures."""


class MissingEvidenceError(EvidenceError):
    """Raised when replay evidence is missing or incomplete."""


class ReplayNetworkBlocked(EvidenceError):
    """Raised when replay code tries to reach the network."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ArtifactRecord:
    logical_name: str
    sha256: str
    relative_path: str
    media_type: str
    size_bytes: int
    observed_at: str | None = None
    captured_at: str = field(default_factory=utc_now_iso)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

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
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        return cls(
            logical_name=str(data["logical_name"]),
            sha256=str(data["sha256"]),
            relative_path=str(data["relative_path"]),
            media_type=str(data["media_type"]),
            size_bytes=int(data["size_bytes"]),
            observed_at=data.get("observed_at"),
            captured_at=str(data["captured_at"]),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EvidenceManifest:
    correlation_id: str
    artifacts: tuple[ArtifactRecord, ...]
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now_iso)
    run: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "run": self.run,
            "policy": self.policy,
            "trace": self.trace,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceManifest":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise EvidenceError(f"unsupported evidence schema: {data.get('schema_version')!r}")
        return cls(
            correlation_id=str(data["correlation_id"]),
            created_at=str(data["created_at"]),
            run=dict(data.get("run") or {}),
            policy=dict(data.get("policy") or {}),
            trace=dict(data.get("trace") or {}),
            artifacts=tuple(ArtifactRecord.from_dict(item) for item in data.get("artifacts") or ()),
        )


class EvidenceBundleWriter:
    def __init__(self, bundle_dir: Path | str, *, correlation_id: str, run: dict[str, Any] | None = None):
        self.bundle_dir = Path(bundle_dir)
        self.correlation_id = correlation_id
        self.run = dict(run or {})
        self._artifacts: list[ArtifactRecord] = []

    def capture_raw(
        self,
        logical_name: str,
        payload: bytes,
        *,
        media_type: str = "application/octet-stream",
        observed_at: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        digest = sha256_bytes(payload)
        relative_path = Path("artifacts") / "sha256" / digest[:2] / f"{digest}{self._extension_for(media_type)}"
        artifact_path = self.bundle_dir / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        if artifact_path.exists() and artifact_path.read_bytes() != payload:
            raise EvidenceError(f"hash collision or corrupted artifact path: {artifact_path}")

        artifact_path.write_bytes(payload)
        record = ArtifactRecord(
            logical_name=logical_name,
            sha256=digest,
            relative_path=relative_path.as_posix(),
            media_type=media_type,
            size_bytes=len(payload),
            observed_at=observed_at,
            source=source,
            metadata=dict(metadata or {}),
        )
        self._artifacts.append(record)
        return record

    def capture_json(
        self,
        logical_name: str,
        value: Any,
        *,
        observed_at: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        return self.capture_raw(
            logical_name,
            canonical_json_bytes(value),
            media_type="application/json",
            observed_at=observed_at,
            source=source,
            metadata=metadata,
        )

    def write_manifest(
        self,
        *,
        policy: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> EvidenceManifest:
        manifest = EvidenceManifest(
            correlation_id=self.correlation_id,
            run=self.run,
            policy=dict(policy or {}),
            trace=dict(trace or {}),
            artifacts=tuple(self._artifacts),
        )
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        (self.bundle_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest.to_dict()))
        return manifest

    @staticmethod
    def _extension_for(media_type: str) -> str:
        if media_type == "application/json":
            return ".json"
        if media_type.startswith("text/"):
            return ".txt"
        return ".bin"


class EvidenceBundleReader:
    def __init__(self, bundle_dir: Path | str):
        self.bundle_dir = Path(bundle_dir)

    def load_manifest(self) -> EvidenceManifest:
        manifest_path = self.bundle_dir / "manifest.json"
        if not manifest_path.exists():
            raise MissingEvidenceError(f"missing evidence manifest: {manifest_path}")
        return EvidenceManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))

    def artifact_bytes(self, artifact: ArtifactRecord) -> bytes:
        path = self._artifact_path(artifact)
        if not path.exists():
            raise MissingEvidenceError(f"missing evidence artifact: {artifact.logical_name}")
        payload = path.read_bytes()
        observed_digest = sha256_bytes(payload)
        if observed_digest != artifact.sha256:
            raise EvidenceError(
                f"artifact hash mismatch for {artifact.logical_name}: expected {artifact.sha256}, got {observed_digest}"
            )
        return payload

    def artifact_json(self, artifact: ArtifactRecord) -> Any:
        if artifact.media_type != "application/json":
            raise EvidenceError(f"artifact is not JSON: {artifact.logical_name}")
        return json.loads(self.artifact_bytes(artifact).decode("utf-8"))

    def artifacts_by_name(self) -> dict[str, ArtifactRecord]:
        return {artifact.logical_name: artifact for artifact in self.load_manifest().artifacts}

    def require(self, logical_names: Iterable[str]) -> dict[str, ArtifactRecord]:
        by_name = self.artifacts_by_name()
        missing = [name for name in logical_names if name not in by_name]
        if missing:
            raise MissingEvidenceError(f"missing required evidence: {', '.join(missing)}")
        return {name: by_name[name] for name in logical_names}

    def verify(self) -> EvidenceManifest:
        manifest = self.load_manifest()
        for artifact in manifest.artifacts:
            self.artifact_bytes(artifact)
        return manifest

    def _artifact_path(self, artifact: ArtifactRecord) -> Path:
        path = (self.bundle_dir / artifact.relative_path).resolve()
        root = self.bundle_dir.resolve()
        if os.path.commonpath([str(path), str(root)]) != str(root):
            raise EvidenceError(f"artifact path escapes bundle: {artifact.relative_path}")
        return path
