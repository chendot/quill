from __future__ import annotations

from pathlib import Path

from config import PROMPTS_DIR


def load_prompt(prompt_file: str) -> str:
    path = Path(PROMPTS_DIR) / prompt_file
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_input(path: str | Path) -> str:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    return input_path.read_text(encoding="utf-8").strip()
