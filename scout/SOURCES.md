# Scout 数据源说明

Scout 的数据源按信息质量和用途分层。这里不追求“源越多越好”，而是按 Quill 的三个内容赛道筛出真正有用的信号：

- `AI×Productivity`
- `Crypto Research`
- `Global Investing`

优先级原则：一手数据和可验证数据优先，社区讨论用于发现分歧，趋势/社交热度只作为叙事扩散信号，不能单独支撑核心论点。

---

## Tier 1 · 一手信息源

### arXiv

学术预印本平台。论文正式发表前通常会先传到这里，不经过同行评审，但价值也在这里：它往往比正式发表、媒体报道和行业复述早几个月。

对 Quill 有用的分区：

- `cs.AI`：AI 模型、Agent、推理、评测
- `q-fin`：量化金融、资产定价、风险模型
- `cs.CR`：密码学，偶尔有 DeFi / 安全 / 零知识相关论文

典型选题：某篇论文发现 BTC 链上行为的新规律，可能比媒体报道早几个月。

- API 接口：`http://export.arxiv.org/api/query`
- 免费限制：免费 Atom API，无需 API key；需要控制请求频率，避免频繁抓取。
- Python 文件：`scout/sources/tier1_primary/arxiv.py`

### GitHub Trending

开发者每天投票和使用行为推出来的热门开源项目。很多产品还没发布、媒体还没报道，但代码已经出现了。

对 Quill 有用的信号：

- AI Agent 框架突然走红，预示应用方向变化
- DeFi 协议或链上工具开源新模块
- 量化工具、数据分析库、研究框架突然获得开发者关注

典型选题：某个 LP 自动化工具上了 Trending，背后可能意味着 DeFi 做市或收益管理需求正在变化。

- API 接口：无官方 API，抓取 `https://github.com/trending?since=daily`
- 免费限制：无需 API key；必须设置 `User-Agent`，GitHub 页面结构可能变化，也可能对高频请求限速。
- Python 文件：`scout/sources/tier1_primary/github_trending.py`

### Hugging Face Papers

AI 研究者社区每天精选的重要论文。相比直接扫 arXiv，Hugging Face Papers 噪音更少，适合追踪模型能力边界和 AI 工具链变化。

对 Quill 有用：判断某个 AI 叙事是否有技术支撑，而不是只停留在产品发布或市场热词。

- API 接口：优先使用 `https://huggingface.co/api/daily_papers`，RSS / 页面作为后备。
- 免费限制：当前无需 API key；属于公开但非强 SLA 的接口，字段和可用性可能变化。
- Python 文件：`scout/sources/tier1_primary/huggingface_papers.py`

---

## Tier 2 · 专业人士讨论区

### Hacker News

硅谷技术创业社区，用户主要是工程师、创始人、投资人。评论区经常比文章本身更有价值，因为行业内行人会直接指出问题、补充数据或反驳叙事。

对 Quill 有用：

- AI 工具真实使用体验
- 创业公司早期动态
- 技术争议和工程侧反对意见
- 某个趋势是否已经从“媒体说法”进入“从业者讨论”

典型选题：HN 上工程师说“我们内部已经不用 X，换成 Y”，这可能比官方发布更早反映工具迁移。

- API 接口：
  - `https://hacker-news.firebaseio.com/v0/topstories.json`
  - `https://hacker-news.firebaseio.com/v0/item/{id}.json`
- 免费限制：Firebase 公开 API，无需 key；Scout 只取前 30 条，并限制最多 5 个并发详情请求。
- Python 文件：`scout/sources/tier2_community/hackernews.py`

### Reddit

分版块社区，质量差异很大，但特定版块可以作为情绪指标。

对 Quill 可能有用的版块：

- `r/investing`：散户视角，市场情绪
- `r/Bitcoin` / `r/ethereum`：加密社区共识和分歧
- `r/MachineLearning`：ML 研究者讨论
- `r/algotrading`：量化策略讨论

使用定位：Reddit 更适合判断“共识是否已经形成”，通常是 E 级信号，只能作为反向指标或叙事扩散背景。

- API 接口：Reddit API
- 免费限制：API 限制较多，鉴权和使用政策变化频繁。
- Python 文件：暂未实现

---

## Tier 3 · 数据平台

### DefiLlama

DeFi 协议 TVL 聚合平台，免费、无需注册、有公开 API，是链上数据里信噪比较高的入门数据源。

对 Quill 有用的指标：

- TVL 7 日 / 30 日变化：协议资金流入流出
- 协议类别和所属链：判断资金迁移发生在哪条链、哪个赛道
- 链级别 TVL：判断哪条链正在吸引资金

典型用法：验证“TVL 高不等于代币价值高”，或者发现资金迁移先于价格叙事发生。

- API 接口：`https://api.llama.fi/protocols`
- 免费限制：免费公开 API，无需 key；字段和可用性可能变化。
- Python 文件：`scout/sources/tier3_data/defillama.py`

### Glassnode

BTC / ETH 链上数据平台，适合做周期和持仓结构判断。

对 Quill 有用的指标：

- MVRV Ratio / MVRV Z-Score
- 交易所净流入 / 流出
- 长期持有者供应量
- RHODL Ratio 等周期指标

使用定位：适合支撑 BTC 六指标框架，是 Crypto Research 的 A 级证据来源之一。

- API 接口：Glassnode API
- 免费限制：有免费 tier，但高价值指标和更细粒度数据通常需要付费。
- Python 文件：暂未实现

### FRED

