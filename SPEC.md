# Quill — Content Agent Pipeline
> 把投资观点提炼成可发布内容的本地 AI pipeline

---

## 项目目标

输入：一段原始投资观点（100 字以内）+ 可选的补充数据文件
输出：可直接发布的内容草稿（标题 + 正文 + 合规检查报告 + token 成本统计）

设计原则：
- 线性 pipeline，不用 Agent 框架
- 每步输出单独存文件，支持断点重跑
- Prompt 完全可控，存于独立 md 文件
- 内容哲学优先于自动化效率
- Researcher 不捏造事实，只标注数据缺口
- 合规检查双轨：规则函数兜底 + LLM 语气风险判断
- 支持两种运行模式：**API 模式**（调用外部 LLM provider）和 **Cowork 模式**（Claude 原生执行，无需额外 API 调用）
- 支持通过 `--platform` 指定正文输出平台，默认 `x-thread`
- 可选独立 Scout 模块用于发现候选话题，但不进入主 pipeline、不自动改写 idea.md

---

## 项目结构

```
quill/
├── SPEC.md                  # 本文件，Codex 的唯一输入
├── README.md                # 项目说明
├── .env                     # API keys（不进 git）
├── .gitignore               # 排除 .env / outputs/ / __pycache__/
├── config.py                # 模型参数、路径配置，从 .env 读取
├── run.py                   # 主流程入口
├── pipeline/
│   ├── __init__.py
│   ├── runner.py            # 单个 agent 调用逻辑 + token 统计
│   ├── loader.py            # prompt 文件读取
│   ├── writer.py            # 输出文件写入
│   └── compliance.py        # 硬性敏感词规则函数（不调 LLM）
├── prompts/
│   ├── 01_researcher.md     # Agent 1：数据缺口标注（不编造事实）
│   ├── 02_strategist.md     # Agent 2：选题判断
│   ├── 03_writer.md         # Agent 3：正文生成
│   ├── 04_editor.md         # Agent 4：风格润色
│   ├── 05_reviewer.md       # Agent 5：逻辑校验（含原始 idea）
│   └── 06_compliance.md     # Agent 6：语气风险判断（LLM）
├── inputs/
│   ├── idea.md              # 用户输入核心观点，每次运行前手动编辑
│   ├── data.md              # 可选：用户手动填入的真实数据/链接
│   ├── scout_candidates.example.md  # Scout 候选话题样例，可进 git
│   └── scout_candidates.md          # Scout 运行输出，每次运行覆盖，不进 git
├── outputs/                 # 自动生成，不进 git
│   └── YYYYMMDD_HHMM/
│       ├── 01_research.md
│       ├── 02_strategy.md
│       ├── 03_draft.md
│       ├── 04_edited.md
│       ├── 05_reviewed.md
│       ├── 06_final.md      # 最终稿，人工确认后发布
│       └── meta.json        # token 统计、费用、运行参数
├── scout/                   # 独立话题侦察模块，不属于主 pipeline
│   ├── __init__.py
│   ├── run_scout.py         # Scout CLI 入口
│   ├── scorer.py            # LLM 筛选和评分
│   ├── writer.py            # 写入候选话题文件和归档
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── http.py          # 轻量 JSON 请求 helper
│   │   ├── tier1_primary/   # 一手信息源
│   │   │   ├── arxiv.py
│   │   │   ├── github_trending.py
│   │   │   └── huggingface_papers.py
│   │   ├── tier2_community/ # 专业人士讨论区
│   │   │   └── hackernews.py
│   │   ├── tier3_data/      # 数据平台
│   │   │   ├── defillama.py
│   │   │   ├── eastmoney.py
│   │   │   ├── fred.py
│   │   │   └── polymarket.py
│   │   ├── tier4_trends/
│   │   │   └── google_trends.py
│   │   └── tier5_social/
│   │       └── hackernews_hot.py
│   └── scout_runs/          # Scout 历史归档，不进 git
└── requirements.txt
```

