from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ARCHIVE_DIR = Path("scout/scout_runs")
SCHEMA_VERSION = 1


def write_raw_snapshot(
    raw_items: list[dict[str, Any]],
    source_names: list[str],
    source_status: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> Path:
    generated_at = generated_at or datetime.now()
    snapshot = build_raw_snapshot(raw_items, source_names, source_status, generated_at)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{generated_at.strftime('%Y%m%d_%H%M')}_raw.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def build_raw_snapshot(
    raw_items: list[dict[str, Any]],
    source_names: list[str],
    source_status: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    normalized_items = [_normalize_raw_item(item) for item in raw_items]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "selected_sources": source_names,
        "source_status": source_status,
        "raw_item_count": len(normalized_items),
        "raw_items": normalized_items,
    }


def load_raw_snapshot(path: str | Path) -> dict[str, Any]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Raw snapshot not found: {snapshot_path}")

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError(f"Raw snapshot must be a JSON object: {snapshot_path}")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported raw snapshot schema_version: {snapshot.get('schema_version')}"
        )
    if not isinstance(snapshot.get("raw_items"), list):
        raise ValueError(f"Raw snapshot missing raw_items array: {snapshot_path}")
    return snapshot


def snapshot_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [_normalize_raw_item(item) for item in snapshot.get("raw_items", [])]


def snapshot_source_names(snapshot: dict[str, Any]) -> list[str]:
    return [
        str(source)
        for source in snapshot.get("selected_sources", [])
        if str(source).strip()
    ]


def snapshot_source_errors(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for status in snapshot.get("source_status", []):
        if not isinstance(status, dict):
            continue
        raw_status = status.get("status")
        if raw_status is None and status.get("ok"):
            continue
        if raw_status == "ok":
            continue
        source = status.get("source", "unknown")
        error = status.get("error") or raw_status or "unknown error"
        errors.append(f"{source} 数据源不可用：{error}")
    return errors


def snapshot_generated_at(snapshot: dict[str, Any]) -> datetime:
    raw_value = str(snapshot.get("generated_at") or "")
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw_value, date_format)
        except ValueError:
            continue
    raise ValueError(f"Raw snapshot has invalid generated_at: {raw_value}")


def _normalize_raw_item(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    if not isinstance(data, dict):
        data = {}
    return {
        "title": str(item.get("title") or item.get("topic_title") or "Untitled"),
        "summary": str(item.get("summary") or item.get("data_summary") or ""),
        "data": data,
        "url": str(item.get("url") or item.get("link") or ""),
        "published_at": str(item.get("published_at") or ""),
        "source": str(item.get("source") or "unknown"),
        "tier": item.get("tier"),
        "track": str(item.get("track") or "unknown"),
        "evidence_grade": str(item.get("evidence_grade") or "unknown"),
    }
