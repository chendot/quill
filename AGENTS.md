# AGENTS.md — Quill Development Rules

Quill 是一个本地、线性的内容 forge，用短投资观点生成可发布草稿。

**SPEC.md 是产品行为的唯一来源。不要静默改变它的设计假设。**

## 架构边界

必须保持：
- 线性流程，无分支编排
- 无 LangChain / CrewAI / LangGraph
- 无数据库；文件系统即状态
- prompts 存在 `prompts/*.md`
- 每步写独立输出文件
- 支持 `--from` 断点续跑
- 支持 API / Cowork / Codex 模式
- 支持 `--platform`

禁止引入：
- Agent 框架或多 agent 并发
- Vector DB 或数据库状态
- Web UI、自动发布、主流程 web search
- Python 内隐藏业务 prompt 生成（SPEC 规定的平台字数 header 与 `@skills` 展开除外）
- API key、模型名、敏感词散落在 `config.py` 之外
- runtime 输出进入 git

## 主流程

固定顺序：

```text
01_researcher -> 02_strategist -> 03_writer -> 04_editor -> 05_reviewer -> 06_compliance
```

06 之后同一个最终检查阶段运行：

```text
forge/compliance.py -> forge/wordcount.py
```

输入规则：
- 每个 LLM step 默认只接收上一步输出
- `05_reviewer` 额外接收原始 `inputs/idea.md`
- `03_writer` 额外接收平台和字数 header：`目标平台：{platform}，目标字数：{word_count_min}-{word_count_max} 字，请严格按照该平台的格式规范输出，并在目标字数区间内完成。`
- `06_compliance` 接收 `05_reviewer` 修订后的正文，不接收 review report

HITL：
- API mode：步骤 02 和 06 后 `input()` 阻塞；`--auto` 跳过
- Cowork/Codex：Python 不阻塞，由对话侧确认

## 内容规则

核心规则已抽到 skills：
- `skills/evidence-quality.md`
- `skills/thesis-angle-validation.md`
- `skills/compliance-review.md`
- `skills/expert-lens.md`

所有内容必须遵守：
- 结论先行，无 filler
- 不编造事实、日期、数字、价格、百分比
- 不做价格预测，除非用户在 `idea.md` 明确提供
- 数据缺口必须标注
- E 级证据不能支撑核心论点
- 不使用情绪煽动、焦虑营销、神棍预测

Researcher 只能分类证据质量、识别数据缺口、标记缺失来源，不能主动补事实。

合规分两层，不能合并：
- `prompts/06_compliance.md`：LLM 语气和监管风险判断
- `forge/compliance.py`：纯 Python 硬规则扫描
- `forge/wordcount.py`：纯 Python CJK 字符数检查

## Platform

支持：

```text
x-article, wechat
```

优先级：CLI `--platform` > `.env DEFAULT_PLATFORM` > `x-article`。

平台模板只允许存在于 `prompts/03_writer.md`。Python 可以传平台名，不能硬编码平台内容模板。
字数区间只从 `config.WORD_COUNT_RANGES` 读取，属于运行时数值参数，不属于平台内容模板。

## Provider

支持：

```text
groq, gemini, anthropic, cowork, codex
```

优先级：CLI `--provider` > `.env DEFAULT_PROVIDER` > `groq`。

`cowork` / `codex` 不是外部 LLM provider。它们只让脚本打印当前 step 的 system prompt 和 user input，由对话侧 assistant 执行并写文件。token 和 cost 字段保持 `null`。

## Scout

Scout 是独立 ETL，不属于主流程：
- Extract：本机抓取公开数据，写 `scout/scout_runs/YYYYMMDD_HHMM_raw.json`
- Transform：只读 raw snapshot，评分和排序
- Load：写 `inputs/scout_candidates.md` 并归档
- Prepare：显式选择候选，回查本地 raw snapshot，写 `inputs/idea.md` 和 `inputs/data.md`

要求：
- source adapter 必须先做硬过滤，不能把低质量全量 payload 丢给 scorer
- `source_status` 使用 `ok` / `empty` / `failed` / `incomplete`
- Cowork/Codex Scout 禁止联网，必须先本机 `--fetch-only`，再 `--from-raw`
- Prepare 不联网，不新增事实，只整理本地候选和 raw snapshot

## Examples

`prompts/examples/` 只给 `03_writer` 学习判断标准：
- `liked.md`：好例子摘录 + 一句判断
- `disliked.md`：反例摘录 + 一句判断
- `notes.md`：原句 -> 改成 -> 原因
- `archive/`：完整长文存档，不进入 loader

不要把完整外部文章放入被 loader 读取的三个 md 文件。

## Metadata 和输出

每次运行维护 `outputs/YYYYMMDD_HHMM/meta.json`。断点续跑必须更新目标目录已有 meta，不新建 checkpoint meta。

必要字段：

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

不要提交 `.env`、`outputs/`、`scout/scout_runs/`、`__pycache__/`、`prompts/examples/archive/*`。

## Coding Style

- 小函数，副作用集中在 `forge/writer.py`、`forge/runner.py`、`run.py`
- 配置只从 `config.py` 读取，不在 forge 代码直接读 `.env`
- 异常信息要可行动
- 不做无关重构
- 重要改动先看后写；每个改动独立 commit

开发优先级：先证明文件流程，再优化 prompt 和 provider 质量。