---

## 技术栈

- Python 3.10+
- `anthropic` SDK（正式内容生产）
- `google-genai` SDK（测试阶段）
- `groq` SDK（默认快速测试 provider）
- `python-dotenv`（环境变量管理）
- `click`（CLI 参数）
- Scout 数据源请求使用轻量 HTTP 请求；优先使用 `requests`，不可用时回退到标准库
- 无 LangChain / CrewAI / LangGraph，纯函数式 pipeline
- 无数据库，文件系统即状态

---

## Pipeline 定义

### 数据流

```
inputs/idea.md + inputs/data.md（可选）
    → 01_researcher   → outputs/01_research.md
    → 02_strategist   → outputs/02_strategy.md
    → 03_writer       → outputs/03_draft.md
    → 04_editor       → outputs/04_edited.md
    → 05_reviewer     → outputs/05_reviewed.md   ← 同时接收原始 idea.md
    → 06_compliance   → outputs/06_final.md
    → compliance.py   → 硬性敏感词规则扫描（叠加在 06 之上）
                               ↓
                        [HITL：人工确认]
                               ↓
                          手动发布
```

每个 agent 的输入 = 上一步的输出（保持 context 干净）。
例外：05_reviewer 同时接收上一步输出 + 原始 idea.md，用于校验内容是否偏离初衷。
例外：03_writer 的 user message 头部会额外注入 `--platform` 选择：

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

### Agent 职责

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| 01 Researcher | **只标注数据缺口和证据等级要求，不补充事实，不捏造数字** | idea.md + data.md | 缺口清单 + 证据等级标注 |
| 02 Strategist | 判断选题价值、确定目标平台、提炼核心论点、生成3个标题候选 | research | 选题报告 + 标题候选 |
| 03 Writer | 按平台模板生成正文初稿 | strategy | 正文草稿 |
| 04 Editor | 压缩冗余、增强表达、调整语气风格 | draft | 润色后正文 |
| 05 Reviewer | 检查逻辑跳跃、论点支撑、反直觉验证、核查是否偏离原始观点 | edited + idea.md | 审稿报告 + 修订建议 |
| 06 Compliance | **语气风险判断**（LLM）：过度承诺、情绪化、焦虑营销 | reviewed | 语气风险报告 + 替代词建议 |
| compliance.py | **硬性敏感词扫描**（规则函数）：稳赚/翻倍/荐股等 | 06_final | 命中词列表 + 位置标注 |

---

## 输出平台

`--platform` 控制 `03_writer` 生成正文初稿时使用的平台格式。支持值：

| platform | 用途 |
|----------|------|
| `x-tweet` | X 单条推文 |
| `x-thread` | X 线程，默认主格式 |
| `x-article` | X 长文 |
| `xhs-text` | 小红书纯文字 |
| `xhs-caption` | 小红书配图说明 |
| `xueqiu` | 雪球长文 |
| `wechat` | 微信公众号长文 |

默认值从 `config.DEFAULT_PLATFORM` 读取；`config.DEFAULT_PLATFORM` 默认读取 `.env` 的 `DEFAULT_PLATFORM`，未配置时为 `x-thread`。

Platform 优先级：`--platform` 命令行参数 > `.env` 中的 `DEFAULT_PLATFORM` > 默认 `x-thread`。

平台模板只保存在 `prompts/03_writer.md`，Python 代码只负责传入目标平台，不把具体模板硬编码进 runner。

## HITL 节点

| 节点 | 介入方式 | 原因 |
|------|----------|------|
| 运行前 | 手动编辑 inputs/idea.md | 核心观点必须来自人，不能生成 |
| 02 之后 | 确认选题和标题 | 方向错了后续全部浪费 |
| 06 之后 | 手动发布 | 发布不可逆，合规风险由人承担 |

