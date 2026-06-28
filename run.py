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
from pipeline.compliance import scan_hard_rules
from pipeline.loader import load_input, load_prompt
from pipeline.runner import run_agent
from pipeline.writer import ensure_dir, read_json, read_text, write_json, write_text

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


def run_pipeline(
    input_file: str,
    test_mode: bool,
    provider: str | None,
    platform: str,
    auto: bool,
    from_step: str | None,
    run_dir_name: str | None,
) -> None:
    """Run the Quill content pipeline."""
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

    # Cowork 模式：Claude 直接处理每一步，无需外部 API 调用
    if selected_provider == "cowork":
        _run_cowork_mode(idea_text, data_text, selected_platform, from_step, output_dir, meta)
        return

    # API 模式：依次调用配置的外部 LLM provider
    start_index = _step_index(from_step or "01")
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)

    for step in STEPS[start_index:]:
        agent_input = previous_output
        if step["id"] == "05":
            agent_input = f"{previous_output}\n\n---\n\n# 原始观点\n\n{idea_text}"

        _echo(f"\nRunning {step['id']} {step['name']}...")
        output_text, usage = run_agent(
            step["prompt"],
            agent_input,
            selected_provider,
            model,
            step["temperature"],
            selected_platform,
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

    final_text = read_text(output_dir / "06_final.md")
    hard_hits = scan_hard_rules(final_text)
    meta["hard_rule_hits"] = hard_hits
    if hard_hits:
        _secho("\n硬性敏感词命中：", fg="red", bold=True)
        for hit in hard_hits:
            _secho(
                f"- {hit['word']} @ {hit['position']}: {hit['context']}",
                fg="red",
            )

    decision = _hitl_confirm("after_06", auto, meta)
    write_json(output_dir / "meta.json", meta)
    if decision == "n":
        raise RuntimeError("Stopped after step 06 by HITL decision.")

    _secho(f"\nDone. Outputs written to {output_dir}", fg="green")


# ---------------------------------------------------------------------------
# Cowork 模式：Claude 作为 AI 引擎，逐步处理 pipeline
# ---------------------------------------------------------------------------

def _run_cowork_mode(
    idea_text: str,
    data_text: str,
    platform: str,
    from_step: str | None,
    output_dir: Path,
    meta: dict[str, Any],
) -> None:
    """Cowork 模式执行逻辑。

    每次调用处理 **一个步骤**：
    1. 准备该步骤的 system prompt 和 user input
    2. 将清单写入 outputs/DIR/.cowork_step.json
    3. 打印清单内容（Claude 通过 Bash 输出读取并处理）
    4. 退出——由 Claude 写入输出文件后继续调用下一步

    HITL 节点（步骤 02、06）不阻塞脚本，由 Claude 在对话中向用户确认。
    """
    start_index = _step_index(from_step or "01")

    if start_index >= len(STEPS):
        # 所有步骤已完成，运行最终合规检查
        _cowork_finalize(output_dir, meta)
        return

    step = STEPS[start_index]
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)

    agent_input = previous_output
    if step["id"] == "03":
        agent_input = (
            f"目标平台：{platform}，请严格按照该平台的格式规范输出。"
            f"\n\n{agent_input}"
        )
    if step["id"] == "05":
        agent_input = f"{previous_output}\n\n---\n\n# 原始观点\n\n{idea_text}"

    system_prompt = load_prompt(step["prompt"])

    # 下一步的续跑命令
    next_step_index = start_index + 1
    if next_step_index < len(STEPS):
        next_step_id = STEPS[next_step_index]["id"]
        resume_cmd = _cowork_resume_command(next_step_id, output_dir.name, platform)
    else:
        resume_cmd = _cowork_resume_command("done", output_dir.name, platform)

    # HITL 提示（不阻塞脚本）
    hitl_note = ""
    if step["id"] == "02":
        hitl_note = (
            "\n⚠️  HITL：处理完本步后，请在 Cowork 对话中向用户确认选题和标题，"
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
    }

    manifest_path = output_dir / ".cowork_step.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 打印清单供 Claude 读取
    sep = "=" * 68
    _secho(f"\n{sep}", fg="cyan")
    _secho(f"  COWORK 模式 — 步骤 {step['id']}: {step['name'].upper()}", fg="cyan", bold=True)
    _secho(sep, fg="cyan")
    _echo(f"输出文件:   {output_dir / step['output']}")
    _echo(f"温度:       {step['temperature']}")
    _echo(f"清单文件:   {manifest_path}")
    _echo(f"\n{'─' * 68}")
    _secho("【SYSTEM PROMPT】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(system_prompt)
    _echo(f"\n{'─' * 68}")
    _secho("【USER INPUT】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(agent_input)
    _echo(f"\n{'─' * 68}")
    _secho("【下一步操作】", bold=True)
    _echo(f"{'─' * 68}")
    _echo(f"1. 根据以上 SYSTEM PROMPT 和 USER INPUT 生成输出内容")
    _echo(f"2. 将输出写入: {output_dir / step['output']}")
    _echo(f"3. 更新 meta.json（标记完成步骤；Cowork token 字段保持 null）")
    if hitl_note:
        _secho(hitl_note, fg="yellow")
    _echo(f"4. 继续运行: {resume_cmd}")
    _secho(sep, fg="cyan")

    # 更新 meta：记录当前步骤为 pending（由 Claude 完成后标记）
    meta["cowork_pending_step"] = step["id"]
    write_json(output_dir / "meta.json", meta)


def _cowork_finalize(output_dir: Path, meta: dict[str, Any]) -> None:
    """Cowork 模式最终合规检查（所有 LLM 步骤完成后调用）。"""
    final_path = output_dir / "06_final.md"
    if not final_path.exists():
        _secho("错误：06_final.md 不存在，请先完成步骤 06。", fg="red")
        return

    final_text = read_text(final_path)
    hard_hits = scan_hard_rules(final_text)
    meta["hard_rule_hits"] = hard_hits
    meta.pop("cowork_pending_step", None)

    if hard_hits:
        _secho("\n硬性敏感词命中：", fg="red", bold=True)
        for hit in hard_hits:
            _secho(f"- {hit['word']} @ {hit['position']}: {hit['context']}", fg="red")
    else:
        _secho("\n✓ 硬性敏感词扫描通过", fg="green")

    write_json(output_dir / "meta.json", meta)
    _secho(f"\n✓ Pipeline 完成。输出目录: {output_dir}", fg="green")


def _cowork_resume_command(step_id: str, run_dir_name: str, platform: str) -> str:
    return (
        "python run.py --provider cowork "
        f"--from {step_id} --dir {run_dir_name} --platform {platform}"
    )


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
        if provider == "cowork":
            _set_cowork_usage_null(meta)
        return meta

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
        "hitl_decisions": {
            "after_02": "pending",
            "after_06": "pending",
        },
        "steps_completed": [],
    }
    if provider == "cowork":
        _set_cowork_usage_null(meta)
    return meta


def _set_cowork_usage_null(meta: dict[str, Any]) -> None:
    meta["total_input_tokens"] = None
    meta["total_output_tokens"] = None
    meta["estimated_cost_usd"] = None


def _step_index(step_id: str) -> int:
    # "done" 是 cowork 模式完成所有步骤后的最终态
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
        raise ValueError(f"Unknown platform: {raw_platform}. Supported: {supported}")

    return selected_platform


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
        decision = input(f"{key}: continue? [y/n] ").strip().lower()
    meta.setdefault("hitl_decisions", {})[key] = decision
    return decision


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


def _main_with_argparse() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Quill content pipeline.")
    parser.add_argument(
        "--input",
        dest="input_file",
        default="idea.md",
        help="Input file name under inputs/ or an explicit file path.",
    )
    parser.add_argument(
        "--test",
        dest="test_mode",
        action="store_true",
        help="Legacy flag; use --provider gemini instead.",
    )
    parser.add_argument(
        "--provider",
        choices=config.SUPPORTED_PROVIDERS,
        default=None,
        help="Model provider (groq/gemini/anthropic) or 'cowork' for Claude-native mode.",
    )
    parser.add_argument(
        "--platform",
        choices=config.SUPPORTED_PLATFORMS,
        default=config.DEFAULT_PLATFORM,
        help="Output platform format.",
    )
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--from", dest="from_step", default=None)
    parser.add_argument("--dir", dest="run_dir_name", default=None)
    args = parser.parse_args()
    run_pipeline(
        input_file=args.input_file,
        test_mode=args.test_mode,
        provider=args.provider,
        platform=args.platform,
        auto=args.auto,
        from_step=args.from_step,
        run_dir_name=args.run_dir_name,
    )


if click:

    @click.command(context_settings={"help_option_names": ["-h", "--help"]})
    @click.option(
        "--input",
        "input_file",
        default="idea.md",
        show_default=True,
        help="Input file name under inputs/ or an explicit file path.",
    )
    @click.option(
        "--test",
        "test_mode",
        is_flag=True,
        help="Legacy flag; use --provider gemini instead.",
    )
    @click.option(
        "--provider",
        "provider",
        type=click.Choice(config.SUPPORTED_PROVIDERS),
        default=None,
        help="Model provider (groq/gemini/anthropic) or 'cowork' for Claude-native mode.",
    )
    @click.option(
        "--platform",
        "platform",
        type=click.Choice(config.SUPPORTED_PLATFORMS),
        default=config.DEFAULT_PLATFORM,
        show_default=True,
        help="Output platform format.",
    )
    @click.option("--auto", is_flag=True, help="Skip HITL confirmations.")
    @click.option(
        "--from",
        "from_step",
        default=None,
        help="Resume from a step id such as 03.",
    )
    @click.option(
        "--dir",
        "run_dir_name",
        default=None,
        help="Output directory name under outputs/ for resume runs.",
    )
    def main(
        input_file: str,
        test_mode: bool,
        provider: str | None,
        platform: str,
        auto: bool,
        from_step: str | None,
        run_dir_name: str | None,
    ) -> None:
        run_pipeline(input_file, test_mode, provider, platform, auto, from_step, run_dir_name)

else:
    main = _main_with_argparse


if __name__ == "__main__":
    main()
