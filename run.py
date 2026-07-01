from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import click
except ModuleNotFoundError:
    click = None

import config
from forge.compliance import scan_hard_rules
from forge.loader import load_input
from forge.runner import (
    ProviderRuntimeState,
    build_writer_platform_header,
    prepare_system_prompt,
    run_agent,
)
from forge.wordcount import check_word_count
from forge.writer import ensure_dir, read_json, read_text, write_json, write_text

ASSISTED_PROVIDERS = {"cowork", "codex"}
ASSISTED_PROVIDER_LABELS = {
    "cowork": "Cowork",
    "codex": "Codex",
}

STEPS = [
    {
        "id": "01",
        "name": "researcher",
        "prompt": "01_researcher.md",
        "output": "01_research.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "02",
        "name": "strategist",
        "prompt": "02_strategist.md",
        "output": "02_strategy.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "03",
        "name": "writer",
        "prompt": "03_writer.md",
        "output": "03_draft.md",
        "temperature": config.TEMPERATURE_CREATIVE,
    },
    {
        "id": "04",
        "name": "editor",
        "prompt": "04_editor.md",
        "output": "04_edited.md",
        "temperature": config.TEMPERATURE_CREATIVE,
    },
    {
        "id": "05",
        "name": "reviewer",
        "prompt": "05_reviewer.md",
        "output": "05_reviewed.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "06",
        "name": "compliance",
        "prompt": "06_compliance.md",
        "output": "06_final.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
]

CLI_OPTIONS = (
    {
        "flags": ("--input",),
        "dest": "input_file",
        "default": "idea.md",
        "help": "Input file name under inputs/ or an explicit file path.",
        "show_default": True,
    },
    {
        "flags": ("--test",),
        "dest": "test_mode",
        "is_flag": True,
        "help": "Legacy flag; use --provider gemini instead.",
    },
    {
        "flags": ("--provider",),
        "dest": "provider",
        "choices": config.SUPPORTED_PROVIDERS,
        "default": None,
        "help": "Model provider (groq/gemini/anthropic) or 'cowork'/'codex' for conversation-native mode.",
    },
    {
        "flags": ("--platform",),
        "dest": "platform",
        "default": config.DEFAULT_PLATFORM,
        "help": "Output platform format (long-form only: x-article/wechat).",
        "show_default": True,
    },
    {
        "flags": ("--auto",),
        "dest": "auto",
        "is_flag": True,
        "help": "Skip HITL confirmations.",
    },
    {
        "flags": ("--from",),
        "dest": "from_step",
        "default": None,
        "help": "Resume from a step id such as 03.",
    },
    {
        "flags": ("--dir",),
        "dest": "run_dir_name",
        "default": None,
        "help": "Output directory name under outputs/ for resume runs.",
    },
)


class UnsupportedPlatformError(ValueError):
    pass


def run_forge(
    input_file: str,
    test_mode: bool,
    provider: str | None,
    platform: str,
    auto: bool,
    from_step: str | None,
    run_dir_name: str | None,
) -> None:
    """Run the Quill content forge."""
    input_path = _resolve_input_path(input_file)
    idea_text = load_input(input_path)
    data_text = _load_optional_data()
    selected_provider = _resolve_provider(provider, test_mode)
    selected_platform = _resolve_platform(platform)
    model = config.PROVIDER_MODELS[selected_provider]
    output_dir = _resolve_output_dir(from_step, run_dir_name)
    meta = _load_or_create_meta(
        output_dir,
        input_path.name,
        selected_provider,
        model,
        selected_platform,
    )

    # 对话执行模式：Cowork/Codex 直接处理每一步，无需外部 API 调用
    if selected_provider in ASSISTED_PROVIDERS:
        _run_assisted_mode(
            selected_provider,
            idea_text,
            data_text,
            selected_platform,
            from_step,
            output_dir,
            meta,
        )
        return

    # API 模式：依次调用配置的外部 LLM provider
    start_index = _step_index(from_step or "01")
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)
    runtime_state = ProviderRuntimeState()
    idea_context = _build_idea_context(idea_text, selected_platform)

    for step in STEPS[start_index:]:
        agent_input = _with_idea_context(idea_context, previous_output)
        if step["id"] == "05":
            agent_input = _with_idea_context(
                idea_context,
                f"{previous_output}\n\n---\n\n# 原始观点\n\n{idea_text}",
            )
        if step["id"] == "06":
            agent_input = _with_idea_context(
                idea_context,
                _extract_revised_body(previous_output),
            )

        _echo(f"\nRunning {step['id']} {step['name']}...")
        output_text, usage = run_agent(
            step["prompt"],
            agent_input,
            selected_provider,
            model,
            step["temperature"],
            selected_platform,
            runtime_state,
            _meta_cost(meta),
            allow_offline_gemini=test_mode and provider is None,
        )
        write_text(output_dir / step["output"], output_text)
        _merge_usage(meta, usage)
        _mark_step_completed(meta, step["id"])
        write_json(output_dir / "meta.json", meta)
        previous_output = output_text

        if step["id"] == "02":
            decision = _hitl_confirm("after_02", auto, meta)
            write_json(output_dir / "meta.json", meta)
            if decision == "n":
                raise RuntimeError("Stopped after step 02 by HITL decision.")

    _run_final_checks(output_dir, meta, selected_platform)
    _print_final_check_summary(meta)

    decision = _hitl_confirm("after_06", auto, meta)
    write_json(output_dir / "meta.json", meta)
    if decision == "n":
        raise RuntimeError("Stopped after step 06 by HITL decision.")

    _secho(f"\nDone. Outputs written to {output_dir}", fg="green")