**API 模式**：`input()` 阻塞等待，输入 `y` 继续，`n` 终止并保留已有输出。`--auto` flag 跳过所有 HITL（仅测试用）。

**Cowork 模式**：脚本不阻塞，HITL 在 Cowork 对话中进行。步骤 02 完成后 Claude 向用户展示选题报告和标题候选，用户在对话中确认后 Claude 继续运行下一步；步骤 06 完成后 Claude 展示最终稿，由用户决定是否发布。

---

## CLI 接口

**API 模式**（调用外部 LLM provider）：
```
python run.py                              # 默认：idea.md，groq provider，HITL 开启
python run.py --input my_idea.md           # 指定输入文件
python run.py --provider groq              # 使用 Groq（默认快速测试）
python run.py --provider gemini            # 使用 Gemini
python run.py --provider anthropic         # 使用 Anthropic（正式生产）
python run.py --test                       # 兼容旧参数；请优先使用 --provider gemini
python run.py --auto                       # 跳过所有 HITL（测试用）
python run.py --platform x-tweet           # 按单条推文格式生成 03_draft.md
python run.py --platform x-thread          # 按 X 线程格式生成；默认值
python run.py --platform xhs-text          # 按小红书纯文字格式生成
python run.py --platform wechat            # 按微信公众号长文格式生成
python run.py --from 03                    # 从第3步断点续跑（默认最新目录）
python run.py --from 03 --dir 20260626_1430  # 指定目录断点续跑
python run.py --from 03 --platform xueqiu  # 续跑时改用雪球格式，覆盖后续输出
python run.py --provider groq --auto       # 组合：Groq + 无 HITL，最快调试
```

**Cowork 模式**（Claude 原生执行，在 Cowork 对话中调用）：
```
python run.py --provider cowork            # 准备步骤 01，打印 prompt+input，退出
python run.py --provider cowork --from 02 --dir 20260626_1520  # 续跑步骤 02
python run.py --provider cowork --from 03 --dir 20260626_1520 --platform xhs-caption # 用小红书配图说明格式准备步骤 03
python run.py --provider cowork --from done --dir 20260626_1520 # 所有步骤完成后运行合规扫描
```
Cowork 模式每次调用只处理一个步骤：脚本打印当前步骤的 system prompt 和 user input，由 Claude 生成输出并写入文件，再调用下一步命令。HITL 在对话中处理，脚本不阻塞。

Provider 优先级：`--provider` 命令行参数 > `.env` 中的 `DEFAULT_PROVIDER` > 默认 `groq`。
Platform 优先级：`--platform` 命令行参数 > `.env` 中的 `DEFAULT_PLATFORM` > 默认 `x-thread`。

---

## Scout 话题侦察模块

Scout 是一个可选的、独立运行的话题发现工具，用于把公开数据源中的异常变化整理成候选选题。它不是主 pipeline 的一个步骤，不改变 `run.py` 的线性执行顺序，也不会自动写入 `inputs/idea.md`。

### 设计边界

- 主 pipeline 不 import Scout，Scout 不改变主 pipeline 的执行顺序或状态；Scout 可复用 `pipeline/loader.py`、`pipeline/runner.py` 中的通用 prompt/LLM helper。
- Scout 输出只写入 `inputs/scout_candidates.md`，供人阅读和筛选；该文件是运行产物，不进 git。
- 用户必须手动把选中的候选改写进 `inputs/idea.md`，再运行主 pipeline。
- Scout 可以访问指定公开 API；这不改变 01 Researcher 的约束。Researcher 仍然不能主动 web search 或编造数据。
- 数据源失败不能中断整体运行；输出文件中标注“数据源不可用”或评分 fallback 原因。
- `scout/scout_runs/` 保存每次候选文件归档，但不进 git。

### 运行方式

