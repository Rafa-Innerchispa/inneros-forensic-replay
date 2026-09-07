from __future__ import annotations

import json
from typing import Any, Iterable

from .bundle import ArtifactRecord, EvidenceBundleReader, EvidenceBundleWriter, sanitize_for_evidence


def optional_dataset_backends() -> dict[str, bool]:
    return {
        "pyarrow": _module_available("pyarrow"),
        "duckdb": _module_available("duckdb"),
    }


def capture_tabular_dataset(
    writer: EvidenceBundleWriter,
    logical_name: str,
    rows: Iterable[dict[str, Any]],
    *,
    observed_at: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactRecord:
    clean_rows = [sanitize_for_evidence(row) for row in rows]
    backends = optional_dataset_backends()
    meta = {
        "dataset_rows": len(clean_rows),
        "duckdb_available": backends["duckdb"],
        **sanitize_for_evidence(metadata or {}),
    }
    if backends["pyarrow"]:
        return _capture_parquet(writer, logical_name, clean_rows, observed_at=observed_at, source=source, metadata=meta)
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in clean_rows).encode("utf-8")
    if payload:
        payload += b"\n"
    return writer.capture_raw(
        logical_name,
        payload,
        media_type="application/x-ndjson",
        observed_at=observed_at,
        source=source,
        metadata={**meta, "storage_status": "fallback_jsonl", "parquet_available": False},
    )


def load_tabular_dataset(reader: EvidenceBundleReader, logical_name: str) -> list[dict[str, Any]]:
    record = reader.require([logical_name])[logical_name]
    payload = reader.artifact_bytes(record)
    if record.media_type == "application/x-parquet":
        return _load_parquet_bytes(payload)
    if record.media_type == "application/x-ndjson":
        return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    raise ValueError(f"unsupported dataset media type: {record.media_type}")


def _capture_parquet(
    writer: EvidenceBundleWriter,
    logical_name: str,
    rows: list[dict[str, Any]],
    *,
    observed_at: str | None,
    source: str | None,
    metadata: dict[str, Any],
) -> ArtifactRecord:
    import pyarrow as pa  # type: ignore[import-not-found]
    import pyarrow.parquet as pq  # type: ignore[import-not-found]

    table = pa.Table.from_pylist(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return writer.capture_raw(
        logical_name,
        sink.getvalue().to_pybytes(),
        media_type="application/x-parquet",
        observed_at=observed_at,
        source=source,
        metadata={**metadata, "storage_status": "parquet", "parquet_available": True},
    )


def _load_parquet_bytes(payload: bytes) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq  # type: ignore[import-not-found]

    import pyarrow as pa  # type: ignore[import-not-found]

    buffer = pa.py_buffer(payload)
    return pq.read_table(buffer).to_pylist()


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except Exception:
        return False
    return True
