from __future__ import annotations

import socket
import urllib.request
from contextlib import contextmanager
from typing import Any, Callable

from .bundle import EvidenceBundleReader, EvidenceManifest, ReplayNetworkBlocked


class AuditReplayer:
    """Loads preserved evidence without contacting external systems."""

    def __init__(self, reader: EvidenceBundleReader):
        self.reader = reader

    def load(self, *, required_artifacts: list[str] | None = None) -> dict[str, Any]:
        manifest = self.reader.verify()
        if required_artifacts:
            self.reader.require(required_artifacts)
        return {
            "manifest": manifest.to_dict(),
            "artifacts": {
                artifact.logical_name: self.reader.artifact_json(artifact)
                if artifact.media_type == "application/json"
                else self.reader.artifact_bytes(artifact)
                for artifact in manifest.artifacts
            },
        }


class DeterministicReplayer:
    """Runs deterministic transforms against verified historical evidence."""

    def __init__(self, reader: EvidenceBundleReader):
        self.reader = reader

    def run_transform(
        self,
        transform: Callable[[dict[str, Any], EvidenceManifest], Any],
        *,
        required_artifacts: list[str],
    ) -> Any:
        manifest = self.reader.verify()
        required = self.reader.require(required_artifacts)
        evidence = {
            name: self.reader.artifact_json(record)
            if record.media_type == "application/json"
            else self.reader.artifact_bytes(record)
            for name, record in required.items()
        }
        with network_disabled():
            return transform(evidence, manifest)


@contextmanager
def network_disabled():
    original_create_connection = socket.create_connection
    original_socket_connect = socket.socket.connect
    original_urlopen = urllib.request.urlopen

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise ReplayNetworkBlocked("network access is disabled during forensic replay")

    try:
        socket.create_connection = blocked  # type: ignore[assignment]
        socket.socket.connect = blocked  # type: ignore[assignment]
        urllib.request.urlopen = blocked  # type: ignore[assignment]
        yield
    finally:
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        socket.socket.connect = original_socket_connect  # type: ignore[assignment]
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
