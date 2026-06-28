from __future__ import annotations

import time
import os
from pathlib import Path

import config
from pipeline.loader import load_prompt

_TOTAL_COST_USD = 0.0
_LAST_API_CALL_AT = 0.0


def run_agent(
    prompt_file: str,
    input_text: str,
    provider: str,
    model: str,
    temperature: float,
    platform: str,
) -> tuple[str, dict]:
    """Run a single agent and return generated text plus usage stats."""
    prompt = load_prompt(prompt_file)
    agent_name = Path(prompt_file).stem
    agent_input = _inject_platform_header(prompt_file, input_text, platform)
    output_text, input_tokens, output_tokens = _run_with_retry(
        agent_name=agent_name,
        prompt=prompt,
        input_text=agent_input,
        provider=provider,
        model=model,
        temperature=temperature,
    )
    stats = _build_usage_stats(input_tokens, output_tokens, provider)
    _print_usage(agent_name, stats)
    return output_text, stats


def _inject_platform_header(prompt_file: str, input_text: str, platform: str) -> str:
    if Path(prompt_file).name != "03_writer.md":
        return input_text
    platform_header = f"目标平台：{platform}，请严格按照该平台的格式规范输出。"
    return f"{platform_header}\n\n{input_text}"


def _run_with_retry(
    agent_name: str,
    prompt: str,
    input_text: str,
    provider: str,
    model: str,
    temperature: float,
) -> tuple[str, int, int]:
    last_error: Exception | None = None
    max_attempts = config.RETRY_ATTEMPTS + 1

    for attempt in range(1, max_attempts + 1):
        try:
            if provider == "gemini" and not config.GEMINI_API_KEY:
                return _offline_test_response(agent_name, prompt, input_text)
            return call_llm(
                provider=provider,
                model=model,
                system=prompt,
                user=input_text,
                temperature=temperature,
                agent_name=agent_name,
            )
        except Exception as exc:
            last_error = exc
            if attempt <= config.RETRY_ATTEMPTS:
                if _is_rate_limit_error(exc):
                    print(
                        f"[{agent_name}] 429限速，等待60秒后重试（第{attempt}次）"
                    )
                    time.sleep(60)
                    continue

                print(
                    f"[{agent_name}] API failed on attempt {attempt}/"
                    f"{max_attempts}: {exc}. Retrying in "
                    f"{config.RETRY_DELAY_SECONDS}s..."
                )
                time.sleep(config.RETRY_DELAY_SECONDS)

    raise RuntimeError(f"[{agent_name}] failed after retries: {last_error}")


def call_llm(
    provider: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
    agent_name: str = "llm",
) -> tuple[str, int, int]:
    """Call a configured LLM provider and return text plus token usage."""
    if provider == "gemini":
        _wait_for_rate_limit(provider)
        return _run_gemini(agent_name, system, user, model, temperature)
    if provider == "anthropic":
        _wait_for_rate_limit(provider)
        return _run_anthropic(system, user, model, temperature)
    if provider == "groq":
        _wait_for_rate_limit(provider)
        return _run_groq(system, user, model, temperature)
    raise ValueError(f"Unsupported provider: {provider}")


def _wait_for_rate_limit(provider: str) -> None:
    global _LAST_API_CALL_AT

    provider_delays = getattr(config, "PROVIDER_RATE_LIMIT_DELAY_SECONDS", {})
    delay_seconds = provider_delays.get(
        provider,
        getattr(config, "RATE_LIMIT_DELAY_SECONDS", 0),
    )
    if delay_seconds <= 0:
        _LAST_API_CALL_AT = time.monotonic()
        return

    now = time.monotonic()
    elapsed = now - _LAST_API_CALL_AT if _LAST_API_CALL_AT else delay_seconds
    wait_seconds = delay_seconds - elapsed
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    _LAST_API_CALL_AT = time.monotonic()


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "429" in message
        or "RESOURCE_EXHAUSTED" in message
        or "TooManyRequests" in message
    )


def _run_anthropic(
    prompt: str,
    input_text: str,
    model: str,
    temperature: float,
) -> tuple[str, int, int]:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is required for primary model runs.")

    import anthropic

    client = anthropic.Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response = client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        temperature=temperature,
        system=prompt,
        messages=[{"role": "user", "content": input_text}],
    )
    text = "\n".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or _estimate_tokens(prompt + input_text))
    output_tokens = int(getattr(usage, "output_tokens", 0) or _estimate_tokens(text))
    return text, input_tokens, output_tokens


def _run_groq(
    prompt: str,
    input_text: str,
    model: str,
    temperature: float,
) -> tuple[str, int, int]:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required for Groq provider runs.")

    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": input_text},
        ],
        temperature=temperature,
        max_tokens=config.MAX_TOKENS,
    )
    text = (response.choices[0].message.content or "").strip()
    usage = getattr(response, "usage", None)
    input_tokens = int(
        getattr(usage, "prompt_tokens", 0) or _estimate_tokens(prompt + input_text)
    )
    output_tokens = int(
        getattr(usage, "completion_tokens", 0) or _estimate_tokens(text)
    )
    return text, input_tokens, output_tokens


