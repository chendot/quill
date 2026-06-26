# Quill

Quill is a local, linear AI pipeline that turns a short investment idea into a publishable draft with review notes, compliance checks, and token cost metadata.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with API keys for production or real test-model runs. Without `GEMINI_API_KEY`, `python run.py --test --auto` uses an offline deterministic test response so the project skeleton can be validated end to end.

## Usage

```bash
python run.py
python run.py --input my_idea.md
python run.py --test
python run.py --auto
python run.py --from 03
python run.py --from 03 --dir 20260626_1430
python run.py --test --auto
```

Edit `inputs/idea.md` before each run. Optional supporting facts or links can be placed in `inputs/data.md`.
