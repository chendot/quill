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
python scout/run_scout.py --provider cowork
```

`--model` overrides the default model from `config.py` for API providers.
Cowork mode fetches and preselects source data, writes a cowork manifest under
`scout/scout_runs/`, then prints the scorer prompt for Claude to complete in the
conversation window.

Default tiers come from `SCOUT_DEFAULT_TIERS` in `.env` and default to `1,2,3`.
Optional sources such as FRED and Google Trends are skipped unless their
credentials or dependencies are available.

## Workflow

1. `python scout/run_scout.py`
2. Open `inputs/scout_candidates.md` and review candidates. `inputs/scout_candidates.example.md` is the tracked sample; the real output file is ignored by git.
3. Pick one topic and manually edit `inputs/idea.md`.
4. Run the normal pipeline: `python run.py --provider groq`
