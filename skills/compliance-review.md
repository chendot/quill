# Compliance Review

## 适用范围
06_compliance、forge/compliance.py，以及所有需要检查投资内容语气风险、监管边界、免责声明和硬性敏感词的步骤。

## 规则内容
合规检查分为两层，不能合并：
- 06_compliance.md：LLM-based tone and regulatory risk review
- forge/compliance.py：deterministic hard-rule keyword scan，pure Python，no LLM call

06_compliance 只负责判断复杂语气风险，不是敏感词机器。

硬性敏感词由独立规则函数处理。

LLM 合规审查执行三项检查：
1. 过度承诺：找出所有暗示「买了就会涨」「做了就会赚」的表达，即使没有用明确的承诺词。
2. 身份越界：内容是否超出「认知分享」边界，进入「投资建议」领域。
3. 平台合规：针对目标平台的特定风险。

平台合规：
- 小红书：不能出现直接代码、账号、平台引流
- X：加密相关内容避免「guaranteed returns」类表达
- 雪球：具体标的讨论需注明「非投资建议」

发布就绪评估：
1. 前两段能不能让陌生读者知道这篇在讲什么？
2. 核心判断是否清晰，还是需要读完全文才能理解？
3. 有没有任何段落可以删掉而不影响核心论点？

forge/compliance.py 纯规则匹配，不调 LLM，零成本，零幻觉。

硬规则扫描返回命中词、位置和前后文。

命中任何词，写入 meta.json 的 hard_rule_hits。

## 常见错误
- 把 LLM 合规审查和硬性敏感词扫描合并。
- 让 06_compliance 负责硬性关键词匹配。
- 把“认知分享”写成具体买卖建议。
- 暗示 guaranteed returns、risk-free、稳赚、保本、翻倍。
- 具体标的讨论缺少「非投资建议」。
- 发布就绪只看合规，不看前两段是否讲清核心判断。
