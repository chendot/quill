from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from scout.sources.http import fetch_text
from scout.utils import infer_track

SOURCE_NAME = "GitHub Trending"
TIER = 1
URL = "https://github.com/trending?since=daily"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    try:
        page = fetch_text(
            URL,
            timeout=25,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
        )
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    articles = re.findall(r"<article[\s\S]*?</article>", page)
    items: list[dict[str, Any]] = []
    for article in articles[:20]:
        repo_match = re.search(r'href="/([^"]+)"[\s\S]*?<span class="text-normal">', article)
        if not repo_match:
            repo_match = re.search(r'<h2[\s\S]*?<a[^>]+href="/([^"]+)"', article)
        if not repo_match:
            continue

        repo = _clean(repo_match.group(1))
        description_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>([\s\S]*?)</p>', article)
        language_match = re.search(r'itemprop="programmingLanguage">([^<]+)</span>', article)
        stars_match = re.search(
            r'href="/[^"]+/stargazers"[\s\S]*?([0-9][0-9,]*)\s*</a>',
            article,
        )
        today_match = re.search(r'([0-9,]+)\s+stars?\s+today', article)
        url = f"https://github.com/{repo}"
        description = _clean(description_match.group(1)) if description_match else ""
        stars = _to_int(stars_match.group(1) if stars_match else None)
        today_stars = _to_int(today_match.group(1) if today_match else None)
        if today_stars is None:
            continue
        language = _clean(language_match.group(1)) if language_match else "unknown"
        published_at = date.today().isoformat()

        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": repo,
                "evidence_grade": "B",
                "track": infer_track(repo + " " + description),
                "url": url,
                "published_at": published_at,
                "data": {
                    "repo": repo,
                    "description": description,
                    "stars": stars,
                    "stars_today": today_stars,
                    "language": language,
                    "url": url,
                    "published_at": published_at,
                },
                "summary": (
                    f"{repo} 今日 GitHub Trending；语言：{language}；总 star "
                    f"{stars or 0}，今日新增 star {today_stars or 0}。"
                    f"描述：{description or '无'}"
                ),
            }
        )

    return items[:20], None


def _clean(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(" ".join(no_tags.split())).strip()


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None
