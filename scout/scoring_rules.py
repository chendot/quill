from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import config
from scout.utils import infer_track

CORE_SOURCE_BONUS = {
    "arXiv": 1.2,
    "DefiLlama": 1.2,
    "FRED": 1.2,
    "Hugging Face Papers": 0.8,
    "GitHub Trending": 0.7,
    "Hacker News": 0.7,
}


def local_priority_score(item: dict[str, Any]) -> float:
    evidence_grade = item.get("evidence_grade", "B")
    evidence_score = {"A": 2.0, "B": 1.4, "C": 0.8, "D": 0.3, "E": 0.0}.get(
        str(evidence_grade),
        0.5,
    )
    tier = _to_int(item.get("tier")) or 3
    source = str(item.get("source") or "")
    track = str(item.get("track") or _infer_item_track(item))
    track_score = 1.0 if track in {"AI×Productivity", "Crypto Research", "Global Investing"} else 0.0
    return (
        2.5
        + evidence_score
        + track_score
        + _timeliness_score(item.get("published_at"))
        + _magnitude_hint(item)
        + CORE_SOURCE_BONUS.get(source, 0.0)
    ) * _tier_weight(tier)


def score_with_rules(raw_items: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    scored = []
    for item in raw_items:
        source = item.get("source", "unknown")
        evidence_grade = item.get("evidence_grade", "B")
        tier = _to_int(item.get("tier")) or 3
        track = str(item.get("track") or _infer_item_track(item))
        score = local_priority_score(item)
        scored.append(
            {
                "source": source,
                "tier": tier,
                "track": track,
                "topic_title": _rule_title(item),
                "score": max(0, score),
                "evidence_grade": evidence_grade,
                "data_summary": item.get("summary", ""),
                "contrarian_angle": _rule_contrarian_angle(item),
                "suggested_angle": _rule_suggested_angle(item),
                "url": item.get("url", ""),
                "published_at": item.get("published_at", ""),
            }
        )

    return rank_and_limit_candidates(scored, top_n)


def rank_and_limit_candidates(
    candidates: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=_candidate_sort_key, reverse=True)
    limited = _limit_by_source_caps(ranked, top_n)
    return [_strip_sort_metadata(item) for item in limited]


def _candidate_sort_key(item: dict[str, Any]) -> tuple[float, float, int, float, str]:
    return (
        max(0.0, _to_float(item.get("score")) or 0.0),
        _published_timestamp(item.get("published_at")),
        _evidence_rank(item.get("evidence_grade")),
        _contrarian_score(item),
        str(item.get("topic_title") or item.get("title") or ""),
    )


def _limit_by_source_caps(
    ranked: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for item in ranked:
        source = str(item.get("source") or "unknown")
        source_cap = _source_cap(source)
        if source_cap is not None and source_counts.get(source, 0) >= source_cap:
            continue
        selected.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= top_n:
            break
    return selected


def _source_cap(source: str) -> int | None:
    caps = getattr(config, "SCOUT_SOURCE_CAPS", {})
    if not isinstance(caps, dict):
        return None
    return caps.get(source)


def _strip_sort_metadata(item: dict[str, Any]) -> dict[str, Any]:
    visible = dict(item)
    visible.pop("published_at", None)
    visible.pop("contrarian_score", None)
    visible.pop("contrarian_degree", None)
    visible.pop("contrarian_degree_score", None)
    return visible


def _published_timestamp(value: Any) -> float:
    if not value:
        return 0.0
    parsed = _parse_datetime(str(value))
    if not parsed:
        return 0.0
    return parsed.timestamp()


def _evidence_rank(value: Any) -> int:
    return {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}.get(str(value), 0)


def _contrarian_score(item: dict[str, Any]) -> float:
    for key in ("contrarian_score", "contrarian_degree", "contrarian_degree_score"):
        score = _to_float(item.get(key))
        if score is not None:
            return score
    return 0.0


def _magnitude_hint(item: dict[str, Any]) -> float:
    data = item.get("data") or {}
    if item.get("source") == "DefiLlama":
        change_score = abs(float(data.get("change_7d_pct") or 0)) / 50
        tvl = float(data.get("current_tvl") or 0)
        if tvl >= 100_000_000:
            tvl_score = 1.5
        elif tvl >= 10_000_000:
            tvl_score = 1.2
        elif tvl >= 1_000_000:
            tvl_score = 0.9
        elif tvl >= 100_000:
            tvl_score = 0.4
        else:
            tvl_score = 0.0
        return change_score + tvl_score
    if item.get("source") == "Eastmoney":
        return abs(float(data.get("main_net_inflow") or 0)) / 500_000_000
    if item.get("source") == "Polymarket":
        probability = float(data.get("current_probability") or 0.5)
        return 1.5 - abs(probability - 0.5)
    if item.get("source") == "Hacker News":
        return float(data.get("score") or 0) / 300
    if item.get("source") == "GitHub Trending":
        return float(data.get("stars_today") or 0) / 300
    if item.get("source") == "FRED":
        return abs(float(data.get("change_30d") or 0))
    if item.get("source") == "Google Trends":
        return abs(float(data.get("change_7d") or 0)) / 30
    if item.get("source") in {"arXiv", "Hugging Face Papers"}:
        return 1.0
    return 0


def _rule_title(item: dict[str, Any]) -> str:
    if item.get("source") == "DefiLlama":
        data = item.get("data") or {}
        return f"{data.get('protocol') or item.get('title')} 7日TVL异动"
    return str(item.get("title") or "Untitled")


def _rule_contrarian_angle(item: dict[str, Any]) -> str:
    if item.get("tier") == 1:
        return "一手资料中的早期信号可能先于二级叙事扩散。"
    if item.get("tier") == 2:
        return "专业社区讨论热度可能比大众媒体更早暴露技术或市场分歧。"
    if item.get("source") == "DefiLlama":
        return "TVL短期大幅变化可能提前暴露资金迁移，而不是等价格叙事确认。"
    if item.get("source") == "Eastmoney":
        return "板块资金流与涨跌幅同看，可能发现价格表现之外的资金偏好。"
    if item.get("source") == "Polymarket":
        return "非极端概率市场保留分歧，适合观察共识尚未定价的事件。"
    return "数据出现异常变化，值得进一步验证。"


def _rule_suggested_angle(item: dict[str, Any]) -> str:
    if item.get("tier") == 1:
        return "从原始论文或项目切入，提炼可验证的趋势框架。"
    if item.get("tier") == 2:
        return "从专业讨论中的争议点切入，寻找可被数据验证的反直觉判断。"
    if item.get("source") == "DefiLlama":
        return "从协议TVL迁移切入，补充链上或官方数据验证资金来源。"
    if item.get("source") == "Eastmoney":
        return "从主力资金方向切入，对照相关资产和政策催化。"
    if item.get("source") == "Polymarket":
        return "从预测市场分歧切入，讨论概率变化背后的信息增量。"
    return "先补充 A/B 级证据，再决定是否进入主线写作。"


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _tier_weight(tier: int) -> float:
    return {
        1: 1.3,
        2: 1.1,
        3: 1.2,
        4: 1.0,
        5: 0.8,
    }.get(tier, 1.0)


def _timeliness_score(published_at: Any) -> float:
    if not published_at:
        return 0.0
    published = _parse_datetime(str(published_at))
    if not published:
        return 0.0
    age = datetime.now(timezone.utc) - published
    if age <= timedelta(hours=24):
        return 1.0
    if age <= timedelta(hours=48):
        return 0.0
    return -1.0


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _infer_item_track(item: dict[str, Any]) -> str:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return infer_track(text)
