from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

from scout.sources.http import fetch_text
from scout.utils import infer_track

SOURCE_NAME = "arXiv"
TIER = 1
URL = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
QUERIES = (
    "cat:cs.AI",
    "cat:q-fin.CP OR cat:q-fin.EC OR cat:q-fin.GN OR cat:q-fin.MF OR cat:q-fin.PM OR cat:q-fin.RM OR cat:q-fin.ST OR cat:q-fin.TR",
)


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    errors: list[str] = []
    all_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in QUERIES:
        root, error = _fetch_query(query)
        if error:
            errors.append(error)
            continue

        for entry in root.findall("atom:entry", ATOM_NS):
            item = _entry_to_item(entry)
            if not item:
                continue
            url = str(item.get("url") or "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            all_items.append(item)

    cutoff = _source_relative_cutoff(all_items)
    items = [
        item
        for item in all_items
        if _is_at_or_after(item, cutoff)
    ] if cutoff else all_items
    items.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    if not items and errors:
        return [], "; ".join(errors)
    return items[:20], None


def _fetch_query(query: str) -> tuple[ElementTree.Element | None, str | None]:
    params = {
        "search_query": query,
        "start": 0,
        "max_results": 50,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        xml_text = fetch_text(f"{URL}?{urlencode(params)}", timeout=25)
    except Exception as exc:
        return None, f"{query}: {exc}"

    try:
        return ElementTree.fromstring(xml_text), None
    except ElementTree.ParseError as exc:
        return None, f"{query}: RSS解析失败 {exc}"


def _entry_to_item(
    entry: ElementTree.Element,
    cutoff: datetime | None = None,
) -> dict[str, Any] | None:
    published = _parse_time(_text(entry, "atom:published"))
    if cutoff and published and published < cutoff:
        return None
    title = _clean(_text(entry, "atom:title")) or "Untitled paper"
    summary = _clean(_text(entry, "atom:summary"))
    authors = [
        _clean(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    link = _text(entry, "atom:id")
    published_text = published.isoformat() if published else _text(entry, "atom:published")
    if not published_text:
        return None
    return {
        "source": SOURCE_NAME,
        "tier": TIER,
        "title": title,
        "evidence_grade": "B",
        "track": infer_track(title + " " + summary),
        "url": link,
        "published_at": published_text,
        "data": {
            "title": title,
            "authors": ", ".join(author for author in authors if author),
            "abstract": summary[:200],
            "published_at": published_text,
            "url": link,
        },
        "summary": (
            f"{title} 于 {published_text} 提交。作者："
            f"{', '.join(author for author in authors[:4] if author) or 'unknown'}。"
            f"摘要前200字：{summary[:200]}"
        ),
    }


def _source_relative_cutoff(items: list[dict[str, Any]]) -> datetime | None:
    published_times = []
    for item in items:
        published = _parse_time(str(item.get("published_at") or ""))
        if not published:
            continue
        published_times.append(published)
    if not published_times:
        return None
    return max(published_times) - timedelta(hours=48)


def _is_at_or_after(item: dict[str, Any], cutoff: datetime) -> bool:
    published = _parse_time(str(item.get("published_at") or ""))
    return published is not None and published >= cutoff


def _text(entry: ElementTree.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS).strip()


def _clean(text: str) -> str:
    return " ".join(text.split())


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
