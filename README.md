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
```

Provider 优先级：命令行 `--provider` > `.env` 的 `DEFAULT_PROVIDER` > 默认 `groq`。

Platform 优先级：命令行 `--platform` > `.env` 的 `DEFAULT_PLATFORM` > 默认 `x-thread`。

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

## 输出平台

`--platform` 控制 `03_writer` 的正文格式，默认是 `x-thread`。

可选值：

- `x-tweet`：单条推文
- `x-thread`：X 线程，默认主格式
- `x-article`：X 长文
- `xhs-text`：小红书纯文字
- `xhs-caption`：小红书配图说明
- `xueqiu`：雪球长文

示例：

```bash
python run.py --platform x-tweet
python run.py --platform x-thread
python run.py --test --auto --from 03 --platform xhs-text
python run.py --provider cowork --from 03 --dir 20260626_1520 --platform xueqiu
```

运行时会把平台要求注入 `03_writer.md` 的 user message 头部：

```text
目标平台：{platform}，请严格按照该平台的格式规范输出。
```

本次平台会记录到 `outputs/YYYYMMDD_HHMM/meta.json` 的 `platform` 字段。断点续跑时，如果传入新的 `--platform`，会更新同一目录下的 `meta.json` 并覆盖后续输出文件。
