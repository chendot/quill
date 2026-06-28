# CLAUDE.md — Claude Entry Point

@AGENTS.md
@SPEC.md

---

## Claude-Specific Instructions

Use `SPEC.md` as the product specification.
Use `AGENTS.md` as the implementation rulebook.

When implementing or modifying this project:
- Do not redesign the architecture unless explicitly asked
- Inspect relevant files before editing
- Run the smallest useful test after each change
- Do not store secrets in code

---

## Cowork Mode

When the user runs `--provider cowork`, Claude is the executor for that pipeline step.

如果当前步骤是 `03_writer`，脚本打印的 user input 顶部会包含：

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

Claude 需要按该平台在 `prompts/03_writer.md` 中的模板输出正文。支持的平台包括：`x-tweet`、`x-thread`、`x-article`、`xhs-text`、`xhs-caption`、`xueqiu`，默认 `x-thread`。

**What the script does:**
Prints the system prompt and user input for the current step, writes metadata, and exits.

**What Claude does:**
1. Read the printed system prompt and input
2. Generate the step output following the content philosophy in `AGENTS.md`
3. Write the result to the correct file: `outputs/<run_id>/0N_<stepname>.md`
4. Update `outputs/<run_id>/meta.json` — record `platform`, and set token fields to `null` for Cowork steps
5. Tell the user the next command to run
6. Stop at HITL checkpoints (after step 02 and step 06) and ask for confirmation before proceeding

**Claude must not:**
- Call any external LLM API
- Skip the hard-rule compliance scan (run `--from done` to trigger it)
- Invent facts, figures, or data not present in the user's input
