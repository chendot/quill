from __future__ import annotations

import re
from pathlib import Path

from config import PROMPTS_DIR

EXAMPLES_DIR = Path(PROMPTS_DIR) / "examples"
SKILLS_DIR = Path("skills")
EXAMPLE_FILES = {
    "liked": "liked.md",
    "disliked": "disliked.md",
    "notes": "notes.md",
}
SKILL_REF_PATTERN = re.compile(r"@skills/([A-Za-z0-9_.-]+\.md)")


def load_prompt(prompt_file: str) -> str:
    path = Path(PROMPTS_DIR) / prompt_file
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    prompt = path.read_text(encoding="utf-8")
    return append_referenced_skills(prompt)


def append_referenced_skills(prompt: str) -> str:
    skill_names = _referenced_skill_names(prompt)
    if not skill_names:
        return prompt

    sections = ["## Skill References"]
    for skill_name in skill_names:
        skill_path = SKILLS_DIR / skill_name
        if not skill_path.exists():
            raise FileNotFoundError(f"Referenced skill not found: {skill_path}")
        sections.extend(
            [
                "",
                f"### @skills/{skill_name}",
                skill_path.read_text(encoding="utf-8").strip(),
            ]
        )
    return f"{prompt.rstrip()}\n\n" + "\n".join(sections)


def _referenced_skill_names(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in SKILL_REF_PATTERN.finditer(text):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def load_examples() -> dict[str, str]:
    examples: dict[str, str] = {}
    for key, filename in EXAMPLE_FILES.items():
        path = EXAMPLES_DIR / filename
        if not path.exists():
            examples[key] = ""
            continue
        examples[key] = path.read_text(encoding="utf-8")
    return examples


def load_input(path: str | Path) -> str:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    return input_path.read_text(encoding="utf-8").strip()
