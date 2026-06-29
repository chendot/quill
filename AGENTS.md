# AGENTS.md — Quill Development Instructions

## Project Identity

Quill is a local content-agent pipeline for turning short investment ideas into publishable drafts.

Intentional design constraints:
- Linear pipeline, no branching
- No LangChain / CrewAI / LangGraph
- No database; file system is state
- Prompts stored as editable `prompts/*.md`
- Each step writes an independent output file
- Supports breakpoint reruns via `--from`
- Supports API mode and Cowork mode
- Supports platform-specific writer output via `--platform`

**SPEC.md is the source of truth for product behavior. Do not silently change its design assumptions.**

---

## Hard Prohibitions

Never introduce:
- Agent frameworks or orchestration libraries
- Vector databases or any database-backed state
- Web UI or auto-publishing
- Web search integration
- Multi-agent concurrency
- Hidden prompt generation inside Python code

Never do:
- Move prompts into Python code — prompts must remain in `prompts/*.md`
- Hardcode API keys, model names, or sensitive words outside `config.py`
- Write generated outputs into git-tracked paths — runtime outputs go under `outputs/YYYYMMDD_HHMM/`
- Commit `.env`, `outputs/`, `__pycache__/`, or any runtime-generated file

---

## Pipeline Architecture

Fixed execution order:

```
01_researcher → 02_strategist → 03_writer → 04_editor → 05_reviewer → 06_compliance → compliance.py
```

**Input rules:**
- Each LLM step receives only the previous step's output
- Exception: `05_reviewer` also receives the original `inputs/idea.md`
- Exception: `03_writer` receives a user-message header with the selected platform:
  `目标平台：{platform}，请严格按照该平台的格式规范输出。`
- `06_compliance` receives the revised body text from `05_reviewer`, not the review report

**Researcher constraint:**
Must not invent facts, figures, dates, or market data.
May only classify evidence quality, identify data gaps, and flag missing sources.

**Compliance — two layers (must not be merged):**
- `06_compliance.md`: LLM-based tone and regulatory risk review
- `pipeline/compliance.py`: deterministic hard-rule keyword scan, pure Python, no LLM call

## Scout ETL Architecture

Scout is an independent topic reconnaissance module, not a main pipeline step.
It must follow a strict Extract → Transform → Load split:

- Extract: local Python fetches public data sources and writes `scout/scout_runs/YYYYMMDD_HHMM_raw.json`
- Transform: scoring, ranking, summarization, and track matching read only the raw snapshot
- Load: candidate markdown is written to `inputs/scout_candidates.md` and archived under `scout/scout_runs/`

Raw snapshots must include fetch metadata, selected sources, per-source success/failure status, and raw items with title, summary, data, URL, timestamp, source, tier, track, and evidence grade.

Source adapters must apply domain-specific hard filters before writing raw snapshots. Do not dump low-quality full source payloads and rely on the scorer to clean them up. If a source returns zero items, mark it `empty`; if required freshness fields are missing, mark it `incomplete`.

Cowork must not execute network fetches. `python scout/run_scout.py --provider cowork` requires `--from-raw`; first run `python scout/run_scout.py --fetch-only` locally, then pass the generated raw snapshot to Cowork scoring.

---

## Provider System

Supported providers: `groq` / `gemini` / `anthropic` / `cowork`

Priority order:
1. CLI `--provider`
2. `.env` `DEFAULT_PROVIDER`
3. Fallback: `groq`

**Cowork mode is not an LLM provider.**
In Cowork mode, the script prepares and prints the system prompt and user input for the current step, persists step metadata, then exits. Claude executes natively in the conversation window and writes the output file.

Rate limit delays (configured in `config.py`, not hardcoded in runner):
- `groq`: 3s between calls
- `gemini`: 15s between calls
- `anthropic`: 0s
- `cowork`: N/A

## Platform System

Supported platforms: `x-tweet` / `x-thread` / `x-article` / `xhs-text` / `xhs-caption` / `xueqiu`

