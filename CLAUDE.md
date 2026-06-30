# CLAUDE.md — Claude Entry Point

@AGENTS.md
@SPEC.md

Use `SPEC.md` for product behavior and `AGENTS.md` for implementation rules.

## General

- Inspect relevant files before editing.
- Do not redesign architecture unless explicitly asked.
- Run the smallest useful test after changes.
- Do not store secrets in code.

## Cowork Mode

`--provider cowork` means Claude executes exactly one prepared forge step.

The script prints:
- system prompt
- user input
- output path
- next command

Claude must:
1. Follow the printed prompt and `AGENTS.md`
2. Write `outputs/<run_id>/0N_<stepname>.md`
3. Update `outputs/<run_id>/meta.json`
4. Keep token and cost fields `null`
5. Stop for HITL after steps 02 and 06

Claude must not:
- call external LLM APIs
- invent facts or data
- skip final hard-rule scan; use `--from done`

For `03_writer`, the user input starts with:

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

Use the matching template in `prompts/03_writer.md`.

## Codex Mode

`--provider codex` follows the same handoff pattern. The manifest is `outputs/<run_id>/.codex_step.json`; Codex writes the output file and updates `meta.json`.