```
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

Scout provider 优先级：`--provider` 命令行参数 > `.env` 中的 `DEFAULT_PROVIDER` > 默认 `groq`。支持 `groq` / `gemini` / `anthropic` 作为 API 评分 provider，也支持 `cowork` 由 Claude 在当前对话中直接评分。

`--model` 可覆盖所选 API provider 的默认模型；不传时复用 `config.py` 的 `PROVIDER_MODELS`。

`--sources` 显式指定具体数据源时优先级最高；不传 `--sources` 时，`--tier` 选择一个或多个层级；两者都不传时使用 `config.SCOUT_DEFAULT_TIERS`。

`scout/run_scout.py` 可以在未激活虚拟环境时自动切换到项目 `.venv/bin/python`，以复用项目安装的 SDK 和 `.env` 配置。

### Scout ETL 分层

Scout 采用 Extract → Transform → Load：

- Extract：`--fetch-only` 只联网抓取数据源，写入 `scout/scout_runs/YYYYMMDD_HHMM_raw.json`，不调用任何 LLM。
- Transform：`--from-raw <snapshot>` 只读取 raw snapshot，执行评分、排序、赛道匹配，不再访问数据源。未显式传 `--provider` 时使用本地规则评分，以保证同一 snapshot 重跑产出一致。
- Load：评分结果写入 `inputs/scout_candidates.md`，并归档到 `scout/scout_runs/YYYYMMDD_HHMM_candidates.md`。

默认 `python scout/run_scout.py` 保留本机 API 模式的一步式体验：先写 raw snapshot，再使用配置的 API provider 评分并落盘候选。若要从 snapshot 做可复现重跑，使用 `python scout/run_scout.py --from-raw <snapshot>`；若明确接受模型评分的不确定性，可传 `--from-raw <snapshot> --provider groq|gemini|anthropic`。

Raw snapshot 是评分阶段的唯一输入，必须包含抓取时间、数据源列表、各源成功/失败状态，以及原始候选的标题、摘要、结构化数据、链接、时间戳、来源、层级、赛道和证据等级。

抓取层必须先做质量控制，不把全量原始转储交给评分器。每个源需要在自己的 adapter 中完成领域硬过滤，并保证 `config.SCOUT_FRESHNESS_FIELD` 定义的核心热度字段不为空；缺失时该源在 `source_status` 中标记为 `incomplete`。

`source_status` 字段规则：

- `ok`：源成功返回候选，且核心热度字段完整。
- `empty`：请求成功但返回 0 条候选，不能标记为 ok。
- `failed`：请求或解析异常，必须附带 error。
- `incomplete`：返回候选但部分候选缺少核心热度字段。

### Cowork 模式

```
python scout/run_scout.py --provider cowork --from-raw scout/scout_runs/20260629_1430_raw.json
```

Cowork 模式禁止执行联网抓取。若未传 `--from-raw`，脚本必须报错并提示先在本机运行 `--fetch-only` 生成 raw snapshot。拿到 raw snapshot 后，脚本会：

1. 写入 `scout/scout_runs/YYYYMMDD_HHMM_cowork.json`
2. 打印 Scout scorer 的 system prompt 和 user input
3. 指明需要覆盖写入的 `inputs/scout_candidates.md`
4. 指明需要同步写入的归档文件路径

Claude 在当前对话中根据打印的 prompt 直接完成评分和文件写入。Cowork 模式不阻塞 Python，也不自动进入主 pipeline。

### 信息源分层

| Tier | 类型 | 已实现数据源 |
|------|------|--------------|
| Tier 1 | 一手信息源 | arXiv、GitHub Trending、Hugging Face Papers |
| Tier 2 | 专业人士讨论区 | Hacker News |
| Tier 3 | 数据平台 | DefiLlama、Polymarket、FRED、Eastmoney |
| Tier 4 | 趋势发现 | Google Trends |
| Tier 5 | 社交热点 | Hacker News Hot |

默认启用源：arXiv、GitHub Trending、Hugging Face Papers、Hacker News、DefiLlama、Polymarket、FRED。

默认关闭 / 可选源：Eastmoney、Google Trends、Hacker News Hot。FRED 需要 `FRED_API_KEY`；未配置时会返回 empty 并在 `source_status` 中标注。Google Trends 需要安装 `pytrends`，被限速或未安装时跳过并在输出中标注不可用。

暂不实现：Glassnode、Reddit。

所有选中的数据源并发抓取，总超时 60 秒。单个数据源失败不终止整体流程，输出文件中标注 `[数据源不可用]`。

### 数据源规格

| Source | API | 抓取规则 | 输出字段 |
|--------|-----|----------|----------|
| arXiv | `http://export.arxiv.org/api/query` | 分别抓 `cs.AI` 和 `q-fin.*`，按 arXiv 返回的最新提交时间回看 48 小时，去重后取最新 20 篇 | 标题、作者、摘要前 200 字、提交时间、链接 |
| GitHub Trending | `https://github.com/trending?since=daily` | 今日 trending，缺少 `stars_today` 的条目剔除，取前 20 | repo 名、描述、star 数、今日新增 star、语言、链接、抓取日期 |
| Hacker News | Firebase topstories + item API | topstories 前 30 条，内部最多 5 并发 | 标题、分数、评论数、链接、发布时间 |
| Hugging Face Papers | `https://huggingface.co/papers/rss.xml` | 今日推荐论文，取前 20 | 标题、作者、摘要前 200 字、提交时间、链接 |
| DefiLlama | `https://api.llama.fi/protocols` | TVL、7日变化和类别白名单硬过滤，默认输出约 30-50 条，不做全量转储 | 协议名、当前 TVL、7日变化%、所属链、类别 |
| Polymarket | `https://gamma-api.polymarket.com/markets?limit=100&order=volume&ascending=false` | 概率在 `[0.15, 0.85]`，且 `volume_24h` 达到阈值；低成交量或缺热度字段的市场剔除 | 市场名称、当前概率、24h 概率变化、24h 成交量、总成交量、流动性 |
| FRED | `https://api.stlouisfed.org/fred/series/observations` | FEDFUNDS、DGS10、DTWEXBGS、CPIAUCSL 最新值和约 30 日变化 | 指标名、最新值、观测日期、30 日变化 |
| Google Trends | pytrends | Bitcoin、AI agent、gold、interest rate、DeFi，过去 7 天 | 趋势分数、7 日变化 |

