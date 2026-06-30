from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

from scout.sources.http import fetch_json, fetch_text

SOURCE_NAME = "Hugging Face Papers"
TIER = 1
API_URL = "https://huggingface.co/api/daily_papers"
RSS_URL = "https://huggingface.co/papers/rss.xml"
PAGE_URL = "https://huggingface.co/papers"


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    api_items, api_error = _fetch_api()
    if api_items:
        return api_items, None

    try:
        xml_text = fetch_text(RSS_URL, timeout=25)
    except Exception as exc:
        return _fetch_page(f"API不可用：{api_error}; RSS不可用：{exc}")

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：RSS解析失败 {exc}"

    items: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:20]:
        title = _clean(item.findtext("title", default="Untitled paper"))
        link = item.findtext("link", default="")
        description = _clean(item.findtext("description", default=""))
        published = item.findtext("pubDate", default="")
        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": title,
                "evidence_grade": "B",
                "track": "AI×Productivity",
                "url": link,
                "published_at": _normalize_pubdate(published),
                "data": {
                    "title": title,
                    "authors": "unknown",
                    "abstract": description[:200],
                    "published_at": published,
                    "url": link,
                },
                "summary": (
                    f"{title} 被 Hugging Face Papers 收录；发布时间：{published or 'unknown'}。"
                    f"摘要前200字：{description[:200]}"
                ),
            }
        )
    return items, None


def _fetch_api() -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = fetch_json(API_URL, timeout=25)
    except Exception as exc:
        return [], str(exc)

    if not isinstance(payload, list):
        return [], "响应格式异常"

    items: list[dict[str, Any]] = []
    for row in payload[:20]:
        if not isinstance(row, dict):
            continue
        paper = row.get("paper") if isinstance(row.get("paper"), dict) else row
        title = _clean(str(paper.get("title") or row.get("title") or "Untitled paper"))
        paper_id = str(paper.get("id") or "")
        link = f"https://huggingface.co/papers/{paper_id}" if paper_id else PAGE_URL
        summary = _clean(str(paper.get("summary") or row.get("summary") or ""))
        authors = paper.get("authors") or []
        author_names = [
            str(author.get("name"))
            for author in authors
            if isinstance(author, dict) and author.get("name")
        ]
        published = str(
            row.get("publishedAt")
            or paper.get("submittedOnDailyAt")
            or paper.get("publishedAt")
            or ""
        )
        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": title,
                "evidence_grade": "B",
                "track": "AI×Productivity",
                "url": link,
                "published_at": _normalize_iso(published),
                "data": {
                    "title": title,
                    "authors": ", ".join(author_names),
                    "abstract": summary[:200],
                    "published_at": published,
                    "url": link,
                    "upvotes": paper.get("upvotes"),
                    "github_stars": paper.get("githubStars"),
                },
                "summary": (
                    f"{title} 被 Hugging Face Papers 收录；作者："
                    f"{', '.join(author_names[:4]) or 'unknown'}。"
                    f"摘要前200字：{summary[:200]}"
                ),
            }
        )
    return items, None


def _fetch_page(rss_error: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        page = fetch_text(PAGE_URL, timeout=25)
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{rss_error}; 页面抓取失败：{exc}"

    cards = re.findall(r'<a[^>]+href="(/papers/[^"]+)"[\s\S]*?</a>', page)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for href in cards:
        if href in seen:
            continue
        seen.add(href)
        title = _title_near_href(page, href)
        if not title:
            continue
        link = f"https://huggingface.co{href}"
        items.append(
            {
                "source": SOURCE_NAME,
                "tier": TIER,
                "title": title,
                "evidence_grade": "B",
                "track": "AI×Productivity",
                "url": link,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "title": title,
                    "authors": "unknown",
                    "abstract": "",
                    "published_at": "",
                    "url": link,
                },
                "summary": f"{title} 被 Hugging Face Papers 今日页面收录。链接：{link}",
            }
        )
        if len(items) >= 20:
            break

    if not items:
        return [], f"{SOURCE_NAME} 数据源不可用：{rss_error}; 页面未解析到论文"
    return items, None


def _title_near_href(page: str, href: str) -> str:
    index = page.find(f'href="{href}"')
    if index < 0:
        return ""
    window = page[index : index + 1200]
    title_match = re.search(r'<h3[^>]*>([\s\S]*?)</h3>', window)
    if not title_match:
        title_match = re.search(r'<p[^>]*class="[^"]*font[^"]*"[^>]*>([\s\S]*?)</p>', window)
    if not title_match:
        return ""
    return _clean(html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))))


def _clean(text: str) -> str:
    return " ".join(text.split())


def _normalize_pubdate(value: str) -> str:
    if not value:
        return ""
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except Exception:
        return value


def _normalize_iso(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return value
