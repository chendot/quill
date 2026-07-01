from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

OUTPUT_PATH = Path("inputs/scout_candidates.md")
ARCHIVE_DIR = Path("scout/scout_runs")


def write_candidates(
    candidates: list[dict[str, Any]],
    selected_sources: list[str],
    source_errors: list[str],
    generated_at: datetime | None = None,
) -> Path:
    generated_at = generated_at or datetime.now()
    text = render_candidates(candidates, selected_sources, source_errors, generated_at)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{generated_at.strftime('%Y%m%d_%H%M')}_candidates.md"
    archive_path.write_text(text, encoding="utf-8")
    return OUTPUT_PATH


def render_candidates(
    candidates: list[dict[str, Any]],
    selected_sources: list[str],
    source_errors: list[str],
    generated_at: datetime,
) -> str:
    lines = [
        "---",
        "# Scout 候选话题",
        f"生成时间：{generated_at.strftime('%Y-%m-%d %H:%M')}",
        f"数据源：{', '.join(selected_sources)}",
        "---",
        "",
    ]

    if source_errors:
        lines.extend(["## 数据源状态", ""])
        for error in source_errors:
            label = error if str(error).startswith("[数据源不可用]") else f"[数据源不可用] {error}"
            lines.append(f"- {label}")
        lines.append("")

    if not candidates:
        lines.extend(
            [
                "## 暂无候选",
                "",
                "本次运行没有生成可用候选。请稍后重试，或缩小 `--sources` 范围排查数据源。",
                "",
            ]
        )
        return "\n".join(lines)

    for index, item in enumerate(candidates, start=1):
        tier = item.get("tier")
        tier_text = f"Tier {tier}" if tier else "unknown"
        url = item.get("url") or item.get("link") or ""
        lines.extend(
            [
                f"## {index:02d} · {item.get('topic_title') or item.get('title')}",
                (
                    f"评分：{float(item.get('score', 0)):.1f}/10 | "
                    f"层级：{tier_text} | "
                    f"来源：{item.get('source', 'unknown')} | "
                    f"赛道：{item.get('track', 'unknown')} | "
                    f"证据等级：{item.get('evidence_grade', 'unknown')}"
                ),
                f"可论证性得分：{_format_optional_score(item.get('argumentability_score'))}",
                f"热度得分：{_format_optional_score(item.get('popularity_score'))}",
                f"赛道（细化后）：{item.get('track', 'unknown')}",
                f"数据摘要：{item.get('data_summary') or item.get('summary') or '无'}",
                f"反直觉角度：{item.get('contrarian_angle') or '待人工判断。'}",
                f"建议切入点：{item.get('suggested_angle') or '从数据异常切入，补充可核验来源后再写。'}",
                f"原文链接：{url or '无'}",
                "",
            ]
        )

    return "\n".join(lines)


def _format_optional_score(value: Any) -> str:
    if value is None:
        return "规则路径，无此字段"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)
