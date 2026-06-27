from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from scout.sources.http import fetch_json

SOURCE_NAME = "Hacker News"
TIER = 2
TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    try:
        story_ids = fetch_json(TOP_URL, timeout=20)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    if not isinstance(story_ids, list):
        return [], f"{SOURCE_NAME} 数据源不可用：响应格式异常"

    items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_fetch_item, int(item_id))
            for item_id in story_ids[:30]
            if isinstance(item_id, int)
        ]
        for future in as_completed(futures):
            item = future.result()
            if item:
                items.append(item)

    items.sort(key=lambda row: row["data"].get("score", 0), reverse=True)
    return items, None


def _fetch_item(item_id: int) -> dict[str, Any] | None:
    try:
        story = fetch_json(ITEM_URL.format(item_id=item_id), timeout=15)
    except Exception:
        return None

    if not isinstance(story, dict) or story.get("type") != "story":
        return None

    title = str(story.get("title") or "Untitled HN story")
    score = int(story.get("score") or 0)
    comments = int(story.get("descendants") or 0)
    url = story.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
    published_at = _format_timestamp(story.get("time"))
    return {
        "source": SOURCE_NAME,
        "tier": TIER,
        "title": title,
        "evidence_grade": "B",
        "track": _infer_track(title),
        "url": url,
        "published_at": published_at,
        "data": {
            "title": title,
            "score": score,
            "comments": comments,
            "url": url,
            "published_at": published_at,
        },
        "summary": (
            f"{title} 当前 HN 分数 {score}，评论数 {comments}，发布时间 {published_at}。"
        ),
    }


def _format_timestamp(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _infer_track(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("ai", "llm", "agent", "model", "openai")):
        return "AI×Productivity"
    if any(word in lowered for word in ("bitcoin", "crypto", "ethereum", "defi")):
        return "Crypto Research"
    return "Global Investing"
