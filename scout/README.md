# Scout

Scout is an independent topic reconnaissance module. It does not call or modify
the main Quill pipeline.

## Usage

```bash
python scout/run_scout.py
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

## Workflow

1. `python scout/run_scout.py`
2. Open `inputs/scout_candidates.md` and review candidates.
3. Pick one topic and manually edit `inputs/idea.md`.
4. Run the normal pipeline: `python run.py --provider groq`
