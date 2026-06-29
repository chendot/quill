from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python"
FETCH_TIMEOUT_SECONDS = 60


def _maybe_reexec_with_venv() -> None:
    if os.environ.get("QUILL_SCOUT_NO_VENV_REEXEC"):
        return
    if not VENV_PYTHON.exists():
        return
    if sys.prefix != sys.base_prefix:
        return

    os.environ["QUILL_SCOUT_NO_VENV_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])


_maybe_reexec_with_venv()

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from scout.scorer import SYSTEM_PROMPT, build_scorer_user_input, score_candidates
from scout.scoring_rules import score_with_rules
from scout.snapshot import (
    load_raw_snapshot,
    snapshot_generated_at,
    snapshot_items,
    snapshot_source_errors,
    snapshot_source_names,
    write_raw_snapshot,
)
from scout.sources.tier1_primary import arxiv, github_trending, huggingface_papers
from scout.sources.tier2_community import hackernews
from scout.sources.tier3_data import defillama, eastmoney, fred, polymarket
from scout.sources.tier4_trends import google_trends
from scout.sources.tier5_social import hackernews_hot
from scout.utils import infer_track
from scout.writer import write_candidates

SourceFetcher = Callable[[], tuple[list[dict[str, Any]], str | None]]


@dataclass(frozen=True)
class SourceSpec:
    name: str
    tier: int
    fetcher: SourceFetcher
    default_enabled: bool = True


@dataclass(frozen=True)
class SourceFetchResult:
    source_name: str
    tier: int
    items: list[dict[str, Any]]
    error: str | None


SOURCES: dict[str, SourceSpec] = {
    "arxiv": SourceSpec("arxiv", 1, arxiv.fetch),
    "github_trending": SourceSpec("github_trending", 1, github_trending.fetch),
    "huggingface_papers": SourceSpec(
        "huggingface_papers",
        1,
        huggingface_papers.fetch,
    ),
    "hackernews": SourceSpec("hackernews", 2, hackernews.fetch),
    "defillama": SourceSpec("defillama", 3, defillama.fetch),
    "polymarket": SourceSpec("polymarket", 3, polymarket.fetch),
    "fred": SourceSpec("fred", 3, fred.fetch),
    "eastmoney": SourceSpec("eastmoney", 3, eastmoney.fetch, default_enabled=False),
    "google_trends": SourceSpec(
        "google_trends",
        4,
        google_trends.fetch,
        default_enabled=False,
    ),
    "hackernews_hot": SourceSpec(
        "hackernews_hot",
        5,
        hackernews_hot.fetch,
        default_enabled=False,
    ),
}


def main() -> int:
    args = _parse_args()
    provider = _resolve_provider(args.provider)
    model = _resolve_model(provider, args.model)
    top_n = args.top or getattr(config, "SCOUT_TOP_N", 5)
    raw_snapshot_path: str | None = None
    generated_at: datetime

    if args.fetch_only and args.from_raw:
        raise SystemExit("--fetch-only cannot be combined with --from-raw.")

    if provider == "cowork" and not args.from_raw:
        raise SystemExit(
            "Cowork scoring requires --from-raw. Run "
            "`python scout/run_scout.py --fetch-only` on the local machine first, "
            "then rerun with `--provider cowork --from-raw <snapshot>`."
        )

    if args.from_raw:
        raw_snapshot_path = args.from_raw
        snapshot = load_raw_snapshot(args.from_raw)
        raw_items = snapshot_items(snapshot)
        source_names = snapshot_source_names(snapshot)
        source_errors = snapshot_source_errors(snapshot)
        generated_at = snapshot_generated_at(snapshot)
    else:
        generated_at = datetime.now()
        source_names = _resolve_source_names(args.sources, args.tier)
        raw_items, source_errors, source_status = _extract_raw_items(source_names)
        snapshot_path = write_raw_snapshot(
            raw_items,
            source_names,
            source_status,
            generated_at,
        )
        raw_snapshot_path = str(snapshot_path)
        print(f"Raw snapshot written to {snapshot_path}")
        if args.fetch_only:
            print(f"Fetched {len(raw_items)} raw items. Scoring skipped by --fetch-only.")
            return 0

    if provider == "cowork":
        manifest_path = _prepare_cowork_scout(
            raw_items=raw_items,
            source_names=source_names,
            source_errors=source_errors,
            top_n=top_n,
            model=model,
            raw_snapshot_path=raw_snapshot_path,
        )
        print(f"\nCowork scout manifest written to {manifest_path}")
        print(f"Fetched {len(raw_items)} raw items. Claude should now score candidates.")
        return 0

    if args.from_raw and not args.provider:
        candidates = score_with_rules(raw_items, top_n)
    else:
        candidates, scorer_warning = score_candidates(raw_items, top_n, provider, model)
        if scorer_warning:
            source_errors.append(scorer_warning)

    output_path = write_candidates(candidates, source_names, source_errors, generated_at)
    print(f"Scout candidates written to {output_path}")
    print(f"Fetched {len(raw_items)} raw items; wrote {len(candidates)} candidates.")
    if source_errors:
        print("Warnings:")
        for error in source_errors:
            print(f"- {error}")
    return 0


def _extract_raw_items(
    source_names: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    results = asyncio.run(_fetch_sources(source_names))
    raw_items: list[dict[str, Any]] = []
    source_errors: list[str] = []
    source_status: list[dict[str, Any]] = []

    for result in results:
        normalized_items = [
            _ensure_source_metadata(item, result.source_name)
            for item in result.items
        ]
        raw_items.extend(normalized_items)
        missing_freshness = _missing_freshness_count(result.source_name, normalized_items)
        status = _source_status(result, missing_freshness)
        warning = _source_warning(result, status, missing_freshness)
        if warning:
            print(f"Warning: {warning}")
            source_errors.append(f"[数据源不可用] {warning}")
        source_status.append(
            {
                "source": result.source_name,
                "tier": result.tier,
                "status": status,
                "ok": status == "ok",
                "item_count": len(normalized_items),
                "error": result.error,
                "freshness_field": _freshness_field(result.source_name),
                "missing_freshness_count": missing_freshness,
            }
        )
    return raw_items, source_errors, source_status


async def _fetch_sources(source_names: list[str]) -> list[SourceFetchResult]:
    async def fetch_one(source_name: str) -> SourceFetchResult:
        spec = SOURCES[source_name]
        try:
            items, error = await asyncio.to_thread(spec.fetcher)
            return SourceFetchResult(source_name, spec.tier, items, error)
        except Exception as exc:
            return SourceFetchResult(
                source_name,
                spec.tier,
                [],
                f"{source_name} 数据源不可用：{exc}",
            )

    tasks = [asyncio.create_task(fetch_one(source_name)) for source_name in source_names]
    results: list[SourceFetchResult] = []
    done, pending = await asyncio.wait(tasks, timeout=FETCH_TIMEOUT_SECONDS)
    if pending:
        for task in pending:
            task.cancel()
        timed_out = {task for task in pending}
        for source_name, task in zip(source_names, tasks):
            if task not in timed_out:
                continue
            spec = SOURCES[source_name]
            results.append(
                SourceFetchResult(
                    source_name,
                    spec.tier,
                    [],
                    f"Scout 数据源抓取超过 {FETCH_TIMEOUT_SECONDS} 秒",
                )
            )

    for task in done:
        results.append(task.result())

    return sorted(
        results,
        key=lambda result: source_names.index(result.source_name),
    )


def _ensure_source_metadata(item: dict[str, Any], source_name: str) -> dict[str, Any]:
    spec = SOURCES[source_name]
    item.setdefault("tier", spec.tier)
    text = item.get("title", "") + " " + item.get("summary", "")
    item.setdefault("track", infer_track(text))
    item.setdefault("url", "")
    item.setdefault("published_at", "")
    return item


def _source_status(result: SourceFetchResult, missing_freshness: int) -> str:
    if result.error:
        return "failed"
    if not result.items:
        return "empty"
    if missing_freshness:
        return "incomplete"
    return "ok"


def _source_warning(
    result: SourceFetchResult,
    status: str,
    missing_freshness: int,
) -> str | None:
    if status == "failed":
        return result.error or f"{result.source_name} 数据源不可用"
    if status == "empty":
        return f"{result.source_name} 返回 0 条候选"
    if status == "incomplete":
        field = _freshness_field(result.source_name) or "unknown"
        return f"{result.source_name} 有 {missing_freshness} 条候选缺少热度字段 {field}"
    return None


def _missing_freshness_count(source_name: str, items: list[dict[str, Any]]) -> int:
    field = _freshness_field(source_name)
    if not field:
        return 0
    missing = 0
    for item in items:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        value = data.get(field) if isinstance(data, dict) else None
        if value in (None, ""):
            value = item.get(field)
        if value in (None, ""):
            missing += 1
    return missing


def _freshness_field(source_name: str) -> str:
    fields = getattr(config, "SCOUT_FRESHNESS_FIELD", {})
    return str(fields.get(source_name, ""))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run independent Quill scout.")
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source list, e.g. defillama,arxiv.",
    )
    parser.add_argument(
        "--tier",
        default=None,
        help="Comma-separated tier list, e.g. 1 or 1,3. Ignored when --sources is set.",
    )
    parser.add_argument("--top", type=int, default=None, help="Number of candidates to write.")
    parser.add_argument(
        "--provider",
        default=None,
        help="Scoring provider: groq, gemini, anthropic, or cowork.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the default model for the selected API provider.",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch sources and write a raw snapshot without scoring.",
    )
    parser.add_argument(
        "--from-raw",
        default=None,
        help="Score from an existing raw snapshot instead of fetching sources.",
    )
    return parser.parse_args()


def _resolve_source_names(raw_sources: str | None, raw_tiers: str | None) -> list[str]:
    if raw_sources:
        source_names = [name.strip().lower() for name in raw_sources.split(",") if name.strip()]
        unknown = [name for name in source_names if name not in SOURCES]
        if unknown:
            valid = ", ".join(sorted(SOURCES))
            raise SystemExit(f"Unknown scout source(s): {', '.join(unknown)}. Valid: {valid}")
        return source_names

    if raw_tiers:
        tiers = _parse_tiers(raw_tiers)
        return [
            name
            for name, spec in SOURCES.items()
            if spec.tier in tiers
        ]

    tiers = _parse_tiers(getattr(config, "SCOUT_DEFAULT_TIERS", "1,2,3"))
    return [
        name
        for name, spec in SOURCES.items()
        if spec.default_enabled and spec.tier in tiers
    ]


def _parse_tiers(raw_tiers: str) -> set[int]:
    try:
        tiers = {int(tier.strip()) for tier in raw_tiers.split(",") if tier.strip()}
    except ValueError as exc:
        raise SystemExit(f"Invalid --tier value: {raw_tiers}") from exc
    unknown = sorted(tier for tier in tiers if tier not in {1, 2, 3, 4, 5})
    if unknown:
        raise SystemExit(f"Unsupported tier(s): {unknown}")
    return tiers or {1, 2, 3}


def _resolve_provider(provider: str | None) -> str:
    selected = (provider or config.DEFAULT_PROVIDER or "groq").strip().lower()
    if selected not in {"groq", "gemini", "anthropic", "cowork"}:
        raise SystemExit(f"Unsupported scout provider: {selected}")
    return selected


def _resolve_model(provider: str, model_override: str | None) -> str:
    if model_override:
        return model_override
    if provider == "cowork":
        return config.PROVIDER_MODELS.get("cowork", config.PRIMARY_MODEL)
    return config.PROVIDER_MODELS[provider]


def _prepare_cowork_scout(
    raw_items: list[dict[str, Any]],
    source_names: list[str],
    source_errors: list[str],
    top_n: int,
    model: str,
    raw_snapshot_path: str | None,
) -> Path:
    generated_at = datetime.now()
    user_input, llm_items = build_scorer_user_input(raw_items, top_n)
    manifest = {
        "mode": "scout_cowork",
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M"),
        "provider": "cowork",
        "model": model,
        "sources": source_names,
        "source_errors": source_errors,
        "raw_item_count": len(raw_items),
        "raw_snapshot": raw_snapshot_path,
        "llm_item_count": len(llm_items),
        "top_n": top_n,
        "system_prompt": SYSTEM_PROMPT,
        "user_input": user_input,
        "output_file": "inputs/scout_candidates.md",
        "archive_file": (
            f"scout/scout_runs/{generated_at.strftime('%Y%m%d_%H%M')}_candidates.md"
        ),
    }

    manifest_dir = Path("scout/scout_runs")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{generated_at.strftime('%Y%m%d_%H%M')}_cowork.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print_cowork_manifest(manifest)
    return manifest_path


def _print_cowork_manifest(manifest: dict[str, Any]) -> None:
    sep = "=" * 72
    print(f"\n{sep}")
    print("  SCOUT COWORK 模式")
    print(sep)
    print(f"输出文件:   {manifest['output_file']}")
    print(f"归档文件:   {manifest['archive_file']}")
    print(f"模型:       {manifest['model']}")
    if manifest.get("raw_snapshot"):
        print(f"Raw快照:    {manifest['raw_snapshot']}")
    print(f"数据源:     {', '.join(manifest['sources'])}")
    print(f"原始候选:   {manifest['raw_item_count']}")
    print(f"评分候选:   {manifest['llm_item_count']}")
    if manifest["source_errors"]:
        print("\n【数据源状态】")
        for error in manifest["source_errors"]:
            print(f"- {error}")
    print("\n【SYSTEM PROMPT】")
    print("-" * 72)
    print(manifest["system_prompt"])
    print("\n【USER INPUT】")
    print("-" * 72)
    print(manifest["user_input"])
    print("\n【Claude 需要执行】")
    print("-" * 72)
    print("1. 根据以上 prompt 输出 JSON 数组。")
    print("2. 将 JSON 转成 Scout 候选话题 markdown 格式。")
    print(f"3. 覆盖写入 {manifest['output_file']}。")
    print(f"4. 同步写入归档 {manifest['archive_file']}。")
    print(sep)

if __name__ == "__main__":
    raise SystemExit(main())
