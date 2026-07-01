from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from scout.snapshot import load_raw_snapshot, snapshot_items

CANDIDATES_PATH = Path(config.INPUTS_DIR) / "scout_candidates.md"
IDEA_PATH = Path(config.INPUTS_DIR) / "idea.md"
DATA_PATH = Path(config.INPUTS_DIR) / "data.md"
BACKUP_DIR = Path(config.INPUTS_DIR) / "prepared_backups"
RAW_SNAPSHOT_DIR = Path("scout/scout_runs")


@dataclass(frozen=True)
class Candidate:
    index: int
    title: str
    score: str
    tier: str
    source: str
    track: str
    evidence_grade: str
    data_summary: str
    contrarian_angle: str
    suggested_angle: str
    url: str


@dataclass(frozen=True)
class RawMatch:
    item: dict[str, Any] | None
    snapshot_path: Path | None


def main() -> int:
    args = _parse_args()
    candidates = parse_candidates(args.candidates)
    if not candidates:
        raise SystemExit(f"No candidates found in {args.candidates}")
    if args.candidate < 1 or args.candidate > len(candidates):
        raise SystemExit(
            f"--candidate must be between 1 and {len(candidates)}, got {args.candidate}"
        )

    candidate = candidates[args.candidate - 1]
    raw_match = find_raw_match(candidate, args.raw)
    related_items = collect_related_items(candidate, raw_match)
    idea_text = render_idea(candidate, args.platform)
    data_text = render_data(candidate, raw_match, related_items)

    if args.dry_run:
        print("# inputs/idea.md")
        print(idea_text)
        print("\n---\n")
        print("# inputs/data.md")
        print(data_text)
        return 0

    write_prepared_inputs(idea_text, data_text, args.no_backup)
    print(f"Prepared forge inputs from candidate {candidate.index}: {candidate.title}")
    print(f"Wrote {IDEA_PATH}")
    print(f"Wrote {DATA_PATH}")
    if raw_match.snapshot_path:
        print(f"Matched raw snapshot: {raw_match.snapshot_path}")
    else:
        print("Matched raw snapshot: none; used candidate markdown only")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare inputs/idea.md and inputs/data.md from one Scout candidate."
    )
    parser.add_argument(
        "--candidate",
        type=int,
        required=True,
        help="1-based candidate number from inputs/scout_candidates.md.",
    )
    parser.add_argument(
        "--platform",
        default=config.DEFAULT_PLATFORM,
        choices=config.SUPPORTED_PLATFORMS,
        help="Target forge platform to write into idea.md.",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=CANDIDATES_PATH,
        help="Scout candidate markdown file.",
    )
    parser.add_argument(
        "--raw",
        type=Path,
        default=None,
        help="Optional raw snapshot to use for material enrichment.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated idea/data text without writing files.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Overwrite idea.md/data.md without creating timestamped backups.",
    )
    return parser.parse_args()


def parse_candidates(path: Path) -> list[Candidate]:
    if not path.exists():
        raise FileNotFoundError(f"Scout candidates file not found: {path}")

    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^##\s+", text)
    candidates: list[Candidate] = []
    for section in sections[1:]:
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if not lines:
            continue
        header = lines[0]
        header_match = re.match(r"(?P<index>\d+)\s*[·.]\s*(?P<title>.+)", header)
        if not header_match:
            continue

        fields = _candidate_fields(lines[1:])
        meta = _parse_meta_line(fields.get("评分", ""))
        candidates.append(
            Candidate(
                index=int(header_match.group("index")),
                title=header_match.group("title").strip(),
                score=meta.get("score", ""),
                tier=meta.get("tier", ""),
                source=meta.get("source", ""),
                track=meta.get("track", ""),
                evidence_grade=meta.get("evidence_grade", ""),
                data_summary=fields.get("数据摘要", ""),
                contrarian_angle=fields.get("反直觉角度", ""),
                suggested_angle=fields.get("建议切入点", ""),
                url=fields.get("原文链接", ""),
            )
        )
    return candidates


def _candidate_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    for line in lines:
        if "：" in line:
            key, value = line.split("：", 1)
            current_key = key.strip()
            fields[current_key] = value.strip()
            continue
        if current_key:
            fields[current_key] = f"{fields[current_key]}\n{line}".strip()
    return fields