### Scorer

`scout/scorer.py` 先对原始候选做轻量预筛，避免低限额模型一次接收过多数据；再调用配置的 LLM provider 对候选评分。LLM 不可用、返回格式不可解析或超过限额时，Scout 使用本地规则评分 fallback，并在输出中标注原因。

评分维度写入 system prompt：

| 维度 | 分值 | 含义 |
|------|------|------|
| 反直觉程度 | 0-3 | 结论是否违反大众直觉 |
| 信息差价值 | 0-3 | 目标读者大概率不知道 |
| TradFi × DeFi 匹配度 | 0-2 | 是否符合 Quill 定位 |
| 数据可信度 | 0-2 | 是否有 A/B 级证据支撑 |

扩展加权：

- 信息层级权重：tier1=×1.3，tier2=×1.1，tier3=×1.2，tier4=×1.0，tier5=×0.8
- 赛道匹配度：AI×Productivity / Crypto Research / Global Investing 三个赛道各 +1 分
- 时效性：24 小时内 +1 分，48 小时内 +0 分，更早 -1 分
- 优先选反直觉结论，不选新闻复述
- “热点+框架”组合优先于单纯热点

总分 10 分，默认输出 top 5。

### 输出格式

Scout 每次覆盖写入：

```
inputs/scout_candidates.md
```

仓库保留 `inputs/scout_candidates.example.md` 作为样例；真实运行输出不进 git。

