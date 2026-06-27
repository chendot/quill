from __future__ import annotations

import json
import re
from typing import Any

import config

MAX_LLM_INPUT_ITEMS = 15

SYSTEM_PROMPT = """你是 Quill 的独立话题侦察评分器。

请只根据输入数据评分，不要编造事实、数字、日期或来源。评分维度：
1. 反直觉程度（0-3分）：结论是否违反大众直觉
2. 信息差价值（0-3分）：目标读者大概率不知道
3. 与 TradFi×DeFi 定位匹配度（0-2分）
4. 数据可信度（0-2分）：是否有 A/B 级证据支撑

总分 10 分。请只返回 JSON 数组，不要使用 Markdown 代码块。每个对象必须包含：
source, topic_title, score, evidence_grade, data_summary, contrarian_angle, suggested_angle。
data_summary 只写事实，不写观点，2-3句。
contrarian_angle 和 suggested_angle 各一句。
"""


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
    llm_limit = min(MAX_LLM_INPUT_ITEMS, max(top_n * 3, top_n))
    llm_items = _preselect_for_llm(raw_items, llm_limit)
    user_text = (
        f"请从以下 {len(llm_items)} 条候选中选出总分最高的 {top_n} 条，"
        "只返回 JSON 数组，不要解释，不要 Markdown 代码块。\n\n"
        f"{json.dumps(llm_items, ensure_ascii=False, indent=2)}"
    )
    return user_text, llm_items


def parse_scorer_output(text: str, top_n: int) -> list[dict[str, Any]]:
    parsed = _extract_json_array(text)
    normalized = [_normalize_scored_item(item) for item in parsed if isinstance(item, dict)]
    normalized = [item for item in normalized if item is not None]
    normalized.sort(key=lambda item: item["score"], reverse=True)
    return normalized[:top_n]


def _score_with_llm(
    raw_items: list[dict[str, Any]],
    top_n: int,
    provider: str,
    model_override: str | None,
) -> list[dict[str, Any]]:
    model = model_override or config.PROVIDER_MODELS[provider]
    user_text, _llm_items = build_scorer_user_input(raw_items, top_n)
    if provider == "groq":
        text = _run_groq(SYSTEM_PROMPT, user_text, model)
    elif provider == "gemini":
        text = _run_gemini(SYSTEM_PROMPT, user_text, model)
    elif provider == "anthropic":
        text = _run_anthropic(SYSTEM_PROMPT, user_text, model)
    else:
        raise ValueError(f"Unsupported scout provider: {provider}")

    return parse_scorer_output(text, top_n)


def _preselect_for_llm(
    raw_items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        raw_items,
        key=lambda item: (
            _magnitude_hint(item),
            1 if item.get("evidence_grade") == "A" else 0,
        ),
        reverse=True,
    )
    return ranked[:limit]


def _run_groq(prompt: str, input_text: str, model: str) -> str:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required for Groq scout scoring.")
    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": input_text},
        ],
        temperature=config.TEMPERATURE_STRICT,
        max_tokens=config.MAX_TOKENS,
    )
    return (response.choices[0].message.content or "").strip()


def _run_gemini(prompt: str, input_text: str, model: str) -> str:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for Gemini scout scoring.")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=input_text,
        config=types.GenerateContentConfig(
            system_instruction=prompt,
            temperature=config.TEMPERATURE_STRICT,
            max_output_tokens=config.MAX_TOKENS,
        ),
    )
    return (response.text or "").strip()


def _run_anthropic(prompt: str, input_text: str, model: str) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic scout scoring.")
    import anthropic

    client = anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response = client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        temperature=config.TEMPERATURE_STRICT,
        system=prompt,
        messages=[{"role": "user", "content": input_text}],
    )
    return "\n".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()


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


def _normalize_scored_item(item: dict[str, Any]) -> dict[str, Any] | None:
    score = _to_float(item.get("score"))
    if score is None:
        return None
    return {
        "source": str(item.get("source") or "unknown"),
        "topic_title": str(item.get("topic_title") or item.get("title") or "Untitled"),
        "score": max(0, min(10, score)),
        "evidence_grade": str(item.get("evidence_grade") or "unknown"),
        "data_summary": str(item.get("data_summary") or ""),
        "contrarian_angle": str(item.get("contrarian_angle") or ""),
        "suggested_angle": str(item.get("suggested_angle") or ""),
    }


def _score_with_rules(raw_items: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    scored = []
    for item in raw_items:
        source = item.get("source", "unknown")
        evidence_grade = item.get("evidence_grade", "B")
        score = 4.0
        if evidence_grade == "A":
            score += 2.0
        elif evidence_grade == "B":
            score += 1.5
        if source in {"DefiLlama", "Eastmoney"}:
            score += 1.5
        if source == "Polymarket":
            score += 1.0
        magnitude = _magnitude_hint(item)
        score += min(2.0, magnitude)
        score = max(0, min(10, score))
        scored.append(
            {
                "source": source,
                "topic_title": _rule_title(item),
                "score": score,
                "evidence_grade": evidence_grade,
                "data_summary": item.get("summary", ""),
                "contrarian_angle": _rule_contrarian_angle(item),
                "suggested_angle": _rule_suggested_angle(item),
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
    return 0


def _rule_title(item: dict[str, Any]) -> str:
    if item.get("source") == "DefiLlama":
        data = item.get("data") or {}
        return f"{data.get('protocol') or item.get('title')} 7日TVL异动"
    return str(item.get("title") or "Untitled")


def _rule_contrarian_angle(item: dict[str, Any]) -> str:
    if item.get("source") == "DefiLlama":
        return "TVL短期大幅变化可能提前暴露资金迁移，而不是等价格叙事确认。"
    if item.get("source") == "Eastmoney":
        return "板块资金流与涨跌幅同看，可能发现价格表现之外的资金偏好。"
    if item.get("source") == "Polymarket":
        return "非极端概率市场保留分歧，适合观察共识尚未定价的事件。"
    return "数据出现异常变化，值得进一步验证。"


def _rule_suggested_angle(item: dict[str, Any]) -> str:
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
