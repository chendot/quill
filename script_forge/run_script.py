from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from forge.loader import append_referenced_skills, load_input
from forge.runner import ProviderRuntimeState, call_llm
from forge.writer import ensure_dir, read_json, read_text, write_json, write_text
from script_forge.duration_check import (
    SPEECH_RATE_CPM,
    TARGET_DURATION_SEC,
    update_meta as update_duration_meta,
)

ASSISTED_PROVIDERS = {"cowork", "codex"}
PROMPTS_DIR = Path("script_forge/prompts")
OUTPUTS_DIR = Path("video_outputs")

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
        "name": "script_strategist",
        "prompt": "02_script_strategist.md",
        "output": "02_strategy.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "03",
        "name": "outline_beats",
        "prompt": "03_outline_beats.md",
        "output": "03_beats.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "04",
        "name": "script_writer",
        "prompt": "04_script_writer.md",
        "output": "04_script.md",
        "temperature": config.TEMPERATURE_CREATIVE,
    },
    {
        "id": "05",
        "name": "script_editor",
        "prompt": "05_script_editor.md",
        "output": "05_edited.md",
        "temperature": config.TEMPERATURE_CREATIVE,
    },
    {
        "id": "06",
        "name": "script_reviewer",
        "prompt": "06_script_reviewer.md",
        "output": "06_reviewed.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
    {
        "id": "07",
        "name": "compliance",
        "prompt": "07_compliance.md",
        "output": "07_final.md",
        "temperature": config.TEMPERATURE_STRICT,
    },
]


def main() -> int:
    args = _parse_args()
    run_script_forge(
        input_file=args.input_file,
        provider=args.provider,
        auto=args.auto,
        from_step=args.from_step,
        run_dir_name=args.run_dir_name,
        speech_rate_cpm=args.speech_rate_cpm,
        duration_min_sec=args.duration_min_sec,
        duration_max_sec=args.duration_max_sec,
    )
    return 0