同时归档到：

```
scout/scout_runs/YYYYMMDD_HHMM_candidates.md
```

候选文件格式：

```markdown
---
# Scout 候选话题
生成时间：YYYY-MM-DD HH:MM
数据源：arxiv, github_trending, hackernews, defillama, polymarket
---

## 01 · [话题标题，一句话]
评分：8.5/10 | 层级：Tier 1 | 来源：arXiv | 赛道：AI×Productivity | 证据等级：A
数据摘要：[2-3句，只写事实，不写观点]
反直觉角度：[为什么值得写，一句话]
建议切入点：[适合的内容角度，一句话]
原文链接：[URL]
```

### 使用流程

1. 运行 `python scout/run_scout.py --fetch-only`
2. 运行 `python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json`
3. 打开 `inputs/scout_candidates.md` 查看候选
4. 挑选一条，手动编辑 `inputs/idea.md`
5. 运行 `python run.py --provider groq` 或其他主 pipeline 命令

---

## config.py 规范

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys（从 .env 读取，不硬编码）
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# Provider
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "groq").strip().lower()
SUPPORTED_PROVIDERS = ("groq", "gemini", "anthropic", "cowork")
DEFAULT_PLATFORM = os.environ.get("DEFAULT_PLATFORM", "x-thread")
SUPPORTED_PLATFORMS = (
    "x-tweet",
    "x-thread",
    "x-article",
    "xhs-text",
    "xhs-caption",
    "xueqiu",
    "wechat",
)

# 模型（唯一定义处，不在其他文件出现）
PRIMARY_MODEL = "claude-sonnet-4-6"    # 正式内容，启动前验证可用性
TEST_MODEL = "gemini-2.5-flash"        # 结构调试
GROQ_MODEL = "llama-3.1-8b-instant"    # 默认快速测试
PROVIDER_MODELS = {
    "anthropic": PRIMARY_MODEL,
    "gemini": TEST_MODEL,
    "groq": GROQ_MODEL,
    "cowork": PRIMARY_MODEL,           # Cowork 模式：Claude 直接执行，无外部 API 调用
}

# 参数
MAX_TOKENS = 2000
TEMPERATURE_CREATIVE = 0.7             # writer / editor
TEMPERATURE_STRICT = 0.2               # researcher / reviewer / compliance
PROVIDER_RATE_LIMIT_DELAY_SECONDS = {
    "groq": 3,
    "gemini": 15,
    "anthropic": 0,
    "cowork": 0,
}
RATE_LIMIT_DELAY_SECONDS = PROVIDER_RATE_LIMIT_DELAY_SECONDS["gemini"]
SCOUT_TOP_N = int(os.environ.get("SCOUT_TOP_N", "5"))
SCOUT_DEFAULT_TIERS = os.environ.get("SCOUT_DEFAULT_TIERS", "1,2,3")
SCOUT_REQUIRED_SOURCES = tuple(
    source.strip()
    for source in os.environ.get("SCOUT_REQUIRED_SOURCES", "FRED").split(",")
    if source.strip()
)
SCOUT_FRESHNESS_FIELD = {
    "github_trending": "stars_today",
    "defillama": "change_7d",
    "hackernews": "score",
    "huggingface_papers": "published_at",
    "polymarket": "volume_24h",
    "arxiv": "published_at",
    "fred": "observation_date",
}
SCOUT_DEFILLAMA_MIN_TVL_USD = float(os.environ.get("SCOUT_DEFILLAMA_MIN_TVL_USD", "1000000"))
SCOUT_DEFILLAMA_MIN_ABS_CHANGE_7D = float(os.environ.get("SCOUT_DEFILLAMA_MIN_ABS_CHANGE_7D", "20"))
SCOUT_DEFILLAMA_MAX_ITEMS = int(os.environ.get("SCOUT_DEFILLAMA_MAX_ITEMS", "45"))
SCOUT_DEFILLAMA_CATEGORY_ALLOWLIST = tuple(
    category.strip()
    for category in os.environ.get(
        "SCOUT_DEFILLAMA_CATEGORY_ALLOWLIST",
        "Lending,DEX,Derivatives,RWA,Stablecoin,Bridge,Yield Aggregator,Prediction Market",
    ).split(",")
    if category.strip()
)
SCOUT_POLYMARKET_MIN_VOLUME_USD = float(os.environ.get("SCOUT_POLYMARKET_MIN_VOLUME_USD", "1000"))
SCOUT_POLYMARKET_MIN_LIQUIDITY_USD = float(os.environ.get("SCOUT_POLYMARKET_MIN_LIQUIDITY_USD", "1000"))
SCOUT_POLYMARKET_MAX_ITEMS = int(os.environ.get("SCOUT_POLYMARKET_MAX_ITEMS", "20"))

