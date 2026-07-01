# Scout

Scout is an independent topic reconnaissance module. It does not call or modify
the main Quill forge.

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
python scout/run_scout.py --provider codex --from-raw scout/scout_runs/20260629_1430_raw.json
python scout/prepare_forge_input.py --candidate 1
python scout/prepare_forge_input.py --candidate 1 --dry-run
python scout/prepare_forge_input.py --candidate 1 --platform wechat
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
- Prepare: `prepare_forge_input.py` selects one candidate, enriches it from
  local raw snapshots, and writes `inputs/idea.md` plus `inputs/data.md` for the
  main forge. It does not fetch new facts from the network.

Default `python scout/run_scout.py` still runs fetch + API score in one command
for local usage. `--from-raw --provider groq|gemini|anthropic` can use an API
model for scoring, but deterministic reruns should omit `--provider`.
Cowork/Codex mode never performs network fetches; it requires `--from-raw`,
writes a provider-specific manifest under `scout/scout_runs/`, then prints the
scorer prompt for the assistant to complete in the conversation window.

Default tiers come from `SCOUT_DEFAULT_TIERS` in `.env` and default to `1,2,3`.
Optional sources such as FRED and Google Trends are skipped unless their
credentials or dependencies are available.

## Extract Quality Guards

The fetch layer performs source-specific hard filtering before writing the raw
snapshot. The raw snapshot should be a scoring-ready candidate pool, not a full
source dump.

- arXiv queries `cs.AI` and `q-fin.*` separately, deduplicates papers, and keeps
  papers in the 48-hour window relative to the newest arXiv submission returned
  by the API.
- DefiLlama filters by TVL, absolute 7-day TVL change, and a category allowlist.
  Defaults aim for roughly 30-50 high-signal protocols.
- Polymarket filters out low-volume markets and requires `volume_24h`; retained
  rows include 24h probability change, total volume, and liquidity.
- GitHub Trending drops rows without `stars_today`.
- FRED stores `observation_date` for freshness checks.

Each `raw.json` contains `source_status` rows with `status` set to `ok`,
`empty`, `failed`, or `incomplete`. A source that returns zero rows is `empty`,
not `ok`; a source with missing freshness fields is `incomplete`.

Useful `.env` overrides:

```bash
SCOUT_DEFILLAMA_MIN_TVL_USD=1000000
SCOUT_DEFILLAMA_MIN_ABS_CHANGE_7D=20
SCOUT_DEFILLAMA_MAX_ITEMS=45
SCOUT_DEFILLAMA_CATEGORY_ALLOWLIST=Lending,DEX,Derivatives,RWA,Stablecoin,Bridge,Yield Aggregator,Prediction Market
SCOUT_POLYMARKET_MIN_VOLUME_USD=1000
SCOUT_POLYMARKET_MIN_LIQUIDITY_USD=1000
SCOUT_POLYMARKET_MAX_ITEMS=20
```

Scout source fetches use the shared proxy settings from `config.py`. By default
they use `http://127.0.0.1:7897`; set `PROXY_URL` to change it or `USE_PROXY=0`
to disable proxying. Shell proxy variables are ignored unless `USE_ENV_PROXY=1`
is set, which keeps sandbox-provided `localhost` proxies from overriding the
local Clash endpoint.

## Workflow

1. `python scout/run_scout.py --fetch-only`
2. `python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
   or `python scout/run_scout.py --provider cowork --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
   or `python scout/run_scout.py --provider codex --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
3. Open `inputs/scout_candidates.md` and review candidates. `inputs/scout_candidates.example.md` is the tracked sample; the real output file is ignored by git.
4. Preview a Forge-ready material package:
   `python scout/prepare_forge_input.py --candidate 1 --dry-run`
5. Prepare `inputs/idea.md` and `inputs/data.md`:
   `python scout/prepare_forge_input.py --candidate 1`
6. Review or lightly edit the prepared inputs.
7. Run the normal forge: `python run.py --provider groq`

`prepare_forge_input.py` creates timestamped backups under
`inputs/prepared_backups/` before overwriting `inputs/idea.md` and
`inputs/data.md`. Use `--raw scout/scout_runs/YYYYMMDD_HHMM_raw.json` when you
want to force enrichment from a specific snapshot.
