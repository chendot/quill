from __future__ import annotations

from typing import Any

SOURCE_NAME = "Google Trends"
TIER = 4
KEYWORDS = ["Bitcoin", "AI agent", "gold", "interest rate", "DeFi"]


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    try:
        from pytrends.request import TrendReq
    except ModuleNotFoundError:
        return [], f"{SOURCE_NAME} 数据源不可用：未安装 pytrends"

    try:
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
        pytrends.build_payload(KEYWORDS, timeframe="now 7-d")
        interest = pytrends.interest_over_time()
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    if interest is None or interest.empty:
        return [], f"{SOURCE_NAME} 数据源不可用：无趋势数据"

    items: list[dict[str, Any]] = []
    for keyword in KEYWORDS:
        if keyword not in interest:
            continue
        series = interest[keyword].dropna()
        if series.empty:
            continue
        latest = float(series.iloc[-1])
        first = float(series.iloc[0])
        change_7d = latest - first
        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": keyword,
                "evidence_grade": "B",
                "track": _infer_track(keyword),
                "url": "https://trends.google.com/trends/",
                "published_at": "",
                "data": {
                    "keyword": keyword,
                    "latest_score": latest,
                    "change_7d": change_7d,
                },
                "summary": (
                    f"{keyword} 过去7天 Google Trends 最新分数 {latest:.0f}，"
                    f"7日变化 {change_7d:+.0f}。"
                ),
            }
        )
    return items, None


def _infer_track(keyword: str) -> str:
    lowered = keyword.lower()
    if "ai" in lowered or "agent" in lowered:
        return "AI×Productivity"
    if "bitcoin" in lowered or "defi" in lowered:
        return "Crypto Research"
    return "Global Investing"