def _parse_meta_line(line: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    parts = [part.strip() for part in line.split("|") if part.strip()]
    for index, part in enumerate(parts):
        if part.startswith("评分"):
            meta["score"] = part.replace("评分：", "").strip()
        elif index == 0 and "/" in part:
            meta["score"] = part.strip()
        elif part.startswith("层级"):
            meta["tier"] = part.replace("层级：", "").strip()
        elif part.startswith("来源"):
            meta["source"] = part.replace("来源：", "").strip()
        elif part.startswith("赛道"):
            meta["track"] = part.replace("赛道：", "").strip()
        elif part.startswith("证据等级"):
            meta["evidence_grade"] = part.replace("证据等级：", "").strip()
    return meta


def find_raw_match(candidate: Candidate, raw_path: Path | None) -> RawMatch:
    snapshot_paths = [raw_path] if raw_path else sorted(
        RAW_SNAPSHOT_DIR.glob("*_raw.json"),
        reverse=True,
    )
    for snapshot_path in snapshot_paths:
        if snapshot_path is None or not snapshot_path.exists():
            continue
        snapshot = load_raw_snapshot(snapshot_path)
        items = snapshot_items(snapshot)
        match = _best_raw_item_match(candidate, items)
        if match:
            return RawMatch(match, snapshot_path)
    return RawMatch(None, None)


def _best_raw_item_match(
    candidate: Candidate,
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_url = _norm(candidate.url)
    candidate_title = _norm(candidate.title)
    candidate_source = _norm(candidate.source)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        item_url = _norm(str(item.get("url") or ""))
        item_title = _norm(str(item.get("title") or ""))
        item_source = _norm(str(item.get("source") or ""))
        score = 0
        if candidate_url and item_url == candidate_url:
            score += 100
        if candidate_source and item_source == candidate_source:
            score += 20
        if candidate_title and item_title:
            if candidate_title == item_title:
                score += 60
            elif candidate_title in item_title or item_title in candidate_title:
                score += 30
        if score:
            scored.append((score, item))
    if not scored:
        return None
    return max(scored, key=lambda row: row[0])[1]


def collect_related_items(
    candidate: Candidate,
    raw_match: RawMatch,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not raw_match.snapshot_path:
        return []
    snapshot = load_raw_snapshot(raw_match.snapshot_path)
    items = snapshot_items(snapshot)
    selected = raw_match.item or {}
    selected_url = _norm(str(selected.get("url") or candidate.url))
    selected_data = selected.get("data") if isinstance(selected.get("data"), dict) else {}
    selected_category = _norm(str(selected_data.get("category") or ""))
    selected_source = _norm(str(selected.get("source") or candidate.source))
    selected_track = _norm(str(selected.get("track") or candidate.track))

    scored: list[tuple[tuple[int, float], dict[str, Any]]] = []
    for item in items:
        item_url = _norm(str(item.get("url") or ""))
        if selected_url and item_url == selected_url:
            continue
        item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        score = 0
        if selected_source and _norm(str(item.get("source") or "")) == selected_source:
            score += 30
        if selected_track and _norm(str(item.get("track") or "")) == selected_track:
            score += 10
        if selected_category and _norm(str(item_data.get("category") or "")) == selected_category:
            score += 20
        if score:
            scored.append(((score, _magnitude(item)), item))
    return [item for _, item in sorted(scored, key=lambda row: row[0], reverse=True)[:limit]]


def render_idea(candidate: Candidate, platform: str) -> str:
    return "\n".join(
        [
            "# 核心判断（给读者的结论）",
            "",
            _core_judgment(candidate),
            "",
            "# 反直觉角度",
            "",
            candidate.contrarian_angle or "待补充：这件事为什么和读者直觉相反？",
            "",
            "# 目标平台",
            "",
            platform,
            "",
        ]
    )


def render_data(
    candidate: Candidate,
    raw_match: RawMatch,
    related_items: list[dict[str, Any]],
) -> str:
    raw_item = raw_match.item or {}
    source = candidate.source or str(raw_item.get("source") or "unknown")
    evidence_grade = candidate.evidence_grade or str(raw_item.get("evidence_grade") or "unknown")
    lines = [
        "# Scout 准备材料",
        "",
        "## 选中议题",
        "",
        f"- 候选编号：{candidate.index}",
        f"- 标题：{candidate.title}",
        f"- 赛道：{candidate.track or raw_item.get('track', 'unknown')}",
        f"- 来源：{source}",
        f"- 证据等级：{evidence_grade}",
        f"- 原文链接：{candidate.url or raw_item.get('url', '无')}",
        "",
        "## 核心事实",
        "",
        f"- {candidate.data_summary or raw_item.get('summary', '待补充。')}",
    ]

    metrics = _material_metrics(raw_item)
    if metrics:
        lines.extend(["", "## 原始字段", ""])
        for key, value in metrics:
            lines.append(f"- {key}：{value}")

    if candidate.contrarian_angle:
        lines.extend(["", "## 反直觉角度", "", candidate.contrarian_angle])
    if candidate.suggested_angle:
        lines.extend(["", "## 建议切入点", "", candidate.suggested_angle])

    if related_items:
        lines.extend(["", "## 同源上下文", ""])
        for item in related_items:
            lines.append(f"- {_related_item_line(item)}")

    lines.extend(
        [
            "",
            "## 需要核实",
            "",
            *_verification_questions(candidate, raw_item),
            "",
            "## 使用边界",
            "",
            "- 以上材料来自 Scout 本地快照和候选摘要；没有在 Prepare 阶段联网补事实。",
            "- 未核实的信息只能写成待确认，不能写成已确认事实。",
            "- E 级证据不能支撑核心论点；A/B/C 级证据也要保留口径、日期和来源。",
            "",
        ]
    )
    if raw_match.snapshot_path:
        lines.extend(["## Raw Snapshot", "", f"- {raw_match.snapshot_path}", ""])
    return "\n".join(lines)


def _core_judgment(candidate: Candidate) -> str:
    if candidate.contrarian_angle:
        if "说明" in candidate.contrarian_angle:
            conclusion = candidate.contrarian_angle.rsplit("说明", 1)[1].strip()
            if conclusion:
                if conclusion.startswith("这"):
                    return conclusion
                return f"这说明{conclusion}"
        if "但" in candidate.contrarian_angle:
            conclusion = candidate.contrarian_angle.rsplit("但", 1)[1].strip()
            if conclusion:
                return conclusion
        return candidate.contrarian_angle
    if candidate.suggested_angle:
        return candidate.suggested_angle
    return candidate.title


def _material_metrics(item: dict[str, Any]) -> list[tuple[str, str]]:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    fields = []
    seen_keys: set[str] = set()
    for key in sorted(data):
        value = data.get(key)
        if value in (None, ""):
            continue
        seen_keys.add(key)
        fields.append((key, _format_value(value)))
    if item.get("published_at") and "published_at" not in seen_keys:
        fields.append(("published_at", str(item["published_at"])))
    if item.get("url") and "url" not in seen_keys:
        fields.append(("url", str(item["url"])))
    return fields


def _related_item_line(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled")
    summary = str(item.get("summary") or "").strip()
    url = str(item.get("url") or "")
    if summary:
        return f"{title}：{summary}（{url or '无链接'}）"
    return f"{title}（{url or '无链接'}）"


def _verification_questions(candidate: Candidate, raw_item: dict[str, Any]) -> list[str]:
    source = candidate.source or str(raw_item.get("source") or "")
    source_norm = _norm(source)
    if source_norm == "defillama":
        return [
            "- TVL 异动是否来自统计口径、单一大户、激励结束或资产迁移？",
            "- 同类别协议是否同步变化，还是只有该协议单点异动？",
            "- 官方公告、治理提案或安全事件是否解释了这次变化？",
        ]
    if source_norm in {"arxiv", "huggingfacepapers"}:
        return [
            "- 论文结论是否只是实验环境成立，还是能外推到真实生产场景？",
            "- 是否有基准、数据集或消融实验限制需要在正文里说明？",
            "- 作者是否明确声明了局限性？",
        ]
    if source_norm == "githubtrending":
        return [
            "- star 增长是否来自真实使用，还是短期传播热度？",
            "- 项目 README 的能力声明是否有 demo、benchmark 或用户案例支撑？",
            "- license、维护频率、issue 质量是否支持长期价值判断？",
        ]
    if source_norm == "hackernews":
        return [
            "- 讨论热度是否来自事实问题，还是社区争议本身？",
            "- 原文证据链是否完整，评论区有没有高质量反驳？",
            "- 是否需要区分技术事实和开发者情绪？",
        ]
    if source_norm == "fred":
        return [
            "- 指标日期、频率和修订口径是否适合支撑正文判断？",
            "- 是否需要对照同周期利率、美元、通胀或风险资产指标？",
            "- 30日变化是否足够代表趋势，还是只是短期波动？",
        ]
    if source_norm == "polymarket":
        return [
            "- 成交量和流动性是否足够，概率变化有没有被小额交易扭曲？",
            "- 市场问题的结算规则是否清楚？",
            "- 是否需要和其他预测市场或公开民调交叉验证？",
        ]
    return [
        "- 核心数字、日期、来源是否可复核？",
        "- 是否存在同等级或更高等级的反方证据？",
        "- 这个材料能支撑核心论点，还是只能作为背景？",
    ]


def write_prepared_inputs(idea_text: str, data_text: str, no_backup: bool) -> None:
    if not no_backup:
        _backup_existing_inputs()
    IDEA_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDEA_PATH.write_text(idea_text, encoding="utf-8")
    DATA_PATH.write_text(data_text, encoding="utf-8")


def _backup_existing_inputs() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for path in (IDEA_PATH, DATA_PATH):
        if not path.exists():
            continue
        backup_path = BACKUP_DIR / f"{path.stem}_{timestamp}{path.suffix}"
        shutil.copy2(path, backup_path)


def _magnitude(item: dict[str, Any]) -> float:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for key in (
        "change_7d_pct",
        "change_7d",
        "stars_today",
        "score",
        "comments",
        "change_30d",
        "volume_24h",
        "current_tvl",
    ):
        try:
            value = abs(float(data.get(key) or 0))
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value
    return 0.0


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


if __name__ == "__main__":
    raise SystemExit(main())
