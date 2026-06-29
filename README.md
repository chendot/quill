# Quill

Quill 是一个本地、线性的 AI 内容 pipeline，用来把一段短投资观点转成可发布草稿，并生成审稿意见、合规检查和 token 成本记录。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

创建本地 `.env` 文件，按需填入 API key。可选配置：

```bash
DEFAULT_PROVIDER=groq
DEFAULT_PLATFORM=x-thread
SCOUT_REQUIRED_SOURCES=FRED
SCOUT_DEFILLAMA_MIN_TVL_USD=1000000
SCOUT_DEFILLAMA_MIN_ABS_CHANGE_7D=20
SCOUT_POLYMARKET_MIN_VOLUME_USD=1000
USE_PROXY=1
PROXY_URL=http://127.0.0.1:7897
USE_ENV_PROXY=0
```

Provider 优先级：命令行 `--provider` > `.env` 的 `DEFAULT_PROVIDER` > 默认 `groq`。

Platform 优先级：命令行 `--platform` > `.env` 的 `DEFAULT_PLATFORM` > 默认 `x-thread`。

网络请求默认使用 `PROXY_URL`，未配置时回退到 `http://127.0.0.1:7897`。默认不读取 shell 里的 `HTTP_PROXY` / `HTTPS_PROXY`，避免 Cowork 或 sandbox 注入不可用的 `localhost` 代理；如果确实想继承环境代理，可设置 `USE_ENV_PROXY=1`。如果不需要代理，可在 `.env` 设置 `USE_PROXY=0`。

## 使用方式

每次运行前先编辑 `inputs/idea.md`。如果有人工整理的真实数据、链接或来源，可写入 `inputs/data.md`。
`inputs/scout_candidates.example.md` 是样例；真实 Scout 输出写入 `inputs/scout_candidates.md`，该文件不进 git。

```bash
python run.py
python run.py --input my_idea.md
python run.py --provider groq
python run.py --provider gemini
python run.py --provider anthropic
python run.py --test  # 兼容旧参数；新代码优先用 --provider gemini
python run.py --auto
python run.py --from 03
python run.py --from 03 --dir 20260626_1430
python run.py --provider groq --auto
```

## Scout 话题发现

Scout 是独立的 Extract -> Transform -> Load 模块，不属于主 pipeline，也不会自动改写 `inputs/idea.md`。

```bash
python scout/run_scout.py --fetch-only
python scout/run_scout.py --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
python scout/run_scout.py --provider cowork --from-raw scout/scout_runs/YYYYMMDD_HHMM_raw.json
```

- Extract：本机联网抓取，写入 `scout/scout_runs/YYYYMMDD_HHMM_raw.json`，不调用 LLM。
- Transform：只读 raw snapshot；未显式传 `--provider` 时使用本地规则评分，便于可复现重跑。
- Load：写入 `inputs/scout_candidates.md` 并归档候选文件。

抓取层会先做硬过滤，不把全量原始转储丢给评分器：DefiLlama 默认按 TVL、7 日变化和类别白名单筛到约 30-50 条；Polymarket 默认剔除低 24h 成交量市场；arXiv 按源返回的最新提交时间回看 48 小时。raw snapshot 的 `source_status` 会标记 `ok`、`empty`、`failed` 或 `incomplete`，并记录每个源的核心热度字段缺失数。

## 输出平台

`--platform` 控制 `03_writer` 的正文格式，默认是 `x-thread`。

可选值：

- `x-tweet`：单条推文
- `x-thread`：X 线程，默认主格式
- `x-article`：X 长文
- `xhs-text`：小红书纯文字
- `xhs-caption`：小红书配图说明
- `xueqiu`：雪球长文
- `wechat`：微信公众号长文

示例：

```bash
python run.py --platform x-tweet
python run.py --platform x-thread
python run.py --platform wechat
python run.py --test --auto --from 03 --platform xhs-text
python run.py --provider cowork --from 03 --dir 20260626_1520 --platform xueqiu
```

运行时会把平台要求注入 `03_writer.md` 的 user message 头部：

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

本次平台会记录到 `outputs/YYYYMMDD_HHMM/meta.json` 的 `platform` 字段。断点续跑时，如果传入新的 `--platform`，会更新同一目录下的 `meta.json` 并覆盖后续输出文件。
