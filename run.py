from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import click
except ModuleNotFoundError:
    click = None

import config
from pipeline.compliance import scan_hard_rules
from pipeline.loader import load_input
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
    auto: bool,
    from_step: str | None,
    run_dir_name: str | None,
) -> None:
    """Run the Quill content pipeline."""
    input_path = _resolve_input_path(input_file)
    idea_text = load_input(input_path)
    data_text = _load_optional_data()
    model = config.TEST_MODEL if test_mode else config.PRIMARY_MODEL
    output_dir = _resolve_output_dir(from_step, run_dir_name)
    meta = _load_or_create_meta(output_dir, input_path.name, model)

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
            model,
            step["temperature"],
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


def _load_or_create_meta(output_dir: Path, input_file: str, model: str) -> dict[str, Any]:
    meta_path = output_dir / "meta.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        meta["model"] = model
        return meta

    return {
        "run_id": output_dir.name,
        "input_file": input_file,
        "model": model,
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


def _step_index(step_id: str) -> int:
    for index, step in enumerate(STEPS):
        if step["id"] == step_id:
            return index
    raise ValueError(f"Unknown step id: {step_id}")


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
    parser.add_argument("--test", dest="test_mode", action="store_true")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--from", dest="from_step", default=None)
    parser.add_argument("--dir", dest="run_dir_name", default=None)
    args = parser.parse_args()
    run_pipeline(
        input_file=args.input_file,
        test_mode=args.test_mode,
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
    @click.option("--test", "test_mode", is_flag=True, help="Use the test model.")
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
        auto: bool,
        from_step: str | None,
        run_dir_name: str | None,
    ) -> None:
        run_pipeline(input_file, test_mode, auto, from_step, run_dir_name)

else:
    main = _main_with_argparse


if __name__ == "__main__":
    main()
