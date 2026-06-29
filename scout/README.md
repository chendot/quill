# Scout

Scout is an independent topic reconnaissance module. It does not call or modify
the main Quill pipeline.

## Usage

```bash
python scout/run_scout.py
python scout/run_scout.py --tier 1
python scout/run_scout.py --tier 1,3
python scout/run_scout.py --sources defillama,eastmoney
python scout/run_scout.py --top 5
python scout/run_scout.py --provider groq
python scout/run_scout.py --provider gemini --model gemini-2.5-flash
python scout/run_scout.py --provider anthropic --model claude-sonnet-4-6
python scout/run_scout.py --fetch-only
python scout/run_scout.py --from-raw scout/scout_runs/20260629_1430_raw.json
python scout/run_scout.py --provider cowork --from-raw scout/scout_runs/20260629_1430_raw.json
```

`--model` overrides the default model from `config.py` for API providers.

Scout follows an Extract -> Transform -> Load flow:

- Extract: `--fetch-only` fetches source data on the local machine and writes a
  raw snapshot under `scout/scout_runs/YYYYMMDD_HHMM_raw.json`.
- Transform: `--from-raw <snapshot>` scores and ranks candidates using only that
  snapshot as input. Without an explicit `--provider`, this uses deterministic
  local rules so repeated runs of the same snapshot produce the same candidate
  file.
- Load: scored candidates are written to `inputs/scout_candidates.md` and
  archived under `scout/scout_runs/`.

Default `python scout/run_scout.py` still runs fetch + API score in one command
for local usage. `--from-raw --provider groq|gemini|anthropic` can use an API
model for scoring, but deterministic reruns should omit `--provider`. Cowork
mode never performs network fetches; it requires `--from-raw`, writes a cowork
manifest under `scout/scout_runs/`, then prints the scorer prompt for Claude to
complete in the conversation window.

Default tiers come from `SCOUT_DEFAULT_TIERS` in `.env` and default to `1,2,3`.
Optional sources such as FRED and Google Trends are skipped unless their
credentials or dependencies are available.

Scout source fetches use the shared proxy settings from `config.py`. By default
they use `http://127.0.0.1:7897`; set `PROXY_URL` to change it or `USE_PROXY=0`
to disable proxying. Shell proxy variables are ignored unless `USE_ENV_PROXY=1`
is set, which keeps sandbox-provided `localhost` proxies from overriding the
local Clash endpoint.

## Workflow

1. `python scout/run_scout.py --fetch-only`
2. `python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
   or `python scout/run_scout.py --provider cowork --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
3. Open `inputs/scout_candidates.md` and review candidates. `inputs/scout_candidates.example.md` is the tracked sample; the real output file is ignored by git.
4. Pick one topic and manually edit `inputs/idea.md`.
5. Run the normal pipeline: `python run.py --provider groq`