# 路径
PROMPTS_DIR = "prompts"
INPUTS_DIR = "inputs"
OUTPUTS_DIR = "outputs"

# 费用估算（美元/token，用于 meta.json 统计）
PROVIDER_COSTS_USD_PER_TOKEN = {
    "anthropic": {"input": 0.000003, "output": 0.000015},
    "gemini": {"input": 0.00000030, "output": 0.00000250},
    "groq": {"input": 0.00000005, "output": 0.00000008},
    "cowork": {"input": None, "output": None},
}
COST_PER_INPUT_TOKEN = PROVIDER_COSTS_USD_PER_TOKEN["anthropic"]["input"]
COST_PER_OUTPUT_TOKEN = PROVIDER_COSTS_USD_PER_TOKEN["anthropic"]["output"]

# 硬性敏感词表（compliance.py 使用）
HARD_BANNED_WORDS = [
    "稳赚", "翻倍", "必涨", "必跌", "保本", "零风险",
    "荐股", "内部消息", "百分之百", "稳定收益",
    "guaranteed", "risk-free"
]
```

---

## pipeline/runner.py 规范

```python
# runner.py
# run_agent(prompt_file, input_text, provider, model, temperature, platform) -> (str, dict)
# 返回值：(输出文本, usage_stats)
# usage_stats = {input_tokens, output_tokens, estimated_cost_usd}
# 异常处理：API 失败重试 3 次，间隔 5s，超时 60s
# 每次调用后打印：[Agent名] tokens: {in}→{out} | 本次: ${cost:.4f} | 累计: ${total:.4f}
# 仅当 prompt_file 为 03_writer.md 时，在 user message 头部注入目标平台说明
```

---

## pipeline/compliance.py 规范

```python
# compliance.py
# scan_hard_rules(text) -> list[dict]
# 返回：[{word: "稳赚", position: 42, context: "...前后20字..."}]
# 纯规则匹配，不调 LLM，零成本，零幻觉
# 在 06_compliance LLM 输出之后叠加运行
# 命中任何词 → 终端红色警告，写入 meta.json
```

---

## meta.json 规范

每次运行结束写入 `outputs/YYYYMMDD_HHMM/meta.json`：

```json
{
  "run_id": "20260626_1430",
  "input_file": "idea.md",
  "provider": "groq",
  "model": "claude-sonnet-4-6",
  "platform": "x-thread",
  "total_input_tokens": 12400,
  "total_output_tokens": 6800,
  "estimated_cost_usd": 0.138,
  "hard_rule_hits": [],
  "hitl_decisions": {
    "after_02": "y",
    "after_06": "pending"
  },
  "steps_completed": ["01", "02", "03", "04", "05", "06"]
}
```

---

## .gitignore

```
.env
outputs/
scout/scout_runs/
__pycache__/
*.pyc
.DS_Store
```

---

## Prompt 文件规范

每个 prompt 文件结构：

```markdown
# [Agent 名称]

## 角色
你是...