Priority order:
1. CLI `--platform`
2. `.env` `DEFAULT_PLATFORM`
3. Fallback: `x-thread`

Platform templates live only in `prompts/03_writer.md`. Python code may pass the selected platform to the writer, but must not hardcode platform-specific content templates.

---

## CLI Interface

Maintain all of the following:

```bash
python run.py                                          # default provider, default input
python run.py --input my_idea.md                       # specify input file
python run.py --provider groq                          # explicit provider
python run.py --provider gemini
python run.py --provider anthropic
python run.py --provider cowork
python run.py --platform x-tweet                      # generate single-tweet format
python run.py --platform x-thread                     # default thread format
python run.py --platform xhs-text                     # generate Xiaohongshu text format
python run.py --test                                   # backward-compatible, maps to gemini
python run.py --auto                                   # skip all HITL prompts
python run.py --from 03                                # resume from step 03, latest dir
python run.py --from 03 --platform xueqiu              # resume writer and later steps with Xueqiu format
python run.py --from 03 --dir 20260626_1430            # resume from step 03, specific dir
python run.py --provider cowork --from 02 --dir 20260626_1520
python run.py --provider cowork --from 03 --dir 20260626_1520 --platform xhs-caption
python run.py --provider cowork --from done --dir 20260626_1520  # run hard-rule scan only
```

`--test` is kept for backward compatibility and maps to `--provider gemini`.
New code should prefer explicit `--provider`.

---

## HITL Rules

**API mode:** blocking `input()` after step 02 and step 06, skipped if `--auto` is passed.

**Cowork mode:** no blocking in Python. HITL checkpoints happen in the Claude conversation. After each HITL step, Claude tells the user the next command to run and waits for confirmation.

Required HITL points:
- After step 02 (topic and angle confirmation)
- After step 06 (final publish confirmation)

---

## Metadata

Every run maintains `outputs/YYYYMMDD_HHMM/meta.json`.

Required fields:
```json
{
  "run_id": "YYYYMMDD_HHMM",
  "input_file": "idea.md",
  "provider": "groq",
  "model": "llama-3.1-8b-instant",
  "platform": "x-thread",
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "estimated_cost_usd": 0.0,
  "hard_rule_hits": [],
  "hitl_decisions": {},
  "steps_completed": []
}
```

On breakpoint rerun (`--from`), update the existing `meta.json` in the target directory.
Do not create a new `meta.json` for checkpoint runs.

Token tracking: Cowork mode cannot count tokens. Set token fields to `null` for Cowork steps.

---

## Coding Style

- Small pure functions; side effects isolated in `writer.py`, `runner.py`, and CLI orchestration
- Clear exceptions with actionable error messages
- No clever abstractions — this project must remain understandable to a solo maintainer
- Config values read from `config.py` only; never re-read `.env` directly in pipeline code

---

## Development Order

When building from scratch, implement in this sequence:

1. Directory structure and `.gitignore`
2. `config.py`
3. `pipeline/compliance.py` (pure Python, testable without API)
4. `pipeline/loader.py` and `pipeline/writer.py`
5. `pipeline/runner.py` (with retry and rate-limit delay)
6. `run.py` (CLI, HITL, meta.json)
7. Prompt skeletons in `prompts/`
8. End-to-end dry run with `--test --auto`
9. Prompt content iteration

**Prove the file pipeline first. Improve prompts and provider quality second.**

---

## Content Philosophy

All generated content must follow:
- Conclusion first, no filler
- No emotional manipulation, no miracle predictions
- No price targets unless explicitly provided by the user in `idea.md`
- Data gaps must be labeled, never invented
- E-level evidence cannot support the core thesis

Evidence hierarchy:
- **A**: on-chain data, financial statements, primary data
- **B**: whitepapers, official documents, earnings call transcripts
- **C**: institutional research reports
- **D**: KOL commentary, analyst opinions
- **E**: market sentiment, narrative trends

When uncertain, preserve uncertainty explicitly. Do not smooth over gaps.
