from __future__ import annotations

import json
from typing import Any

from scout.sources.http import fetch_json

SOURCE_NAME = "Polymarket"
URL = "https://gamma-api.polymarket.com/markets"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    """Fetch high volume markets where probability is not an extreme consensus."""
    params = {"limit": 20, "order": "volume", "ascending": "false"}
    try:
        payload = fetch_json(URL, params=params, timeout=20)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    markets = payload if isinstance(payload, list) else (payload or {}).get("markets")
    if not isinstance(markets, list):
        return [], f"{SOURCE_NAME} 数据源不可用：响应格式异常"

    items: list[dict[str, Any]] = []
    for market in markets:
        if not isinstance(market, dict):
            continue

        probability = _current_probability(market)
        if probability is None or not 0.15 <= probability <= 0.85:
            continue

        change_24h = _first_float(
            market,
            ("oneDayPriceChange", "priceChange24hr", "priceChange24h"),
        )
        volume = _first_float(market, ("volume", "volume24hr", "volumeNum"))
        question = str(market.get("question") or market.get("title") or "Untitled market")

        items.append(
            {
                "source": SOURCE_NAME,
                "title": question,
                "evidence_grade": "B",
                "data": {
                    "market": question,
                    "current_probability": probability,
                    "probability_change_24h": change_24h,
                    "volume": volume,
                },
                "summary": (
                    f"{question} 当前隐含概率 {probability * 100:.1f}%。"
                    f"24小时概率变化：{_format_probability_change(change_24h)}；"
                    f"成交量：{_format_usd(volume)}。"
                ),
            }
        )

    return items, None


def _current_probability(market: dict[str, Any]) -> float | None:
    direct = _first_float(market, ("lastTradePrice", "bestAsk", "bestBid"))
    if direct is not None and 0 <= direct <= 1:
        return direct

    prices = _parse_maybe_json(market.get("outcomePrices"))
    outcomes = _parse_maybe_json(market.get("outcomes"))
    if isinstance(prices, list):
        numeric_prices = [_to_float(price) for price in prices]
        numeric_prices = [price for price in numeric_prices if price is not None]
        if not numeric_prices:
            return None
        if isinstance(outcomes, list):
            for outcome, price in zip(outcomes, numeric_prices):
                if str(outcome).lower() == "yes" and 0 <= price <= 1:
                    return price
        first = numeric_prices[0]
        if 0 <= first <= 1:
            return first
    return None


def _parse_maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _first_float(market: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(market.get(key))
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_probability_change(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value * 100:+.1f}pct"


def _format_usd(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"
