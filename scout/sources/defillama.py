from __future__ import annotations

from typing import Any

from scout.sources.http import fetch_json

SOURCE_NAME = "DefiLlama"
URL = "https://api.llama.fi/protocols"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    """Fetch protocols with 7 day TVL changes above 20%."""
    try:
        payload = fetch_json(URL, timeout=20)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    if not isinstance(payload, list):
        return [], f"{SOURCE_NAME} 数据源不可用：响应格式异常"

    items: list[dict[str, Any]] = []
    for protocol in payload:
        if not isinstance(protocol, dict):
            continue

        change_7d = _to_float(protocol.get("change_7d"))
        if change_7d is None or abs(change_7d) <= 20:
            continue

        tvl = _to_float(protocol.get("tvl"))
        chains = protocol.get("chains") or []
        if isinstance(chains, list):
            chain_text = ", ".join(str(chain) for chain in chains[:4])
        else:
            chain_text = str(chains)

        items.append(
            {
                "source": SOURCE_NAME,
                "title": str(protocol.get("name") or "Unknown protocol"),
                "evidence_grade": "A",
                "data": {
                    "protocol": protocol.get("name"),
                    "current_tvl": tvl,
                    "change_7d_pct": change_7d,
                    "chains": chain_text or "unknown",
                    "category": protocol.get("category") or "unknown",
                },
                "summary": (
                    f"{protocol.get('name') or 'Unknown protocol'} 当前 TVL "
                    f"{_format_usd(tvl)}，7日变化 {change_7d:.1f}%。"
                    f"所属链：{chain_text or 'unknown'}；类别："
                    f"{protocol.get('category') or 'unknown'}。"
                ),
            }
        )

    items.sort(key=lambda item: abs(item["data"]["change_7d_pct"]), reverse=True)
    return items, None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_usd(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"
