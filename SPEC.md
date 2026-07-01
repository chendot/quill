# Quill — Product Spec

Quill turns a short investment idea into a publishable **long-form** draft through a local, file-based forge.

Quill is scoped to deep long-form content only. Short-form output (single tweets, captions, digest-style posts) is explicitly out of scope for the main forge — see Non-goals and Platform System.

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
- word-count check results
- token/cost metadata

Non-goals:
- no Agent framework
- no database or vector store
- no Web UI
- no auto-publishing
- no main-forge web search
- no multi-agent concurrency
- no short-form/single-post generation (single tweets, captions, digest posts) — deep long-form only; short-form output, if built, lives in a separate lightweight tool outside this forge

## Project Map

```text
run.py                    main CLI
config.py                 keys, provider/model/platform config, hard-rule words
forge/                    shared loader, writer, runner, deterministic checks
script_forge/             YouTube script pipeline（独立 agent contracts）
prompts/                  editable agent prompts
prompts/examples/         writer reference snippets
skills/                   reusable prompt rules
inputs/                   human-edited inputs and Scout candidates
outputs/YYYYMMDD_HHMM/    runtime outputs and meta.json
video_outputs/YYYYMMDD_HHMM/  script forge runtime outputs
scout/                    independent topic reconnaissance ETL
```

Runtime outputs are not git-tracked.

## Main Forge

Execution order is fixed:

```text
01_researcher -> 02_strategist -> 03_writer -> 04_editor -> 05_reviewer -> 06_compliance
```

After `06_compliance`, deterministic Python checks run in the same finalization
stage:

```text
forge/compliance.py -> forge/wordcount.py
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
| forge/wordcount.py | deterministic word-count check against platform range | `meta.json word_count_actual`, `word_count_in_range` |

Shared judgment rules live in:
- `skills/evidence-quality.md`
- `skills/thesis-angle-validation.md`
- `skills/compliance-review.md`
- `skills/expert-lens.md`

When a prompt references `@skills/*.md`, the prompt loader appends the referenced
skill content to the system prompt under a visible `Skill References` section.

## Platform System

Supported platforms (long-form only):

```text
x-article, wechat
```

All other platforms previously listed (`x-tweet`, `x-thread`, `xhs-text`, `xhs-caption`, `xueqiu`) are removed from main-forge scope. Any future short-form or additional-platform tool is a separate, independent utility and must not be added to this list without a corresponding SPEC change.

Priority:

```text
CLI --platform > .env DEFAULT_PLATFORM > x-article
```

Only `prompts/03_writer.md` may contain platform templates. Python may pass the selected platform but must not hardcode platform content.

For writer steps, prepend this to the user message:

```text
目标平台：{platform}，目标字数：{word_count_min}-{word_count_max} 字，请严格按照该平台的格式规范输出，并在目标字数区间内完成。
```

## Word Count Range

Platform alone does not guarantee long-form depth — word count is the deterministic proxy that main forge actually enforces.

Each supported platform has a required word-count range, defined in `config.py`:

```python
WORD_COUNT_RANGES = {
    "x-article": (1200, 3000),
    "wechat": (1800, 4000),
}
```

These are placeholder anchors and must be confirmed against actual platform norms before relying on them.

Rules:
- Word count is measured as character count (CJK character count), not tokenized word count, since primary output language is Chinese
- Count excludes markdown syntax and leading/trailing whitespace
- The target range is passed into the `03_writer` user message (see Platform System above); it is not a platform template and does not violate the "only 03_writer.md contains platform templates" rule, since it is a numeric parameter, not format content
- A deterministic check runs after `06_compliance`, alongside `forge/compliance.py`'s hard-rule scan, and records the actual character count and in-range status into `meta.json`
- Out-of-range results do not block automatically; they surface as additional information at the existing HITL checkpoint after `06_compliance` ("confirm final publish readiness"). No new checkpoint is introduced.

`meta.json` gains three fields:

```json
{
  "word_count_target": [1200, 3000],
  "word_count_actual": 0,
  "word_count_in_range": null
}
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

## Script Forge

YouTube Script Forge is a separate pipeline under Quill.

It shares judgment skills with Main Forge but has independent agent contracts,
output schema, prompt directory, and duration checks. It does not add a
`youtube-script` platform to Main Forge.

Run it through:

```bash
python script_forge/run_script.py
python script_forge/run_script.py --provider groq --auto
python script_forge/run_script.py --provider codex
python script_forge/run_script.py --from done --dir YYYYMMDD_HHMM
```

Execution order is fixed:

```text
01_researcher -> 02_script_strategist -> 03_outline_beats -> 04_script_writer -> 05_script_editor -> 06_script_reviewer -> 07_compliance
```

After `07_compliance`, `script_forge/duration_check.py` estimates spoken
duration and writes `target_duration_sec`, `estimated_duration_sec`,
`duration_in_range`, and `speech_rate_cpm` into `video_outputs/*/meta.json`.

`speech_rate_cpm` and `target_duration_sec` are placeholder anchors; confirm
against actual recorded pacing before relying on them.

Main Forge is not modified by Script Forge. Pending stabilization,
`script_forge/` and `forge/` may be reorganized into a unified `pipelines/`
structure. No timeline is committed.

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

Scout is independent from the main forge. `scout/run_scout.py` never changes
`inputs/idea.md` or `inputs/data.md`; the explicit prepare command may write
those files after selecting one candidate.

ETL:
- Extract: fetch public sources locally and write `scout/scout_runs/YYYYMMDD_HHMM_raw.json`
- Transform: read only raw snapshot, score, rank, summarize, match tracks
- Load: write `inputs/scout_candidates.md` and archive candidate markdown

Prepare:
- `python scout/prepare_forge_input.py --candidate N` selects one Scout
  candidate, enriches it from local raw snapshots, and writes
  `inputs/idea.md` plus `inputs/data.md` for the main forge
- Prepare is local and does not fetch new facts from the network
- Prepare backs up existing `inputs/idea.md` and `inputs/data.md` before writing

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
python run.py --platform x-article
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
python scout/prepare_forge_input.py --candidate 1
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
  "platform": "x-article",
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "estimated_cost_usd": 0.0,
  "hard_rule_hits": [],
  "word_count_target": [1200, 3000],
  "word_count_actual": 0,
  "word_count_in_range": null,
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
- expert lenses are explanation frameworks, not external fact sources

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
