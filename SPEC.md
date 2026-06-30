# Quill — Product Spec

Quill turns a short investment idea into a publishable draft through a local, file-based forge.

SPEC.md is the source of truth for product behavior.

## Goals

Input:
- `inputs/idea.md`: short investment idea
- `inputs/data.md`: optional user-provided facts, links, or data

Output:
- research notes
- topic strategy
- platform-specific draft
- edited draft
- logic review
- compliance report
- hard-rule scan results
- token/cost metadata

Non-goals:
- no Agent framework
- no database or vector store
- no Web UI
- no auto-publishing
- no main-forge web search
- no multi-agent concurrency

## Project Map

```text
run.py                    main CLI
config.py                 keys, provider/model/platform config, hard-rule words
forge/                    shared loader, writer, runner, compliance scan
prompts/                  editable agent prompts
prompts/examples/         writer reference snippets
skills/                   reusable prompt rules
inputs/                   human-edited inputs and Scout candidates
outputs/YYYYMMDD_HHMM/    runtime outputs and meta.json
scout/                    independent topic reconnaissance ETL
```

Runtime outputs are not git-tracked.

## Main Forge

Execution order is fixed:

```text
01_researcher -> 02_strategist -> 03_writer -> 04_editor -> 05_reviewer -> 06_compliance -> forge/compliance.py
```

Input boundaries:
- each LLM step reads only the previous step output
- `05_reviewer` also reads original `inputs/idea.md`
- `03_writer` receives platform header in the user message
- `06_compliance` receives reviewer-revised body text, not the review report

HITL checkpoints:
- after `02_strategist`: confirm topic, angle, title direction
- after `06_compliance`: confirm final publish readiness

API mode blocks at HITL unless `--auto` is passed. Cowork/Codex mode never blocks Python; confirmation happens in the conversation.

## Agent Contracts

| Step | Role | Output |
| --- | --- | --- |
| 01_researcher | classify evidence and data gaps; never invent facts | `01_research.md` |
| 02_strategist | decide topic value, platform, thesis, titles | `02_strategy.md` |
| 03_writer | write platform-specific draft | `03_draft.md` |
| 04_editor | compress, clarify, sharpen expression | `04_edited.md` |
| 05_reviewer | check logic, support, drift from idea | `05_reviewed.md` |
| 06_compliance | review tone and regulatory risk | `06_final.md` |
| forge/compliance.py | deterministic hard-rule scan | `meta.json hard_rule_hits` |

Shared judgment rules live in:
- `skills/evidence-quality.md`
- `skills/thesis-angle-validation.md`
- `skills/compliance-review.md`

## Platform System

Supported platforms:

```text
x-tweet, x-thread, x-article, xhs-text, xhs-caption, xueqiu, wechat
```

Priority:

```text
CLI --platform > .env DEFAULT_PLATFORM > x-thread
```

Only `prompts/03_writer.md` may contain platform templates. Python may pass the selected platform but must not hardcode platform content.

For writer steps, prepend this to the user message:

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

## Provider System

Supported providers:

```text
groq, gemini, anthropic, cowork, codex
```

Priority:

```text
CLI --provider > .env DEFAULT_PROVIDER > groq
```

API providers call external LLM SDKs. Cowork/Codex providers only prepare a step manifest and print prompt/input for the conversation-side assistant.

Configured provider delays live in `config.py`, not runner code.

## Examples Reference

`03_writer` may receive examples appended to the system prompt from:

```text
prompts/examples/liked.md
prompts/examples/disliked.md
prompts/examples/notes.md
```

The appended section must say:

```text
学习判断标准，不要模仿句式。
```

Rules:
- empty files produce empty strings
- only these three files are loaded
- `prompts/examples/archive/` is never loaded
- liked/disliked store snippets plus one judgment
- notes stores original sentence, revised sentence, reason

## Scout

Scout is independent from the main forge. It never changes `inputs/idea.md`.

ETL:
- Extract: fetch public sources locally and write `scout/scout_runs/YYYYMMDD_HHMM_raw.json`
- Transform: read only raw snapshot, score, rank, summarize, match tracks
- Load: write `inputs/scout_candidates.md` and archive candidate markdown

Raw snapshots must include:
- generated time
- selected sources
- source status
- raw items with title, summary, data, URL, timestamp, source, tier, track, evidence grade

`source_status` values:
- `ok`: source returned usable candidates
- `empty`: request succeeded but returned no candidates
- `failed`: request or parsing failed; include error
- `incomplete`: returned candidates but required freshness fields are missing

Cowork/Codex Scout mode cannot fetch. It requires:

```bash
python scout/run_scout.py --fetch-only
python scout/run_scout.py --provider codex --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
```

## CLI

Main forge:

```bash
python run.py
python run.py --input my_idea.md
python run.py --provider groq|gemini|anthropic|cowork|codex
python run.py --platform x-thread
python run.py --auto
python run.py --from 03
python run.py --from 03 --dir 20260626_1430
python run.py --from done --dir 20260626_1430
```

`--test` remains as a backward-compatible alias for `--provider gemini`.

Scout:

```bash
python scout/run_scout.py
python scout/run_scout.py --fetch-only
python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
python scout/run_scout.py --provider codex --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
```

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

On breakpoint rerun, update the existing `meta.json` in the selected output directory. Do not create a new checkpoint meta.

Cowork/Codex cannot count tokens; token and cost fields stay `null`.

## Content Philosophy

All generated content must follow:
- conclusion first
- no filler
- no emotional manipulation
- no miracle predictions
- no price targets unless explicitly provided
- data gaps labeled, never hidden
- E-level evidence cannot support the core thesis

Evidence hierarchy:
- A: on-chain data, financial statements, primary data
- B: whitepapers, official documents, earnings call transcripts
- C: institutional research reports
- D: KOL commentary, analyst opinions
- E: market sentiment, narrative trends

When uncertain, preserve uncertainty explicitly.

## File Rules

Do not commit:
- `.env`
- `outputs/`
- `scout/scout_runs/`
- `__pycache__/`
- runtime generated files
- full text stored under `prompts/examples/archive/`

Keep prompts editable markdown. Keep provider names, model names, hard banned words, and config defaults in `config.py`.
