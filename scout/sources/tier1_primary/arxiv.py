from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from scout.utils import infer_track

SOURCE_NAME = "arXiv"
TIER = 1
URL = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch() -> tuple[list[dict[str, Any]], str | None]:
    params = {
        "search_query": "cat:cs.AI OR cat:q-fin*",
        "start": 0,
        "max_results": 50,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        request = Request(
            f"{URL}?{urlencode(params)}",
            headers={"User-Agent": "QuillScout/0.1"},
        )
        with urlopen(request, timeout=25) as response:
            xml_text = response.read().decode("utf-8")
    except Exception as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：{exc}"

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        return [], f"{SOURCE_NAME} 数据源不可用：RSS解析失败 {exc}"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    items: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        published = _parse_time(_text(entry, "atom:published"))
        if published and published < cutoff:
            continue
        title = _clean(_text(entry, "atom:title")) or "Untitled paper"
        summary = _clean(_text(entry, "atom:summary"))
        authors = [
            _clean(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        link = _text(entry, "atom:id")
        published_text = published.isoformat() if published else _text(entry, "atom:published")
        items.append(
            {
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
        )

    items.sort(key=lambda row: row.get("published_at") or "", reverse=True)
    return items[:20], None


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
