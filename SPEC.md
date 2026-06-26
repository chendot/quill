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

---

## 项目结构

```
quill/
├── SPEC.md                  # 本文件，Codex 的唯一输入
├── README.md                # 项目说明
├── .env                     # API keys（不进 git）
├── .env.example             # 环境变量模板（进 git）
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
│   └── data.md              # 可选：用户手动填入的真实数据/链接
├── outputs/                 # 自动生成，不进 git
│   └── YYYYMMDD_HHMM/
│       ├── 01_research.md
│       ├── 02_strategy.md
│       ├── 03_draft.md
│       ├── 04_edited.md
│       ├── 05_reviewed.md
│       ├── 06_final.md      # 最终稿，人工确认后发布
│       └── meta.json        # token 统计、费用、运行参数
└── requirements.txt
```

---

## 技术栈

- Python 3.10+
- `anthropic` SDK（正式内容生产）
- `google-genai` SDK（测试阶段）
- `python-dotenv`（环境变量管理）
- `click`（CLI 参数）
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

## HITL 节点

| 节点 | 介入方式 | 原因 |
|------|----------|------|
| 运行前 | 手动编辑 inputs/idea.md | 核心观点必须来自人，不能生成 |
| 02 之后 | 终端确认选题和标题 | 方向错了后续全部浪费 |
| 06 之后 | 手动发布 | 发布不可逆，合规风险由人承担 |

实现方式：`input()` 阻塞等待，输入 `y` 继续，`n` 终止并保留已有输出。
`--auto` flag 跳过所有 HITL（仅测试用，正式生产不带此 flag）。

---

## CLI 接口

```
python run.py                              # 默认：idea.md，正式模型，HITL 开启
python run.py --input my_idea.md           # 指定输入文件
python run.py --test                       # 使用 Gemini 测试模型
python run.py --auto                       # 跳过所有 HITL（测试用）
python run.py --from 03                    # 从第3步断点续跑（默认最新目录）
python run.py --from 03 --dir 20260626_1430  # 指定目录断点续跑
python run.py --test --auto                # 组合：测试模型 + 无 HITL，最快调试
```

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

# 模型（唯一定义处，不在其他文件出现）
PRIMARY_MODEL = "claude-sonnet-4-6"    # 正式内容，启动前验证可用性
TEST_MODEL = "gemini-2.5-flash"        # 结构调试

# 参数
MAX_TOKENS = 2000
TEMPERATURE_CREATIVE = 0.7             # writer / editor
TEMPERATURE_STRICT = 0.2               # researcher / reviewer / compliance

# 路径
PROMPTS_DIR = "prompts"
INPUTS_DIR = "inputs"
OUTPUTS_DIR = "outputs"

# 费用估算（美元/token，用于 meta.json 统计）
COST_PER_INPUT_TOKEN = 0.000003        # claude-sonnet-4-6 input
COST_PER_OUTPUT_TOKEN = 0.000015       # claude-sonnet-4-6 output

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
# run_agent(prompt_file, input_text, model, temperature) -> (str, dict)
# 返回值：(输出文本, usage_stats)
# usage_stats = {input_tokens, output_tokens, estimated_cost_usd}
# 异常处理：API 失败重试 3 次，间隔 5s，超时 60s
# 每次调用后打印：[Agent名] tokens: {in}→{out} | 本次: ${cost:.4f} | 累计: ${total:.4f}
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
  "model": "claude-sonnet-4-6",
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

## .env.example

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
GEMINI_API_KEY=your-gemini-key-here
```

---

## .gitignore

```
.env
outputs/
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
    └── meta.json
```

---

## 断点续跑

`python run.py --from 03` 默认读最新时间戳目录中已有的输出。
`python run.py --from 03 --dir 20260626_1430` 显式指定目录，用于重跑历史记录。
后续输出覆盖同目录中对应文件，meta.json 追加更新。

---

## requirements.txt

```
anthropic>=0.25.0
google-genai>=0.8.0
python-dotenv>=1.0.0
click>=8.0.0
```

---

## 开发顺序（给 Codex 的执行建议）

1. 创建目录结构、.gitignore、.env.example
2. 实现 `config.py`（含模型名常量和敏感词表）
3. 实现 `pipeline/compliance.py`（纯规则，无 LLM 依赖，最先可测试）
4. 实现 `pipeline/runner.py`（含 token 统计和重试逻辑）
5. 实现 `pipeline/loader.py` 和 `pipeline/writer.py`
6. 实现 `run.py`（含 CLI 参数、HITL 阻塞、meta.json 写入）
7. 写 6 个 prompt 模板骨架（内容待填充）
8. 用 `--test --auto` 端到端跑通全流程
9. 填充 prompt 内容，切换 Anthropic SDK，正式测试

---

## 不在范围内

- 自动发布到小红书 / X（无公开 API）
- Web UI
- 数据库 / 向量存储
- 多并发 Agent
- 自动生成图表（出图逻辑独立维护）
- web search 接入（Phase 2，Researcher 真正补数据时再加）
