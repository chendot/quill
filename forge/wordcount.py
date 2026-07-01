from __future__ import annotations

import re


MARKDOWN_PATTERNS = (
    re.compile(r"```.*?```", re.DOTALL),
    re.compile(r"`([^`]*)`"),
    re.compile(r"!\[([^\]]*)\]\([^)]+\)"),
    re.compile(r"\[([^\]]+)\]\([^)]+\)"),
    re.compile(r"(?m)^\s{0,3}#{1,6}\s*"),
    re.compile(r"(?m)^\s{0,3}>\s?"),
    re.compile(r"(?m)^\s*[-*+]\s+"),
    re.compile(r"(?m)^\s*\d+[.)]\s+"),
    re.compile(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"),
    re.compile(r"[*_~#>|\\]"),
)


def count_cjk_chars(markdown_text: str) -> int:
    cleaned = strip_markdown(markdown_text).strip()
    return sum(1 for char in cleaned if _is_cjk(char))


def strip_markdown(markdown_text: str) -> str:
    text = markdown_text
    text = MARKDOWN_PATTERNS[0].sub("", text)
    text = MARKDOWN_PATTERNS[1].sub(r"\1", text)
    text = MARKDOWN_PATTERNS[2].sub(r"\1", text)
    text = MARKDOWN_PATTERNS[3].sub(r"\1", text)
    for pattern in MARKDOWN_PATTERNS[4:]:
        text = pattern.sub("", text)
    return text


def check_word_count(markdown_text: str, target: tuple[int, int]) -> dict[str, int | bool]:
    actual = count_cjk_chars(markdown_text)
    minimum, maximum = target
    return {
        "actual": actual,
        "in_range": minimum <= actual <= maximum,
    }


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