def _run_gemini(
    agent_name: str,
    prompt: str,
    input_text: str,
    model: str,
    temperature: float,
) -> tuple[str, int, int]:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for test model runs.")

    from google import genai
    from google.genai import types
    import httpx

    proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    httpx_kwargs = {"timeout": config.REQUEST_TIMEOUT_SECONDS, "trust_env": False}
    if proxy_url:
        httpx_kwargs["proxy"] = proxy_url

    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(
            httpx_client=httpx.Client(**httpx_kwargs)
        ),
    )
    generation_config = types.GenerateContentConfig(
        system_instruction=prompt,
        temperature=temperature,
        max_output_tokens=config.MAX_TOKENS,
    )
    response = client.models.generate_content(
        model=model,
        contents=input_text,
        config=generation_config,
    )
    _warn_if_gemini_output_truncated(agent_name, response)
    text = (response.text or "").strip()
    usage = getattr(response, "usage_metadata", None)
    input_tokens = int(
        getattr(usage, "prompt_token_count", 0) or _estimate_tokens(prompt + input_text)
    )
    output_tokens = int(
        getattr(usage, "candidates_token_count", 0) or _estimate_tokens(text)
    )
    return text, input_tokens, output_tokens


def _warn_if_gemini_output_truncated(agent_name: str, response: object) -> None:
    finish_reason = _gemini_finish_reason(response)
    if finish_reason == "MAX_TOKENS":
        print(f"[{agent_name}] 警告：输出被截断，finish_reason=MAX_TOKENS")


def _gemini_finish_reason(response: object) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None

    raw_finish_reason = getattr(candidates[0], "finish_reason", None)
    if raw_finish_reason is None:
        return None

    name = getattr(raw_finish_reason, "name", None)
    if name:
        return str(name)

    return str(raw_finish_reason)


def _offline_test_response(
    agent_name: str,
    prompt: str,
    input_text: str,
) -> tuple[str, int, int]:
    sections = {
        "01_researcher": (
            "# 数据缺口与证据等级\n\n"
            "## 已收到的核心观点\n"
            f"{_excerpt(input_text)}\n\n"
            "## 数据缺口\n"
            "- 需要人工补充可核验数据来源。\n\n"
            "## 证据等级要求\n"
            "- 核心论点需由 A/B/C 级证据支撑，E 级证据仅可作为情绪背景。"
        ),
        "02_strategist": (
            "# 选题报告\n\n"
            "## 判断\n"
            "该选题可继续，但需避免价格预测和过度承诺。\n\n"
            "## 目标平台\n"
            "长文社媒。\n\n"
            "## 核心论点\n"
            "把原始观点压缩为一个可验证、可讨论的判断。\n\n"
            "## 标题候选\n"
            "1. 这个投资判断真正要验证什么\n"
            "2. 先看证据，再谈结论\n"
            "3. 一条观点如何变成可发布内容"
        ),
        "03_writer": (
            "# 正文初稿\n\n"
            "结论先行：这条观点值得讨论，但前提是把证据边界讲清楚。\n\n"
            "当前材料更适合形成一个审慎的分析框架，而不是直接给出交易判断。"
        ),
        "04_editor": (
            "# 润色后正文\n\n"
            "结论先行：这条观点可以写，但必须先讲清证据边界。\n\n"
            "目前更稳妥的表达，是把它处理成一个分析框架：哪些事实已知，哪些缺口待补。"
        ),
        "05_reviewer": (
            "# 审稿报告\n\n"
            "## 逻辑检查\n"
            "- 主线清晰，没有明显跳跃。\n\n"
            "## 偏离检查\n"
            "- 未发现对原始观点的明显偏离。\n\n"
            "## 修订建议\n"
            "- 发布前补充真实数据来源。"
        ),
        "06_compliance": (
            "# 最终稿与语气风险报告\n\n"
            "## 最终稿\n"
            "这条观点可以作为分析框架发布，但需要保留证据边界，并避免把不确定性包装成确定结论。\n\n"
            "## 语气风险\n"
            "- 未发现明显过度承诺。\n\n"
            "## 替代表达\n"
            "- 使用“可能”“需要验证”“数据显示”替代确定性判断。"
        ),
    }
    text = sections.get(
        agent_name,
        f"# {agent_name}\n\n离线测试输出。\n\n{_excerpt(input_text)}",
    )
    return text, _estimate_tokens(prompt + input_text), _estimate_tokens(text)


def _build_usage_stats(input_tokens: int, output_tokens: int, provider: str) -> dict:
    costs = getattr(config, "PROVIDER_COSTS_USD_PER_TOKEN", {}).get(provider, {})
    input_cost = costs.get("input", config.COST_PER_INPUT_TOKEN)
    output_cost = costs.get("output", config.COST_PER_OUTPUT_TOKEN)
    if input_cost is None or output_cost is None:
        cost = None
    else:
        cost = input_tokens * input_cost + output_tokens * output_cost
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost,
    }


def _print_usage(agent_name: str, stats: dict) -> None:
    global _TOTAL_COST_USD
    cost = stats["estimated_cost_usd"]
    if cost is None:
        print(
            f"[{agent_name}] tokens: {stats['input_tokens']}→"
            f"{stats['output_tokens']} | cost unavailable"
        )
        return
    _TOTAL_COST_USD += cost
    print(
        f"[{agent_name}] tokens: {stats['input_tokens']}→"
        f"{stats['output_tokens']} | 本次: "
        f"${cost:.4f} | 累计: ${_TOTAL_COST_USD:.4f}"
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _excerpt(text: str, limit: int = 240) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