def run_script_forge(
    input_file: str,
    provider: str | None,
    auto: bool,
    from_step: str | None,
    run_dir_name: str | None,
    speech_rate_cpm: int,
    duration_min_sec: int,
    duration_max_sec: int,
) -> None:
    input_path = _resolve_input_path(input_file)
    idea_text = load_input(input_path)
    data_text = _load_optional_data()
    selected_provider = _resolve_provider(provider)
    model = config.PROVIDER_MODELS[selected_provider]
    output_dir = _resolve_output_dir(from_step, run_dir_name)
    target_duration = (duration_min_sec, duration_max_sec)
    meta = _load_or_create_meta(
        output_dir,
        input_path.name,
        selected_provider,
        model,
        target_duration,
        speech_rate_cpm,
    )

    if selected_provider in ASSISTED_PROVIDERS:
        _run_assisted_mode(
            provider=selected_provider,
            idea_text=idea_text,
            data_text=data_text,
            from_step=from_step,
            output_dir=output_dir,
            meta=meta,
            target_duration=target_duration,
            speech_rate_cpm=speech_rate_cpm,
        )
        return

    start_index = _step_index(from_step or "01")
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)
    runtime_state = ProviderRuntimeState()

    for step in STEPS[start_index:]:
        agent_input = _step_input(
            step["id"],
            previous_output,
            target_duration,
            speech_rate_cpm,
        )
        print(f"\nRunning script_forge {step['id']} {step['name']}...")
        output_text, usage = _run_api_step(
            step=step,
            user_input=agent_input,
            provider=selected_provider,
            model=model,
            runtime_state=runtime_state,
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

    _run_duration_check(output_dir, target_duration, speech_rate_cpm)
    meta = read_json(output_dir / "meta.json")
    decision = _hitl_confirm("after_07", auto, meta)
    write_json(output_dir / "meta.json", meta)
    if decision == "n":
        raise RuntimeError("Stopped after step 07 by HITL decision.")

    print(f"\nDone. Script outputs written to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Quill YouTube script forge.")
    parser.add_argument("--input", dest="input_file", default="idea.md")
    parser.add_argument("--provider", choices=config.SUPPORTED_PROVIDERS, default=None)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--from", dest="from_step", default=None)
    parser.add_argument("--dir", dest="run_dir_name", default=None)
    parser.add_argument("--speech-rate-cpm", type=int, default=SPEECH_RATE_CPM)
    parser.add_argument("--duration-min-sec", type=int, default=TARGET_DURATION_SEC[0])
    parser.add_argument("--duration-max-sec", type=int, default=TARGET_DURATION_SEC[1])
    return parser.parse_args()


def _run_api_step(
    step: dict[str, Any],
    user_input: str,
    provider: str,
    model: str,
    runtime_state: ProviderRuntimeState,
) -> tuple[str, dict[str, int | float]]:
    system_prompt = _load_script_prompt(step["prompt"])
    text, input_tokens, output_tokens = call_llm(
        provider=provider,
        model=model,
        system=system_prompt,
        user=user_input,
        temperature=step["temperature"],
        agent_name=f"script_{step['name']}",
        runtime_state=runtime_state,
    )
    return text, _usage_stats(provider, input_tokens, output_tokens)


def _load_script_prompt(prompt_file: str) -> str:
    prompt_path = PROMPTS_DIR / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Script prompt not found: {prompt_path}")
    return append_referenced_skills(prompt_path.read_text(encoding="utf-8"))


def _step_input(
    step_id: str,
    previous_output: str,
    target_duration: tuple[int, int],
    speech_rate_cpm: int,
) -> str:
    if step_id == "04":
        header = (
            f"目标时长：{target_duration[0]}–{target_duration[1]} 秒，"
            f"语速参考：{speech_rate_cpm} 字/分钟，"
            "请按 beat 结构输出，每个 beat 单独标注。"
        )
        return f"{header}\n\n{previous_output}"
    if step_id == "07":
        return _extract_revised_script(previous_output)
    return previous_output


def _extract_revised_script(text: str) -> str:
    for marker in ("### 修订后脚本", "### 最终脚本"):
        if marker in text:
            return text.split(marker, 1)[1].strip()
    return text


def _run_assisted_mode(
    provider: str,
    idea_text: str,
    data_text: str,
    from_step: str | None,
    output_dir: Path,
    meta: dict[str, Any],
    target_duration: tuple[int, int],
    speech_rate_cpm: int,
) -> None:
    start_index = _step_index(from_step or "01")
    if start_index >= len(STEPS):
        _run_duration_check(output_dir, target_duration, speech_rate_cpm)
        meta = read_json(output_dir / "meta.json")
        meta.pop(f"{provider}_pending_step", None)
        write_json(output_dir / "meta.json", meta)
        print(
            "duration_check: "
            f"estimated_duration_sec={meta.get('estimated_duration_sec')}, "
            f"duration_in_range={meta.get('duration_in_range')}"
        )
        print(f"Script pipeline complete: {output_dir}")
        return

    step = STEPS[start_index]
    previous_output = _initial_input(start_index, output_dir, idea_text, data_text)
    user_input = _step_input(
        step["id"],
        previous_output,
        target_duration,
        speech_rate_cpm,
    )
    next_step_id = STEPS[start_index + 1]["id"] if start_index + 1 < len(STEPS) else "done"
    resume_cmd = (
        f"python script_forge/run_script.py --provider {provider} "
        f"--from {next_step_id} --dir {output_dir.name}"
    )
    manifest = {
        "mode": f"script_forge_{provider}",
        "step_id": step["id"],
        "step_name": step["name"],
        "prompt_file": f"script_forge/prompts/{step['prompt']}",
        "output_file": str(output_dir / step["output"]),
        "manifest_file": str(output_dir / f".{provider}_script_step.json"),
        "temperature": step["temperature"],
        "resume_command": resume_cmd,
        "system_prompt": _load_script_prompt(step["prompt"]),
        "user_input": user_input,
        "system_prompt_chars": len(_load_script_prompt(step["prompt"])),
        "user_input_chars": len(user_input),
    }
    manifest_path = output_dir / f".{provider}_script_step.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta[f"{provider}_pending_step"] = step["id"]
    write_json(output_dir / "meta.json", meta)
    _print_assisted_manifest(provider, manifest)


def _print_assisted_manifest(provider: str, manifest: dict[str, Any]) -> None:
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  SCRIPT_FORGE {provider.upper()} — STEP {manifest['step_id']}: {manifest['step_name']}")
    print(sep)
    print(f"输出文件: {manifest['output_file']}")
    print(f"清单文件: {manifest['manifest_file']}")
    print(f"Prompt: {manifest['prompt_file']} ({manifest['system_prompt_chars']} chars)")
    print(f"Input: {manifest['user_input_chars']} chars")
    print("\n下一步：")
    print("1. 读取 manifest 中的 system_prompt 和 user_input")
    print("2. 写入 output_file")
    print("3. 更新 meta.json steps_completed")
    print(f"4. 继续运行: {manifest['resume_command']}")
    print(sep)


def _run_duration_check(
    output_dir: Path,
    target_duration: tuple[int, int],
    speech_rate_cpm: int,
) -> None:
    meta = update_duration_meta(output_dir, target_duration, speech_rate_cpm)
    print(
        "duration_check: "
        f"estimated_duration_sec={meta.get('estimated_duration_sec')}, "
        f"duration_in_range={meta.get('duration_in_range')}"
    )


def _resolve_input_path(input_file: str) -> Path:
    raw_path = Path(input_file)
    if raw_path.exists():
        return raw_path
    input_path = Path(config.INPUTS_DIR) / input_file
    if input_path.exists():
        return input_path
    raise FileNotFoundError(f"Input file not found: {input_file}")


def _load_optional_data() -> str:
    data_path = Path(config.INPUTS_DIR) / "data.md"
    if not data_path.exists():
        return ""
    return data_path.read_text(encoding="utf-8").strip()


def _resolve_provider(provider: str | None) -> str:
    selected = (provider or config.DEFAULT_PROVIDER or "groq").strip().lower()
    if selected not in config.SUPPORTED_PROVIDERS:
        supported = ", ".join(config.SUPPORTED_PROVIDERS)
        raise ValueError(f"Unknown provider: {selected}. Supported: {supported}")
    return selected


def _resolve_output_dir(from_step: str | None, run_dir_name: str | None) -> Path:
    outputs_root = ensure_dir(OUTPUTS_DIR)
    if from_step:
        output_dir = outputs_root / run_dir_name if run_dir_name else _latest_output_dir(outputs_root)
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
        raise FileNotFoundError("No video output directories found for resume.")
    return candidates[-1]


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
    return read_text(output_dir / previous_step["output"])


def _load_or_create_meta(
    output_dir: Path,
    input_file: str,
    provider: str,
    model: str,
    target_duration: tuple[int, int],
    speech_rate_cpm: int,
) -> dict[str, Any]:
    meta_path = output_dir / "meta.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        meta["provider"] = provider
        meta["model"] = model
        meta["target_duration_sec"] = [target_duration[0], target_duration[1]]
        meta["speech_rate_cpm"] = speech_rate_cpm
        if provider in ASSISTED_PROVIDERS:
            _set_assisted_usage_null(meta)
        return meta
    meta = {
        "run_id": output_dir.name,
        "input_file": input_file,
        "provider": provider,
        "model": model,
        "pipeline": "script_forge",
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "hard_rule_hits": [],
        "target_duration_sec": [target_duration[0], target_duration[1]],
        "estimated_duration_sec": 0,
        "duration_in_range": None,
        "speech_rate_cpm": speech_rate_cpm,
        "hitl_decisions": {
            "after_02": "pending",
            "after_07": "pending",
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


def _usage_stats(provider: str, input_tokens: int, output_tokens: int) -> dict[str, int | float]:
    costs = config.PROVIDER_COSTS_USD_PER_TOKEN.get(provider, {})
    input_cost = costs.get("input") or 0
    output_cost = costs.get("output") or 0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(input_tokens * input_cost + output_tokens * output_cost, 6),
    }


def _merge_usage(meta: dict[str, Any], usage: dict[str, int | float]) -> None:
    meta["total_input_tokens"] += int(usage["input_tokens"])
    meta["total_output_tokens"] += int(usage["output_tokens"])
    meta["estimated_cost_usd"] = round(
        float(meta["estimated_cost_usd"]) + float(usage["estimated_cost_usd"]),
        6,
    )


def _mark_step_completed(meta: dict[str, Any], step_id: str) -> None:
    completed = meta.setdefault("steps_completed", [])
    if step_id not in completed:
        completed.append(step_id)


def _step_index(step_id: str) -> int:
    if step_id == "done":
        return len(STEPS)
    for index, step in enumerate(STEPS):
        if step["id"] == step_id:
            return index
    raise ValueError(f"Unknown step id: {step_id}")


def _hitl_confirm(key: str, auto: bool, meta: dict[str, Any]) -> str:
    if auto:
        meta.setdefault("hitl_decisions", {})[key] = "auto"
        return "y"
    decision = ""
    while decision not in {"y", "n"}:
        prompt = _hitl_prompt(key, meta)
        decision = input(prompt).strip().lower()
    meta.setdefault("hitl_decisions", {})[key] = decision
    return decision


def _hitl_prompt(key: str, meta: dict[str, Any]) -> str:
    if key != "after_07":
        return f"{key}: continue? [y/n] "
    return (
        f"{key}: estimated_duration_sec={meta.get('estimated_duration_sec')}, "
        f"duration_in_range={meta.get('duration_in_range')}; continue? [y/n] "
    )


if __name__ == "__main__":
    raise SystemExit(main())