## 任务
你的输入是...
你需要输出...

## 约束
- 约束1
- 约束2

## 输出格式
[明确的格式要求]
```

所有 prompt 继承的内容哲学约束：
- 结论先行，不填充废话
- 反直觉事实 > 正确的废话
- 禁止：情绪化、鸡汤、焦虑营销、神棍预测、价格预测
- 证据等级：A（链上数据/财报）> B（白皮书）> C（机构报告）> D（KOL）> E（情绪）
- E 级证据不能支撑核心论点
- 01 Researcher 特别约束：**禁止补充任何未经用户提供的具体数字、日期、数据**

---

## 输出目录规范

每次运行在 `outputs/` 下创建时间戳子目录，不覆盖历史输出：

```
outputs/
└── 20260626_1430/
    ├── 01_research.md
    ├── 02_strategy.md
    ├── 03_draft.md
    ├── 04_edited.md
    ├── 05_reviewed.md
    ├── 06_final.md
    ├── meta.json
    └── .cowork_step.json   # Cowork 模式临时文件：当前步骤的 prompt+input 清单
```

---

## 断点续跑

`python run.py --from 03` 默认读最新时间戳目录中已有的输出。
`python run.py --from 03 --dir 20260626_1430` 显式指定目录，用于重跑历史记录。
后续输出覆盖同目录中对应文件，meta.json 追加更新。
断点续跑可同时传入 `--platform`，例如 `python run.py --from 03 --platform x-tweet`，用于只重写 writer 及后续步骤的目标平台版本。

`--from done` 是 Cowork 模式专用的特殊值，表示所有 LLM 步骤已完成，仅运行最终合规扫描（`scan_hard_rules`）并写入 meta.json。

---

## requirements.txt

```
anthropic>=0.25.0
google-genai>=0.8.0
groq>=0.9.0
python-dotenv>=1.0.0
click>=8.0.0
```

---

## 开发顺序（给 Codex 的执行建议）

1. 创建目录结构、.gitignore
2. 实现 `config.py`（含模型名常量和敏感词表）
3. 实现 `pipeline/compliance.py`（纯规则，无 LLM 依赖，最先可测试）
4. 实现 `pipeline/runner.py`（含 token 统计和重试逻辑）
5. 实现 `pipeline/loader.py` 和 `pipeline/writer.py`
6. 实现 `run.py`（含 CLI 参数、HITL 阻塞、meta.json 写入）
7. 写 6 个 prompt 模板骨架（内容待填充）
8. 用 `--test --auto` 端到端跑通全流程
9. 填充 prompt 内容，切换 Anthropic SDK，正式测试

Scout 开发顺序独立于主 pipeline：

1. 创建五层 `scout/sources/` 目录结构
2. 实现 `hackernews.py`（Firebase API，最多 5 并发）
3. 实现 `arxiv.py`（Atom/RSS 解析）
4. 实现 `github_trending.py`（HTML 抓取，设置 User-Agent）
5. 扩展 `run_scout.py`：`--tier` 参数、`--sources` 优先、asyncio 并发、60 秒总超时
6. 端到端测试：`python scout/run_scout.py --tier 1,2`
7. 实现 `huggingface_papers.py`
8. 实现 `fred.py`（无 `FRED_API_KEY` 时跳过）
9. 实现 `google_trends.py`（pytrends 不可用或限速时跳过）
10. 扩展 `scout/scorer.py`：信息层级权重、赛道匹配、时效性
11. 完整联调：`python scout/run_scout.py --provider groq --top 5`

---

## 不在范围内

- 自动发布到小红书 / X（无公开 API）
- Web UI
- 数据库 / 向量存储
- 多并发 Agent
- 自动生成图表（出图逻辑独立维护）
- 主 pipeline 的 web search 接入（Phase 2，Researcher 真正补数据时再加；Scout 的固定公开 API 不等同于 Researcher web search）