# ---------------------------------------------------------------------------
# 对话执行模式：Cowork/Codex 作为 AI 引擎，逐步处理 forge
# ---------------------------------------------------------------------------

def _run_assisted_mode(
    provider: str,
    idea_text: str,
    data_text: str,
    platform: str,
    from_step: str | None,
    output_dir: Path,
    meta: dict[str, Any],
) -> None:
    """Cowork/Codex 模式执行逻辑。

    每次调用处理 **一个步骤**：
    1. 准备该步骤的 system prompt 和 user input
    2. 将清单写入 outputs/DIR/.<provider>_step.json
    3. 打印清单内容（对话侧通过终端输出读取并处理）
    4. 退出——由对话侧写入输出文件后继续调用下一步

    HITL 节点（步骤 02、06）不阻塞脚本，由对话侧向用户确认。
    """
    label = _assisted_provider_label(provider)
    start_index = _step_index(from_step or "01")

    if start_index >= len(STEPS):
        # 所有步骤已完成，运行最终合规检查
        _assisted_finalize(provider, output_dir, meta)
        return

    step = STEPS[start_index]
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)
    idea_context = _build_idea_context(idea_text, platform)

    agent_input = _with_idea_context(idea_context, previous_output)
    if step["id"] == "05":
        agent_input = _with_idea_context(
            idea_context,
            f"{previous_output}\n\n---\n\n# 原始观点\n\n{idea_text}",
        )
    if step["id"] == "06":
        agent_input = _with_idea_context(
            idea_context,
            _extract_revised_body(previous_output),
        )
    if step["id"] == "03":
        agent_input = f"{build_writer_platform_header(platform)}\n\n{agent_input}"

    system_prompt = prepare_system_prompt(step["prompt"])

    # 下一步的续跑命令
    next_step_index = start_index + 1
    if next_step_index < len(STEPS):
        next_step_id = STEPS[next_step_index]["id"]
        resume_cmd = _assisted_resume_command(provider, next_step_id, output_dir.name, platform)
    else:
        resume_cmd = _assisted_resume_command(provider, "done", output_dir.name, platform)

    # HITL 提示（不阻塞脚本）
    hitl_note = ""
    if step["id"] == "02":
        hitl_note = (
            f"\n⚠️  HITL：处理完本步后，请在 {label} 对话中向用户确认选题和标题，"
            "\n   用户同意后再运行下一步命令。"
        )
    elif step["id"] == "06":
        hitl_note = (
            "\n⚠️  HITL：这是最后一步，处理完后请向用户展示最终稿并确认是否发布。"
        )

    manifest: dict[str, Any] = {
        "step_id": step["id"],
        "step_name": step["name"],
        "prompt_file": f"prompts/{step['prompt']}",
        "output_file": str(output_dir / step["output"]),
        "temperature": step["temperature"],
        "resume_command": resume_cmd,
        "system_prompt": system_prompt,
        "user_input": agent_input,
        "system_prompt_chars": len(system_prompt),
        "user_input_chars": len(agent_input),
    }

    manifest_path = output_dir / f".{provider}_step.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 打印清单供对话侧读取
    sep = "=" * 68
    _secho(f"\n{sep}", fg="cyan")
    _secho(
        f"  {provider.upper()} 模式 — 步骤 {step['id']}: {step['name'].upper()}",
        fg="cyan",
        bold=True,
    )
    _secho(sep, fg="cyan")
    _echo(f"输出文件:   {output_dir / step['output']}")
    _echo(f"温度:       {step['temperature']}")
    _echo(f"清单文件:   {manifest_path}")
    _echo(f"Prompt:     prompts/{step['prompt']} ({len(system_prompt)} chars)")
    _echo(f"Input:      {len(agent_input)} chars")
    _echo(f"\n{'─' * 68}")
    _secho("【SYSTEM PROMPT 预览】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(_compact_preview(system_prompt))
    _echo(f"\n{'─' * 68}")
    _secho("【USER INPUT 预览】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(_compact_preview(agent_input))
    _echo(f"\n{'─' * 68}")
    _secho("【下一步操作】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(f"1. 读取清单文件中的完整 system_prompt 和 user_input，生成输出内容")
    _echo(f"2. 将输出写入: {output_dir / step['output']}")
    _echo(f"3. 更新 meta.json（标记完成步骤；{label} token 字段保持 null）")
    if hitl_note:
        _secho(hitl_note, fg="yellow")
    _echo(f"4. 继续运行: {resume_cmd}")
    _secho(sep, fg="cyan")

    # 更新 meta：记录当前步骤为 pending（由对话侧完成后标记）
    meta[f"{provider}_pending_step"] = step["id"]
    write_json(output_dir / "meta.json", meta)


def _assisted_finalize(provider: str, output_dir: Path, meta: dict[str, Any]) -> None:
    """对话执行模式最终合规检查（所有 LLM 步骤完成后调用）。"""
    final_path = output_dir / "06_final.md"
    if not final_path.exists():
        _secho("错误：06_final.md 不存在，请先完成步骤 06。", fg="red")
        return

    _run_final_checks(output_dir, meta, str(meta.get("platform") or config.DEFAULT_PLATFORM))
    meta.pop(f"{provider}_pending_step", None)
    _print_final_check_summary(meta)

    write_json(output_dir / "meta.json", meta)
    _secho(f"\n✓ Pipeline 完成。输出目录: {output_dir}", fg="green")


def _assisted_resume_command(
    provider: str,
    step_id: str,
    run_dir_name: str,
    platform: str,
) -> str:
    return (
        f"python run.py --provider {provider} "
        f"--from {step_id} --dir {run_dir_name} --platform {platform}"
    )


def _assisted_provider_label(provider: str) -> str:
    return ASSISTED_PROVIDER_LABELS.get(provider, provider)


def _compact_preview(text: str) -> str:
    max_chars = getattr(config, "ASSISTED_PRINT_MAX_CHARS", 1200)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].rstrip()
    tail = text[-max_chars // 2 :].lstrip()
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n\n[... omitted {omitted} chars; see manifest for full text ...]\n\n{tail}"


def _extract_revised_body(review_text: str) -> str:
    marker = "### 修订后正文"
    if marker not in review_text:
        return review_text
    return review_text.split(marker, 1)[1].strip()


def _final_publish_text(output_dir: Path) -> str:
    return read_text(output_dir / "06_final.md")


def _run_final_checks(output_dir: Path, meta: dict[str, Any], platform: str) -> None:
    final_text = _final_publish_text(output_dir)
    meta["hard_rule_hits"] = scan_hard_rules(final_text)
    _record_word_count(meta, final_text, platform)


def _print_final_check_summary(meta: dict[str, Any]) -> None:
    hard_hits = meta.get("hard_rule_hits") or []
    if hard_hits:
        _secho("\n硬性敏感词命中：", fg="red", bold=True)
        for hit in hard_hits:
            _secho(f"- {hit['word']} @ {hit['position']}: {hit['context']}", fg="red")
    else:
        _secho("\n✓ 硬性敏感词扫描通过", fg="green")

    _echo(
        "字数检查："
        f"actual={meta.get('word_count_actual')}, "
        f"target={meta.get('word_count_target')}, "
        f"in_range={meta.get('word_count_in_range')}"
    )


def _build_idea_context(idea_text: str, platform: str) -> str:
    fields = _extract_idea_fields(idea_text)
    core_judgment = fields.get("核心判断（给读者的结论）") or fields.get("核心判断") or "未填写"
    counterintuitive_angle = fields.get("反直觉角度") or "未填写"
    return (
        "# idea.md 核心字段\n"
        f"核心判断：{core_judgment}\n"
        f"反直觉角度：{counterintuitive_angle}\n"
        f"目标平台：{platform}"
    )


def _extract_idea_fields(idea_text: str) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current_heading = ""
    for raw_line in idea_text.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            current_heading = line[2:].strip()
            fields[current_heading] = []
            continue
        if current_heading:
            fields[current_heading].append(raw_line)

    return {
        heading: "\n".join(lines).strip()
        for heading, lines in fields.items()
        if "\n".join(lines).strip()
    }


def _with_idea_context(idea_context: str, body: str) -> str:
    return f"{idea_context}\n\n---\n\n{body}"


def _resolve_input_path(input_file: str) -> Path:
    raw_path = Path(input_file)
    if raw_path.exists():
        return raw_path

    inputs_path = Path(config.INPUTS_DIR) / input_file
    if inputs_path.exists():
        return inputs_path

    raise FileNotFoundError(f"Input file not found: {input_file}")


def _load_optional_data() -> str:
    data_path = Path(config.INPUTS_DIR) / "data.md"
    if not data_path.exists():
        return ""
    return data_path.read_text(encoding="utf-8").strip()


def _resolve_output_dir(from_step: str | None, run_dir_name: str | None) -> Path:
    outputs_root = ensure_dir(config.OUTPUTS_DIR)
    if from_step:
        if run_dir_name:
            output_dir = outputs_root / run_dir_name
        else:
            output_dir = _latest_output_dir(outputs_root)
        if not output_dir.exists():
            raise FileNotFoundError(f"Output directory not found: {output_dir}")
        return output_dir

    run_id = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir = outputs_root / run_id
    suffix = 1
    while output_dir.exists():
        output_dir = outputs_root / f"{run_id}_{suffix:02d}"
        suffix += 1
    return ensure_dir(output_dir)


def _latest_output_dir(outputs_root: Path) -> Path:
    candidates = sorted(path for path in outputs_root.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError("No output directories found for resume.")
    return candidates[-1]


def _load_or_create_meta(
    output_dir: Path,
    input_file: str,
    provider: str,
    model: str,
    platform: str,
) -> dict[str, Any]:
    meta_path = output_dir / "meta.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        meta["provider"] = provider
        meta["model"] = model
        meta["platform"] = platform
        _ensure_word_count_meta(meta, platform)
        if provider in ASSISTED_PROVIDERS:
            _set_assisted_usage_null(meta)
        return meta

    word_count_min, word_count_max = config.WORD_COUNT_RANGES[platform]
    meta = {
        "run_id": output_dir.name,
        "input_file": input_file,
        "provider": provider,
        "model": model,
        "platform": platform,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "hard_rule_hits": [],
        "word_count_target": [word_count_min, word_count_max],
        "word_count_actual": 0,
        "word_count_in_range": None,
        "hitl_decisions": {
            "after_02": "pending",
            "after_06": "pending",
        },
        "steps_completed": [],
    }
    if provider in ASSISTED_PROVIDERS:
        _set_assisted_usage_null(meta)
    return meta


def _set_assisted_usage_null(meta: dict[str, Any]) -> None:
    meta["total_input_tokens"] = None
    meta["total_output_tokens"] = None
    meta["estimated_cost_usd"] = None


def _step_index(step_id: str) -> int:
    # "done" 是对话执行模式完成所有步骤后的最终态
    if step_id == "done":
        return len(STEPS)
    for index, step in enumerate(STEPS):
        if step["id"] == step_id:
            return index
    raise ValueError(f"Unknown step id: {step_id}")


def _resolve_provider(provider: str | None, test_mode: bool) -> str:
    raw_provider = provider
    if raw_provider is None and test_mode:
        raw_provider = "gemini"
    if raw_provider is None:
        raw_provider = config.DEFAULT_PROVIDER or "groq"

    selected_provider = raw_provider.strip().lower()
    if selected_provider not in config.SUPPORTED_PROVIDERS:
        supported = ", ".join(config.SUPPORTED_PROVIDERS)
        raise ValueError(f"Unknown provider: {raw_provider}. Supported: {supported}")

    return selected_provider


def _resolve_platform(platform: str | None) -> str:
    raw_platform = platform or config.DEFAULT_PLATFORM
    selected_platform = raw_platform.strip().lower()
    if selected_platform not in config.SUPPORTED_PLATFORMS:
        supported = ", ".join(config.SUPPORTED_PLATFORMS)
        raise UnsupportedPlatformError(
            f"Unsupported platform: {raw_platform}. "
            f"平台已收窄为长文专用，仅支持：{supported}。"
        )

    return selected_platform


def _ensure_word_count_meta(meta: dict[str, Any], platform: str) -> None:
    word_count_min, word_count_max = config.WORD_COUNT_RANGES[platform]
    meta["word_count_target"] = [word_count_min, word_count_max]
    meta.setdefault("word_count_actual", 0)
    meta.setdefault("word_count_in_range", None)


def _record_word_count(meta: dict[str, Any], final_text: str, platform: str) -> None:
    selected_platform = _resolve_platform(platform)
    target = config.WORD_COUNT_RANGES[selected_platform]
    result = check_word_count(final_text, target)
    meta["word_count_target"] = [target[0], target[1]]
    meta["word_count_actual"] = result["actual"]
    meta["word_count_in_range"] = result["in_range"]


def _initial_input(
    start_index: int,
    output_dir: Path,
    idea_text: str,
    data_text: str,
) -> str:
    if start_index == 0:
        parts = [f"# 核心观点\n\n{idea_text}"]
        if data_text:
            parts.append(f"# 补充数据\n\n{data_text}")
        return "\n\n---\n\n".join(parts)

    previous_step = STEPS[start_index - 1]
    previous_path = output_dir / previous_step["output"]
    if not previous_path.exists():
        raise FileNotFoundError(f"Required resume input not found: {previous_path}")
    return read_text(previous_path)


def _merge_usage(meta: dict[str, Any], usage: dict) -> None:
    if meta.get("total_input_tokens") is None:
        meta["total_input_tokens"] = 0
    if meta.get("total_output_tokens") is None:
        meta["total_output_tokens"] = 0
    if meta.get("estimated_cost_usd") is None:
        meta["estimated_cost_usd"] = 0.0
    meta["total_input_tokens"] += usage["input_tokens"]
    meta["total_output_tokens"] += usage["output_tokens"]
    meta["estimated_cost_usd"] = round(
        meta["estimated_cost_usd"] + usage["estimated_cost_usd"],
        6,
    )


def _meta_cost(meta: dict[str, Any]) -> float:
    return float(meta.get("estimated_cost_usd") or 0.0)


def _mark_step_completed(meta: dict[str, Any], step_id: str) -> None:
    completed = meta.setdefault("steps_completed", [])
    if step_id not in completed:
        completed.append(step_id)


def _hitl_confirm(key: str, auto: bool, meta: dict[str, Any]) -> str:
    if auto:
        meta.setdefault("hitl_decisions", {})[key] = "auto"
        return "y"

    decision = ""
    while decision not in {"y", "n"}:
        decision = input(_hitl_prompt(key, meta)).strip().lower()
    meta.setdefault("hitl_decisions", {})[key] = decision
    return decision


def _hitl_prompt(key: str, meta: dict[str, Any]) -> str:
    if key != "after_06":
        return f"{key}: continue? [y/n] "
    return (
        f"{key}: word_count_actual={meta.get('word_count_actual')}, "
        f"word_count_in_range={meta.get('word_count_in_range')}; continue? [y/n] "
    )


def _echo(message: str) -> None:
    if click:
        click.echo(message)
    else:
        print(message)


def _secho(message: str, fg: str | None = None, bold: bool = False) -> None:
    if click:
        click.secho(message, fg=fg, bold=bold)
    else:
        print(message)


def _run_from_cli_values(
    input_file: str,
    test_mode: bool,
    provider: str | None,
    platform: str,
    auto: bool,
    from_step: str | None,
    run_dir_name: str | None,
) -> None:
    try:
        run_forge(input_file, test_mode, provider, platform, auto, from_step, run_dir_name)
    except UnsupportedPlatformError as exc:
        if click:
            raise click.ClickException(str(exc)) from exc
        raise SystemExit(str(exc)) from exc


def _main_with_argparse() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Quill content forge.")
    for option in CLI_OPTIONS:
        kwargs: dict[str, Any] = {
            "dest": option["dest"],
            "help": option.get("help"),
        }
        if option.get("is_flag"):
            kwargs["action"] = "store_true"
        else:
            kwargs["default"] = option.get("default")
            if option.get("choices"):
                kwargs["choices"] = option["choices"]
        parser.add_argument(*option["flags"], **kwargs)

    args = parser.parse_args()
    _run_from_cli_values(
        input_file=args.input_file,
        test_mode=args.test_mode,
        provider=args.provider,
        platform=args.platform,
        auto=args.auto,
        from_step=args.from_step,
        run_dir_name=args.run_dir_name,
    )


def _build_click_main():
    if click is None:
        return _main_with_argparse

    def command(
        input_file: str,
        test_mode: bool,
        provider: str | None,
        platform: str,
        auto: bool,
        from_step: str | None,
        run_dir_name: str | None,
    ) -> None:
        _run_from_cli_values(
            input_file,
            test_mode,
            provider,
            platform,
            auto,
            from_step,
            run_dir_name,
        )

    command = click.command(context_settings={"help_option_names": ["-h", "--help"]})(command)
    for option in reversed(CLI_OPTIONS):
        kwargs: dict[str, Any] = {
            "help": option.get("help"),
        }
        if option.get("is_flag"):
            kwargs["is_flag"] = True
        else:
            kwargs["default"] = option.get("default")
            kwargs["show_default"] = option.get("show_default", False)
            if option.get("choices"):
                kwargs["type"] = click.Choice(option["choices"])
        param_decls = (*option["flags"], option["dest"])
        command = click.option(*param_decls, **kwargs)(command)
    return command


main = _build_click_main()


if __name__ == "__main__":
    main()
