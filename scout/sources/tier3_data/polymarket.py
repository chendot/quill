from __future__ import annotations

import json
from typing import Any

import config
from scout.sources.http import fetch_json
from scout.utils import infer_track

SOURCE_NAME = "Polymarket"
TIER = 3
URL = "https://gamma-api.polymarket.com/markets"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    """Fetch high volume markets where probability is not an extreme consensus."""
    max_items = int(getattr(config, "SCOUT_POLYMARKET_MAX_ITEMS", 20))
    min_volume = float(getattr(config, "SCOUT_POLYMARKET_MIN_VOLUME_USD", 10_000))
    min_liquidity = float(getattr(config, "SCOUT_POLYMARKET_MIN_LIQUIDITY_USD", 1_000))
    params = {"limit": 100, "order": "volume", "ascending": "false"}
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
        volume_24h = _first_float(
            market,
            ("volume24hr", "volume24h", "oneDayVolume", "volume1d"),
        )
        total_volume = _first_float(market, ("volume", "volumeNum"))
        liquidity = _first_float(market, ("liquidity", "liquidityNum"))
        if volume_24h is None or volume_24h < min_volume:
            continue
        if liquidity is not None and liquidity < min_liquidity:
            continue

        question = str(market.get("question") or market.get("title") or "Untitled market")

        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": question,
                "evidence_grade": "B",
                "track": infer_track(question),
                "url": str(market.get("url") or market.get("slug") or "https://polymarket.com/"),
                "published_at": str(market.get("createdAt") or ""),
                "data": {
                    "market": question,
                    "current_probability": probability,
                    "probability_change_24h": change_24h,
                    "volume_24h": volume_24h,
                    "total_volume": total_volume,
                    "liquidity": liquidity,
                },
                "summary": (
                    f"{question} 当前隐含概率 {probability * 100:.1f}%。"
                    f"24小时概率变化：{_format_probability_change(change_24h)}；"
                    f"24小时成交量：{_format_usd(volume_24h)}；"
                    f"总成交量：{_format_usd(total_volume)}；"
                    f"流动性：{_format_usd(liquidity)}。"
                ),
            }
        )

    items.sort(key=_market_signal_score, reverse=True)
    return items[:max_items], None


def _market_signal_score(item: dict[str, Any]) -> float:
    data = item.get("data") or {}
    volume_24h = _to_float(data.get("volume_24h")) or 0
    total_volume = _to_float(data.get("total_volume")) or 0
    liquidity = _to_float(data.get("liquidity")) or 0
    probability_change = abs(_to_float(data.get("probability_change_24h")) or 0)
    return volume_24h * 2 + total_volume * 0.2 + liquidity + probability_change * 100_000


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
