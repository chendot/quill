from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import config
from scout.sources.http import fetch_json

SOURCE_NAME = "FRED"
TIER = 3
URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES = {
    "FEDFUNDS": "Federal Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "DTWEXBGS": "Trade Weighted U.S. Dollar Index",
    "CPIAUCSL": "Consumer Price Index",
}


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    api_key = getattr(config, "FRED_API_KEY", "")
    if not api_key:
        return [], None

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for series_id, label in SERIES.items():
        item, error = _fetch_series(series_id, label, api_key)
        if item:
            items.append(item)
        if error:
            errors.append(error)

    return items, "; ".join(errors) if errors and not items else None


def _fetch_series(
    series_id: str,
    label: str,
    api_key: str,
) -> tuple[dict[str, Any] | None, str | None]:
    start = (date.today() - timedelta(days=45)).isoformat()
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    try:
        payload = fetch_json(URL, params=params, timeout=20)
    except Exception as exc:
        return None, f"{series_id}: {exc}"

    observations = (payload or {}).get("observations") or []
    values = [
        (obs.get("date"), _to_float(obs.get("value")))
        for obs in observations
        if isinstance(obs, dict)
    ]
    values = [(obs_date, value) for obs_date, value in values if value is not None]
    if not values:
        return None, f"{series_id}: 无有效观测值"

    latest_date, latest_value = values[-1]
    previous_value = values[0][1]
    change_30d = latest_value - previous_value
    return (
        {
            "source": SOURCE_NAME,
            "tier": TIER,
            "title": label,
            "evidence_grade": "A",
            "track": "Global Investing",
            "url": f"https://fred.stlouisfed.org/series/{series_id}",
            "published_at": latest_date,
            "data": {
                "series_id": series_id,
                "label": label,
                "latest_date": latest_date,
                "latest_value": latest_value,
                "change_30d": change_30d,
            },
            "summary": (
                f"{label} 最新值 {latest_value:.2f}，日期 {latest_date}，"
                f"约30日变化 {change_30d:+.2f}。"
            ),
        },
        None,
    )


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "."):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
