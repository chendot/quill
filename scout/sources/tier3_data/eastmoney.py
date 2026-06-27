from __future__ import annotations

from typing import Any

from scout.sources.http import fetch_json

SOURCE_NAME = "Eastmoney"
TIER = 3
PRIMARY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
FALLBACK_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    """Fetch top sector main capital inflows and outflows from Eastmoney."""
    params = {
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f62,f184",
        "pn": "1",
        "pz": "200",
        "po": "1",
        "np": "1",
        "fid": "f62",
    }
    try:
        payload = fetch_json(PRIMARY_URL, params=params, timeout=20)
        rows = (((payload or {}).get("data") or {}).get("diff") or [])
        if not rows:
            payload = fetch_json(FALLBACK_URL, params=params, timeout=20)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    rows = (((payload or {}).get("data") or {}).get("diff") or [])
    if not isinstance(rows, list):
        return [], f"{SOURCE_NAME} 数据源不可用：响应格式异常"
    if not rows:
        return [], f"{SOURCE_NAME} 数据源不可用：未返回可用板块资金流"

    parsed = [_parse_row(row) for row in rows if isinstance(row, dict)]
    parsed = [row for row in parsed if row is not None]
    inflows = sorted(parsed, key=lambda row: row["main_net_inflow"], reverse=True)[:5]
    outflows = sorted(parsed, key=lambda row: row["main_net_inflow"])[:5]

    items: list[dict[str, Any]] = []
    for row in inflows + outflows:
        direction = "净流入" if row["main_net_inflow"] >= 0 else "净流出"
        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": f"{row['sector_name']} 主力资金{direction}",
                "evidence_grade": "A",
                "track": "Global Investing",
                "url": "https://quote.eastmoney.com/center/boardlist.html",
                "published_at": "",
                "data": row,
                "summary": (
                    f"{row['sector_name']} 当日涨跌幅 {row['change_pct']:.2f}%，"
                    f"主力资金{direction} {_format_cny(abs(row['main_net_inflow']))}。"
                ),
            }
        )

    return items, None


def _parse_row(row: dict[str, Any]) -> dict[str, Any] | None:
    name = row.get("f14")
    flow = _to_float(row.get("f62"))
    change = _to_float(row.get("f3"))
    if not name or flow is None or change is None:
        return None
    return {
        "sector_code": row.get("f12"),
        "sector_name": str(name),
        "change_pct": change,
        "main_net_inflow": flow,
        "main_net_inflow_ratio": _to_float(row.get("f184")),
    }


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_cny(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿元"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万元"
    return f"{value:.2f}元"
