# Quill

Quill 是一个本地、线性的**深度长文** investment content forge：输入一段短观点，产出研究底稿、选题报告、正文、审稿、合规检查和成本记录。

定位是深度长文，不做单条推文、配文一类的短内容——短内容如果以后要做，会是独立于本 forge 之外的轻量工具。

设计边界很窄：无 Agent 框架、无数据库、无 Web UI、无自动发布。文件系统就是状态。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

创建 `.env`，按需填写：

```bash
DEFAULT_PROVIDER=groq
DEFAULT_PLATFORM=x-article
GROQ_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
FRED_API_KEY=
USE_PROXY=1
PROXY_URL=http://127.0.0.1:7897
```

优先级：
- provider：`--provider` > `.env DEFAULT_PROVIDER` > `groq`
- platform：`--platform` > `.env DEFAULT_PLATFORM` > `x-article`

## Script Forge

YouTube 脚本使用独立 pipeline：`script_forge/run_script.py`。
它和主 forge 共享 `.env` provider 配置与 `skills/` 判断规则，但有自己的 prompts、
输出目录和时长检查。

```bash
python script_forge/run_script.py
python script_forge/run_script.py --provider groq --auto
python script_forge/run_script.py --provider gemini
python script_forge/run_script.py --provider anthropic
python script_forge/run_script.py --provider codex
python script_forge/run_script.py --from 03 --dir 20260626_1430
python script_forge/run_script.py --from done --dir 20260626_1430
```

输出写入 `video_outputs/YYYYMMDD_HHMM/`，不会混入主 forge 的 `outputs/`。
`script_forge/duration_check.py` 会按语速估算口播时长，并把结果写入
`video_outputs/*/meta.json`。

## 主流程

先编辑 `inputs/idea.md`。如果有人工整理的数据、链接或来源，写入 `inputs/data.md`。

```bash
python run.py
python run.py --provider groq --auto
python run.py --provider gemini
python run.py --provider anthropic
python run.py --from 03 --dir 20260626_1430
python run.py --from 03 --platform wechat
```

执行顺序固定：

```text
01_researcher -> 02_strategist -> 03_writer -> 04_editor -> 05_reviewer -> 06_compliance
```

06 之后同一个最终检查阶段会运行：

```text
forge/compliance.py -> forge/wordcount.py
```

每步只读上一步输出；例外：
- `05_reviewer` 同时读取原始 `idea.md`
- `03_writer` 会收到目标平台 header
- `06_compliance` 读取 reviewer 修订后的正文

输出写入 `outputs/YYYYMMDD_HHMM/`，运行状态写入同目录 `meta.json`。

## 输出平台

`--platform` 只影响 `03_writer` 及后续步骤。支持（仅长文平台）：

```text
x-article, wechat
```

`x-tweet`、`x-thread`、`xhs-text`、`xhs-caption`、`xueqiu` 均不在支持范围内。

平台不是唯一约束。每个平台在 `config.py` 里配了字数区间（`WORD_COUNT_RANGES`），`03_writer` 会同时收到目标平台和目标字数。字数是否达标由 `forge/wordcount.py` 做确定性检查，结果写入 `meta.json`，在 06 之后的 HITL 确认时一并展示，不新增阻断点。

平台模板只放在 `prompts/03_writer.md`，Python 只传入：

```text
目标平台：{platform}，目标字数：{word_count_min}-{word_count_max} 字，请严格按照该平台的格式规范输出，并在目标字数区间内完成。
```

## Examples 参考

`03_writer` 会读取 `prompts/examples/liked.md`、`disliked.md`、`notes.md`，并追加到 system prompt 末尾：

```text
学习判断标准，不要模仿句式。
```

约定：
- `liked.md` / `disliked.md`：只放摘录和一句判断
- `notes.md`：记录“原句 -> 改成 -> 原因”
- `archive/`：完整长文存档，不进入 loader，也不提交正文内容

## Prompt Skills

prompt 里的 `@skills/*.md` 会由 loader 展开到 system prompt 的
`Skill References` 区块。当前共享规则包括：

- `skills/evidence-quality.md`
- `skills/thesis-angle-validation.md`
- `skills/compliance-review.md`
- `skills/expert-lens.md`

`expert-lens.md` 只提供分析透镜和压力测试框架，不是外部事实来源。

## Scout

Scout 是独立话题侦察模块，不进入主 forge。`run_scout.py` 只写候选清单；
显式执行 `prepare_forge_input.py` 时，才会把某个候选整理成
`inputs/idea.md` 和 `inputs/data.md`。

```bash
python scout/run_scout.py --fetch-only
python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
python scout/run_scout.py --provider codex --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
python scout/prepare_forge_input.py --candidate 1 --dry-run
python scout/prepare_forge_input.py --candidate 1
```

ETL 边界：
- Extract：本机联网抓取，写 raw snapshot，不调用 LLM
- Transform：只读 raw snapshot，评分和排序
- Load：写 `inputs/scout_candidates.md` 并归档
- Prepare：从候选中选一条，回查本地 raw snapshot，生成 Forge 输入草稿

Cowork/Codex 的 Scout 模式必须使用 `--from-raw`，不能联网抓取。

## 对话执行模式

`cowork` 和 `codex` 不调用外部 LLM API。命令只准备一个步骤，打印 system prompt 和 user input，然后退出：

```bash
python run.py --provider codex
python run.py --provider codex --from 02 --dir 20260626_1520
python run.py --provider codex --from done --dir 20260626_1520
```

对话侧 assistant 负责写入输出文件、更新 `meta.json`，并在步骤 02 和 06 后进行 HITL 确认。

## 文档分工

- `README.md`：日常使用入口
- `SPEC.md`：产品行为源头
- `AGENTS.md`：开发约束和协作规则
- `skills/*.md`：跨 prompt 的可复用判断标准
