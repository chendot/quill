# Quill

Quill is a local, linear AI pipeline that turns a short investment idea into a publishable draft with review notes, compliance checks, and token cost metadata.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local `.env` file with the API keys you need and optional `DEFAULT_PROVIDER`. Provider priority is `--provider` > `DEFAULT_PROVIDER` > `groq`.

## Usage

```bash
python run.py
python run.py --input my_idea.md
python run.py --provider groq
python run.py --provider gemini
python run.py --provider anthropic
python run.py --test  # legacy; prefer --provider gemini
python run.py --auto
python run.py --from 03
python run.py --from 03 --dir 20260626_1430
python run.py --provider groq --auto
```

Edit `inputs/idea.md` before each run. Optional supporting facts or links can be placed in `inputs/data.md`.
