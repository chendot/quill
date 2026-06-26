from __future__ import annotations

from config import HARD_BANNED_WORDS


def scan_hard_rules(text: str) -> list[dict]:
    """Scan text for hard-banned words and return hit positions with context."""
    hits: list[dict] = []
    if not text:
        return hits

    lower_text = text.lower()
    for word in HARD_BANNED_WORDS:
        search_text = lower_text if word.isascii() else text
        search_word = word.lower() if word.isascii() else word
        start = 0

        while True:
            position = search_text.find(search_word, start)
            if position == -1:
                break

            context_start = max(position - 20, 0)
            context_end = min(position + len(word) + 20, len(text))
            hits.append(
                {
                    "word": word,
                    "position": position,
                    "context": text[context_start:context_end],
                }
            )
            start = position + len(search_word)

    hits.sort(key=lambda item: item["position"])
    return hits
