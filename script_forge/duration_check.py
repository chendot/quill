from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TARGET_DURATION_SEC = (720, 900)
SPEECH_RATE_CPM = 280

MARKDOWN_PATTERNS = (
    re.compile(r"```.*?```", re.DOTALL),
    re.compile(r"`([^`]*)`"),
    re.compile(r"!\[([^\]]*)\]\([^)]+\)"),
    re.compile(r"\[([^\]]+)\]\([^)]+\)"),
    re.compile(r"(?m)^\s{0,3}#{1,6}\s*"),
    re.compile(r"(?m)^\s{0,3}>\s?"),
    re.compile(r"(?m)^\s*[-*+]\s+"),
    re.compile(r"(?m)^\s*\d+[.)]\s+"),
    re.compile(r"[*_~#>|\\]"),
)

NON_SPOKEN_LINE_PREFIXES = (
    "画面建议",
    "图表",
    "B-roll",
    "转场句",
    "预计秒数",
    "编辑说明",
    "合规结论",
    "口播风险",
    "视觉提示风险",
    "需要替换的表达",
)


def check_duration(
    script_text: str,
    target_duration_sec: tuple[int, int] = TARGET_DURATION_SEC,
    speech_rate_cpm: int = SPEECH_RATE_CPM,
) -> dict[str, int | bool]:
    spoken_text = extract_spoken_text(script_text)
    char_count = count_cjk_chars(spoken_text)
    estimated_sec = round(char_count / speech_rate_cpm * 60) if speech_rate_cpm else 0
    return {
        "char_count": char_count,
        "estimated_duration_sec": estimated_sec,
        "duration_in_range": target_duration_sec[0] <= estimated_sec <= target_duration_sec[1],
    }


def extract_spoken_text(script_text: str) -> str:
    lines = []
    in_spoken_block = False
    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("口播文本"):
            in_spoken_block = True
            remainder = line.split("：", 1)[1].strip() if "：" in line else ""
            if remainder:
                lines.append(remainder)
            continue
        if any(line.startswith(prefix) for prefix in NON_SPOKEN_LINE_PREFIXES):
            in_spoken_block = False
            continue
        if line.startswith("### Beat"):
            in_spoken_block = False
            continue
        if in_spoken_block:
            lines.append(line)
    if lines:
        return strip_markdown("\n".join(lines)).strip()
    return strip_markdown(script_text).strip()


def count_cjk_chars(text: str) -> int:
    return sum(1 for char in text if _is_cjk(char))


def strip_markdown(markdown_text: str) -> str:
    text = markdown_text
    for pattern in MARKDOWN_PATTERNS:
        text = pattern.sub("", text)
    return text


def update_meta(
    run_dir: Path,
    target_duration_sec: tuple[int, int] = TARGET_DURATION_SEC,
    speech_rate_cpm: int = SPEECH_RATE_CPM,
) -> dict[str, Any]:
    script_path = _latest_script_path(run_dir)
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.json not found: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    result = check_duration(
        script_path.read_text(encoding="utf-8"),
        target_duration_sec,
        speech_rate_cpm,
    )
    meta["target_duration_sec"] = [target_duration_sec[0], target_duration_sec[1]]
    meta["estimated_duration_sec"] = result["estimated_duration_sec"]
    meta["duration_in_range"] = result["duration_in_range"]
    meta["speech_rate_cpm"] = speech_rate_cpm
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _latest_script_path(run_dir: Path) -> Path:
    for filename in ("06_reviewed.md", "05_edited.md", "04_script.md"):
        path = run_dir / filename
        if path.exists():
            return path
    raise FileNotFoundError(f"No script file found under {run_dir}")


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
        or 0x2CEB0 <= codepoint <= 0x2EBEF
        or 0x30000 <= codepoint <= 0x3134F
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run script_forge duration check.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--speech-rate-cpm", type=int, default=SPEECH_RATE_CPM)
    parser.add_argument("--duration-min-sec", type=int, default=TARGET_DURATION_SEC[0])
    parser.add_argument("--duration-max-sec", type=int, default=TARGET_DURATION_SEC[1])
    args = parser.parse_args()
    meta = update_meta(
        args.run_dir,
        (args.duration_min_sec, args.duration_max_sec),
        args.speech_rate_cpm,
    )
    print(
        "duration_check: "
        f"estimated_duration_sec={meta['estimated_duration_sec']}, "
        f"duration_in_range={meta['duration_in_range']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
