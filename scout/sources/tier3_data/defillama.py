from __future__ import annotations

from typing import Any

import config
from scout.sources.http import fetch_json

SOURCE_NAME = "DefiLlama"
TIER = 3
URL = "https://api.llama.fi/protocols"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    """Fetch high-signal protocols after source-level TVL and category filters."""
    try:
        payload = fetch_json(URL, timeout=20)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    if not isinstance(payload, list):
        return [], f"{SOURCE_NAME} 数据源不可用：响应格式异常"

    min_tvl = float(getattr(config, "SCOUT_DEFILLAMA_MIN_TVL_USD", 1_000_000))
    min_abs_change = float(getattr(config, "SCOUT_DEFILLAMA_MIN_ABS_CHANGE_7D", 35))
    max_items = int(getattr(config, "SCOUT_DEFILLAMA_MAX_ITEMS", 45))
    allowlist = {
        _normalize_category(category)
        for category in getattr(config, "SCOUT_DEFILLAMA_CATEGORY_ALLOWLIST", ())
    }

    items: list[dict[str, Any]] = []
    for protocol in payload:
        if not isinstance(protocol, dict):
            continue

        change_7d = _to_float(protocol.get("change_7d"))
        if change_7d is None or abs(change_7d) < min_abs_change:
            continue

        tvl = _to_float(protocol.get("tvl"))
        if tvl is None or tvl < min_tvl:
            continue

        category = str(protocol.get("category") or "unknown")
        if allowlist and _normalize_category(category) not in allowlist:
            continue

        chains = protocol.get("chains") or []
        if isinstance(chains, list):
            chain_text = ", ".join(str(chain) for chain in chains[:4])
        else:
            chain_text = str(chains)

        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": str(protocol.get("name") or "Unknown protocol"),
                "evidence_grade": "A",
                "track": "Crypto Research",
                "url": f"https://defillama.com/protocol/{protocol.get('slug') or ''}",
                "published_at": "",
                "data": {
                    "protocol": protocol.get("name"),
                    "current_tvl": tvl,
                    "change_7d": change_7d,
                    "change_7d_pct": change_7d,
                    "chains": chain_text or "unknown",
                    "category": category,
                },
                "summary": (
                    f"{protocol.get('name') or 'Unknown protocol'} 当前 TVL "
                    f"{_format_usd(tvl)}，7日变化 {change_7d:.1f}%。"
                    f"所属链：{chain_text or 'unknown'}；类别："
                    f"{category}。"
                ),
            }
        )

    items.sort(key=_signal_score, reverse=True)
    return items[:max_items], None


def _signal_score(item: dict[str, Any]) -> float:
    data = item.get("data") or {}
    tvl = _to_float(data.get("current_tvl")) or 0
    change = abs(_to_float(data.get("change_7d")) or 0)
    if tvl >= 100_000_000:
        tvl_score = 3.0
    elif tvl >= 10_000_000:
        tvl_score = 2.0
    else:
        tvl_score = 1.0
    return change + tvl_score * 20


def _normalize_category(value: str) -> str:
    normalized = value.strip().lower().replace("-", " ")
    aliases = {
        "dexs": "dex",
        "dex": "dex",
        "yield": "yield aggregator",
        "yield aggregator": "yield aggregator",
        "prediction markets": "prediction market",
    }
    return aliases.get(normalized, normalized)


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
