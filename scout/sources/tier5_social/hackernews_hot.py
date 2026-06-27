from __future__ import annotations

from typing import Any

from scout.sources.tier2_community import hackernews

SOURCE_NAME = "Hacker News Hot"
TIER = 5


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    items, error = hackernews.fetch()
    for item in items:
        item["source"] = SOURCE_NAME
        item["tier"] = TIER
    return items, error
