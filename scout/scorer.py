from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import config
from pipeline.loader import load_prompt
from pipeline.runner import call_llm
from scout.utils import infer_track

MAX_LLM_INPUT_ITEMS = 18
MAX_ITEMS_PER_SOURCE_FOR_LLM = 4
CORE_SOURCE_BONUS = {
    "arXiv": 1.2,
    "DefiLlama": 1.2,
    "FRED": 1.2,
    "Hugging Face Papers": 0.8,
    "GitHub Trending": 0.7,
    "Hacker News": 0.7,
}

SYSTEM_PROMPT = load_prompt("scout_scorer.md")


def score_candidates(
    raw_items: list[dict[str, Any]],
    top_n: int,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    if not raw_items:
        return [], None

    selected_provider = _resolve_provider(provider)
    try:
        scored = _score_with_llm(raw_items, top_n, selected_provider, model)
        if scored:
            return scored[:top_n], None
    except Exception as exc:
        fallback = _score_with_rules(raw_items, top_n)
        return fallback, f"LLM评分不可用，已使用规则评分：{exc}"

    fallback = _score_with_rules(raw_items, top_n)
    return fallback, "LLM评分未返回有效结果，已使用规则评分"


def _resolve_provider(provider: str | None) -> str:
    selected = (provider or config.DEFAULT_PROVIDER or "groq").strip().lower()
    if selected not in {"groq", "gemini", "anthropic"}:
        raise ValueError(f"Unsupported scout provider: {selected}")
    return selected


def build_scorer_user_input(
    raw_items: list[dict[str, Any]],
    top_n: int,
) -> tuple[str, list[dict[str, Any]]]:
    llm_limit = min(MAX_LLM_INPUT_ITEMS, max(top_n * 4, top_n))
    llm_items = _preselect_for_llm(raw_items, llm_limit)
    compact_items = [_compact_for_llm(item) for item in llm_items]
    user_text = (
        f"请从以下 {len(compact_items)} 条候选中选出总分最高的 {top_n} 条，"
        "优先覆盖 AI×Productivity、Crypto Research、Global Investing 三条赛道。"
        "只返回 JSON 数组，不要解释，不要 Markdown 代码块。\n\n"
        f"{json.dumps(compact_items, ensure_ascii=False, separators=(',', ':'))}"
    )
    return user_text, compact_items


def _compact_for_llm(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data") or {}
    compact = {
        "source": item.get("source"),
        "tier": item.get("tier"),
        "track": item.get("track"),
        "title": item.get("title"),
        "evidence_grade": item.get("evidence_grade"),
        "published_at": item.get("published_at"),
        "url": item.get("url"),
        "summary": item.get("summary"),
    }
    key_fields = (
        "change_7d_pct",
        "current_tvl",
        "score",
        "comments",
        "stars_today",
        "stars",
        "latest_value",
        "change_30d",
        "current_probability",
        "probability_change_24h",
        "volume",
        "latest_score",
        "change_7d",
    )
    compact["metrics"] = {
        key: data.get(key)
        for key in key_fields
        if key in data and data.get(key) is not None
    }
    return compact


def parse_scorer_output(
    text: str,
    top_n: int,
    reference_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    parsed = _extract_json_array(text)
    reference = _build_reference_index(reference_items or [])
    normalized = [
        _normalize_scored_item(item, reference)
        for item in parsed
        if isinstance(item, dict)
    ]
    normalized = [item for item in normalized if item is not None]
    normalized.sort(key=lambda item: item["score"], reverse=True)
    normalized = _ensure_core_final_coverage(normalized[:top_n], reference_items or [], top_n)
    normalized.sort(key=lambda item: item["score"], reverse=True)
    return normalized[:top_n]


def _build_reference_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reference: dict[str, dict[str, Any]] = {}
    for item in items:
        for key in _reference_keys(item):
            reference[key] = item
    return reference


def _reference_keys(item: dict[str, Any]) -> list[str]:
    source = str(item.get("source") or "")
    title = str(item.get("title") or item.get("topic_title") or "")
    url = str(item.get("url") or "")
    keys = []
    if source and title:
        keys.append(f"{source}|title|{title}")
    if source and url:
        keys.append(f"{source}|url|{url}")
    return keys


def _ensure_core_final_coverage(
    selected: list[dict[str, Any]],
    reference_items: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    if top_n < 5:
        return selected
    required_sources = ("FRED",)
    for source in required_sources:
        if any(item.get("source") == source for item in selected):
            continue
        candidate = _best_reference_for_source(reference_items, source)
        if not candidate:
            continue
        replacement = _fallback_from_reference(candidate)
        if not replacement:
            continue
        if len(selected) < top_n:
            selected.append(replacement)
            continue
        replace_index = _lowest_priority_index(selected)
        selected[replace_index] = replacement
    return selected


def _best_reference_for_source(
    reference_items: list[dict[str, Any]],
    source: str,
) -> dict[str, Any] | None:
    candidates = [item for item in reference_items if item.get("source") == source]
    if not candidates:
        return None
    return max(candidates, key=_reference_priority_score)


def _reference_priority_score(item: dict[str, Any]) -> float:
    metrics = item.get("metrics") or {}
    source = item.get("source")
    if source == "FRED":
        return abs(float(metrics.get("change_30d") or 0))
    return float(metrics.get("score") or metrics.get("stars_today") or 0)


def _fallback_from_reference(item: dict[str, Any]) -> dict[str, Any] | None:
    score = min(8.0, max(6.8, _reference_priority_score(item) + 6.8))
    return {
        "source": str(item.get("source") or "unknown"),
        "tier": _to_int(item.get("tier")),
        "track": str(item.get("track") or "unknown"),
        "topic_title": _fallback_title(item),
        "score": score,
        "evidence_grade": str(item.get("evidence_grade") or "unknown"),
        "data_summary": str(item.get("summary") or ""),
        "contrarian_angle": _sanitize_contrarian("", item),
        "suggested_angle": _sanitize_suggested("", item),
        "url": str(item.get("url") or ""),
    }


def _fallback_title(item: dict[str, Any]) -> str:
    source = item.get("source")
    title = str(item.get("title") or "Untitled")
    if source == "FRED":
        return f"{title} 的30日变化"
    return title


def _lowest_priority_index(items: list[dict[str, Any]]) -> int:
    return min(range(len(items)), key=lambda index: float(items[index].get("score") or 0))


def _score_with_llm(
    raw_items: list[dict[str, Any]],
    top_n: int,
    provider: str,
    model_override: str | None,
) -> list[dict[str, Any]]:
    model = model_override or config.PROVIDER_MODELS[provider]
    user_text, llm_items = build_scorer_user_input(raw_items, top_n)
    text, _, _ = call_llm(
        provider=provider,
        model=model,
        system=SYSTEM_PROMPT,
        user=user_text,
        temperature=config.TEMPERATURE_STRICT,
        agent_name="scout_scorer",
    )
    return parse_scorer_output(text, top_n, llm_items)


def _preselect_for_llm(
    raw_items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(raw_items, key=_local_priority_score, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    source_counts: dict[str, int] = {}

    for track in ("AI×Productivity", "Crypto Research", "Global Investing"):
        for item in ranked:
            if len(selected) >= limit:
                return selected
            if str(item.get("track")) != track:
                continue
            if not _can_select_item(item, seen_ids, source_counts):
                continue
            _select_item(item, selected, seen_ids, source_counts)
            if sum(1 for row in selected if row.get("track") == track) >= max(2, limit // 4):
                break

    for source in ("arXiv", "DefiLlama", "FRED"):
        if len(selected) >= limit:
            return selected
        if any(item.get("source") == source for item in selected):
            continue
        for item in ranked:
            if item.get("source") != source:
                continue
            if not _can_select_item(item, seen_ids, source_counts):
                continue
            _select_item(item, selected, seen_ids, source_counts)
            break

    for item in ranked:
        if len(selected) >= limit:
            break
        if not _can_select_item(item, seen_ids, source_counts):
            continue
        _select_item(item, selected, seen_ids, source_counts)

    return selected


def _can_select_item(
    item: dict[str, Any],
    seen_ids: set[str],
    source_counts: dict[str, int],
) -> bool:
    item_id = _item_identity(item)
    source = str(item.get("source") or "unknown")
    if item_id in seen_ids:
        return False
    return source_counts.get(source, 0) < MAX_ITEMS_PER_SOURCE_FOR_LLM


def _select_item(
    item: dict[str, Any],
    selected: list[dict[str, Any]],
    seen_ids: set[str],
    source_counts: dict[str, int],
) -> None:
    selected.append(item)
    seen_ids.add(_item_identity(item))
    source = str(item.get("source") or "unknown")
    source_counts[source] = source_counts.get(source, 0) + 1


def _item_identity(item: dict[str, Any]) -> str:
    return "|".join(
        str(item.get(key) or "")
        for key in ("source", "title", "url")
    )


def _local_priority_score(item: dict[str, Any]) -> float:
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
        + min(2.0, _magnitude_hint(item))
        + CORE_SOURCE_BONUS.get(source, 0.0)
    ) * _tier_weight(tier)


def _extract_json_array(text: str) -> list[Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            preview = text[:300].replace("\n", " ")
            raise ValueError(f"LLM scorer did not return JSON. Preview: {preview}")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            preview = text[:300].replace("\n", " ")
            raise ValueError(f"LLM scorer returned malformed JSON: {exc}. Preview: {preview}")
    if not isinstance(parsed, list):
        raise ValueError("LLM scorer did not return a JSON array.")
    return parsed


def _normalize_scored_item(
    item: dict[str, Any],
    reference: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    score = _to_float(item.get("score"))
    if score is None:
        return None
    ref = _find_reference_item(item, reference)
    source = str(item.get("source") or (ref or {}).get("source") or "unknown")
    tier = _to_int(item.get("tier")) or _to_int((ref or {}).get("tier"))
    track = str(item.get("track") or (ref or {}).get("track") or "unknown")
    url = str(item.get("url") or (ref or {}).get("url") or "")
    title = str(item.get("topic_title") or item.get("title") or (ref or {}).get("title") or "Untitled")
    summary = str(item.get("data_summary") or (ref or {}).get("summary") or "")
    contrarian = _sanitize_contrarian(str(item.get("contrarian_angle") or ""), ref or item)
    suggested = _sanitize_suggested(str(item.get("suggested_angle") or ""), ref or item)
    return {
        "source": source,
        "tier": tier,
        "track": track,
        "topic_title": title,
        "score": max(0, min(10, score)),
        "evidence_grade": str(item.get("evidence_grade") or "unknown"),
        "data_summary": summary,
        "contrarian_angle": contrarian,
        "suggested_angle": suggested,
        "url": url,
    }


def _find_reference_item(
    item: dict[str, Any],
    reference: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in _reference_keys(item):
        if key in reference:
            return reference[key]
    return None


def _sanitize_contrarian(text: str, item: dict[str, Any]) -> str:
    generic_markers = (
        "挑战传统",
        "传统的",
        "数据与常识/共识的冲突",
        "高于行业平均值",
        "低于行业平均值",
    )
    if text and not any(marker in text for marker in generic_markers):
        return text
    source = item.get("source")
    metrics = item.get("metrics") or item.get("data") or {}
    if source == "DefiLlama":
        change = metrics.get("change_7d_pct")
        tvl = metrics.get("current_tvl")
        return f"短期TVL变化达到 {float(change or 0):+.1f}%，但TVL规模约为 {_format_number(tvl)}，需要区分真实资金迁移和低基数效应。"
    if source == "FRED":
        change = metrics.get("change_30d")
        return f"宏观变量约30日变化 {float(change or 0):+.2f}，可能与市场对利率、美元或通胀路径的线性预期不一致。"
    if source == "GitHub Trending":
        stars_today = metrics.get("stars_today")
        return f"项目单日新增 star 约 {int(stars_today or 0)}，说明开发者兴趣可能先于产品商业化叙事出现。"
    if source in {"arXiv", "Hugging Face Papers"}:
        return "一手研究先于媒体叙事出现，适合检查热门 AI 方向是否真的有技术增量。"
    if source == "Hacker News":
        return "专业社区的高分讨论可能比媒体报道更早暴露从业者分歧。"
    return text or "数据出现异常变化，值得进一步验证。"


def _sanitize_suggested(text: str, item: dict[str, Any]) -> str:
    generic_markers = (
        "创新性产品",
        "市场趋势",
        "用户需求",
        "成功可能",
        "成功秘诀",
        "新热点",
        "是否会影响",
        "有关",
        "全球经济趋势",
    )
    if text and not any(marker in text for marker in generic_markers):
        return text
    source = item.get("source")
    if source == "DefiLlama":
        return "用 TVL 变化、协议类别、所属链和代币价值捕获机制做四步拆解，先排除低基数和激励补贴。"
    if source == "FRED":
        return "把该指标放进利率、美元、通胀和风险资产的传导链条中，检验它对资产配置的边际影响。"
    if source == "GitHub Trending":
        return "从 star 增速、项目定位、目标用户和可替代工具四项判断它是短期热度还是真实工作流迁移。"
    if source in {"arXiv", "Hugging Face Papers"}:
        return "从论文问题设定、方法改进、评测结果和可产品化路径判断它是否支撑新叙事。"
    if source == "Hacker News":
        return "提取评论区的反对意见和补充证据，再和原文主张做交叉验证。"
    return text or "先补充 A/B 级证据，再决定是否进入主线写作。"


def _score_with_rules(raw_items: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    scored = []
    for item in raw_items:
        source = item.get("source", "unknown")
        evidence_grade = item.get("evidence_grade", "B")
        tier = _to_int(item.get("tier")) or 3
        track = str(item.get("track") or _infer_item_track(item))
        score = _local_priority_score(item)
        score = max(0, min(10, score))
        scored.append(
            {
                "source": source,
                "tier": tier,
                "track": track,
                "topic_title": _rule_title(item),
                "score": score,
                "evidence_grade": evidence_grade,
                "data_summary": item.get("summary", ""),
                "contrarian_angle": _rule_contrarian_angle(item),
                "suggested_angle": _rule_suggested_angle(item),
                "url": item.get("url", ""),
            }
        )

    scored.sort(key=lambda row: row["score"], reverse=True)
    return scored[:top_n]


def _magnitude_hint(item: dict[str, Any]) -> float:
    data = item.get("data") or {}
    if item.get("source") == "DefiLlama":
        change_score = min(abs(float(data.get("change_7d_pct") or 0)) / 50, 1.0)
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
        return min(abs(float(data.get("main_net_inflow") or 0)) / 500_000_000, 2)
    if item.get("source") == "Polymarket":
        probability = float(data.get("current_probability") or 0.5)
        return 1.5 - abs(probability - 0.5)
    if item.get("source") == "Hacker News":
        return min(float(data.get("score") or 0) / 300, 2)
    if item.get("source") == "GitHub Trending":
        return min(float(data.get("stars_today") or 0) / 300, 2)
    if item.get("source") == "FRED":
        return min(abs(float(data.get("change_30d") or 0)), 2)
    if item.get("source") == "Google Trends":
        return min(abs(float(data.get("change_7d") or 0)) / 30, 2)
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


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
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


def _format_number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.2f}K"
    return f"{number:.2f}"