Federal Reserve Economic Data，美联储圣路易斯分行维护的宏观数据库。覆盖大量官方宏观数据，免费、稳定、可引用。

对 Quill 有用的指标：

- `FEDFUNDS`：联邦基金利率
- `DGS10`：10 年期美债收益率
- `DTWEXBGS`：美元指数
- `CPIAUCSL`：CPI
- `M2SL`：M2 货币供应量（后续可扩展）

使用定位：资产配置框架的宏观底层变量，是 Global Investing 的 A 级证据来源。

- API 接口：`https://api.stlouisfed.org/fred/series/observations`
- 免费限制：需要免费 API key；`FRED_API_KEY` 为空时 Scout 自动跳过。
- Python 文件：`scout/sources/tier3_data/fred.py`

### Polymarket

预测市场数据源，用来观察市场对事件概率的定价。Scout 只保留概率不极端的市场，避免只抓到已经形成共识的事件。

对 Quill 有用：

- 找到仍有分歧的宏观、政治、加密或 AI 事件
- 对比“媒体叙事”和“下注概率”的差异
- 作为反直觉角度的候选来源

- API 接口：`https://gamma-api.polymarket.com/markets`
- 免费限制：公开接口，无需 key；字段和限速不保证稳定。
- Python 文件：`scout/sources/tier3_data/polymarket.py`

### Eastmoney

东方财富板块资金流。适合观察 A 股板块层面的主力资金流入流出，是区域市场信号。

对 Quill 有用：

- 中国资产相关选题的资金流背景
- 板块涨跌幅和主力资金方向是否背离
- 观察“价格还没动但资金先动”的板块

- API 接口：
  - 主接口：`https://push2.eastmoney.com/api/qt/ulist.np/get`
  - 后备接口：`https://push2.eastmoney.com/api/qt/clist/get`
- 免费限制：非官方公开接口，无需 key；参数和可用性可能变化。
- Python 文件：`scout/sources/tier3_data/eastmoney.py`

### Token Terminal

链上协议财务数据平台，比 DefiLlama 更偏收入、费用和估值维度。

对 Quill 有用：

- P/F（价格 / 费用比）
- P/S（价格 / 收入比）
- 协议收入趋势
- 判断协议是真实现金流还是补贴驱动

使用定位：适合分析 BNB、DEX、借贷协议等“协议像公司一样估值”的选题。

- API 接口：Token Terminal API
- 免费限制：部分数据可免费查看，API 和历史数据通常有限制。
- Python 文件：暂未实现

### Artemis

链上数据聚合平台，覆盖更多 L2、新兴链和应用指标，能补 DefiLlama 和 Glassnode 的空白。

对 Quill 有用：

- 跨链活跃用户对比
- 开发者和应用生态趋势
- 资金、交易量和用户在不同链之间的迁移

- API 接口：Artemis API
- 免费限制：部分数据免费，完整 API 通常需要注册或付费。
- Python 文件：暂未实现

---

## Tier 4 · 趋势发现

### Google Trends

搜索量趋势，反映大众关注度变化方向，不代表事实强度，也不代表投资价值。

对 Quill 有用的用法：

- 对比关键词：`Bitcoin` vs `gold`
- 发现上升叙事：某个词开始快速增长，说明叙事正在扩散
- 观察地域分布：哪个国家或地区开始关注某个资产或技术

注意：Google Trends 是 E 级信号，只能判断叙事扩散程度，不能支撑核心论点。

- API 接口：通过 `pytrends` 使用 Google Trends 非官方接口。
- 免费限制：无需 key，但容易被限速；未安装 `pytrends` 或被限速时 Scout 自动跳过。
- Python 文件：`scout/sources/tier4_trends/google_trends.py`

### Exploding Topics

Google Trends 的策划版，团队筛选正在爆发但还没主流化的话题。

对 Quill 有用：发现早期趋势词，作为选题雷达，而不是证据来源。

- API 接口：无当前实现
- 免费限制：newsletter 免费可用，完整产品和 API 能力有限制。
- Python 文件：暂未实现

---

## Tier 5 · 社交热点

### Hacker News Hot

复用 Hacker News top stories，但作为低优先级社交热度源处理。它和 Tier 2 的区别不是接口不同，而是使用目的不同：Tier 2 看专业讨论，Tier 5 看热点扩散。

对 Quill 有用：

- 判断某个技术话题是否已经热起来
- 作为“共识扩散”信号，而不是核心证据
- 给已有数据选题补充叙事背景

- API 接口：
  - `https://hacker-news.firebaseio.com/v0/topstories.json`
  - `https://hacker-news.firebaseio.com/v0/item/{id}.json`
- 免费限制：同 Hacker News；Scout 对 Tier 5 设置较低 scorer 权重。
- Python 文件：`scout/sources/tier5_social/hackernews_hot.py`

---

## 对 Quill 最有价值的组合

| 赛道 | 首选数据源 | 证据等级 |
|------|------------|----------|
| AI×Productivity | arXiv + GitHub Trending + Hacker News + Hugging Face Papers | A/B |
| Crypto Research | DefiLlama + Glassnode + Token Terminal + Polymarket | A/B |
| Global Investing | FRED + Google Trends + arXiv `q-fin` | A/E |

优先跑通顺序：

1. arXiv：覆盖 AI 和 q-fin，一手信号
2. DefiLlama：覆盖 Crypto Research，免费且稳定
3. FRED：覆盖 Global Investing，官方宏观数据
4. GitHub Trending / Hacker News：补充技术趋势和专业讨论
5. Google Trends / 社交热点：只用于判断叙事扩散
