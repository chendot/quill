from __future__ import annotations


def infer_track(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("agent", "agents", "multi-agent", "workflow", "automation")):
        return "AI×Agent编排"
    if any(word in lowered for word in ("code", "coding", "developer", "copilot", "github", "cli", "ide")):
        return "AI×开发工具链"
    if any(word in lowered for word in ("data", "dataset", "database", "benchmark", "evaluation", "eval")):
        return "AI×数据基础设施"
    if any(word in lowered for word in ("research", "paper", "arxiv", "model", "llm", "ai")):
        return "AI×研究方法"
    if any(word in lowered for word in ("defi", "tvl", "lending", "yield", "liquidity", "protocol")):
        return "crypto×DeFi机制"
    if any(word in lowered for word in ("on-chain", "onchain", "ethereum", "bitcoin", "blockchain", "wallet")):
        return "crypto×链上分析"
    if any(word in lowered for word in ("regulation", "sec", "compliance", "policy")):
        return "crypto×监管合规"
    if any(word in lowered for word in ("market", "probability", "polymarket", "volume", "price")):
        return "crypto×市场结构"
    if any(word in lowered for word in ("rate", "rates", "fed", "yield", "treasury")):
        return "macro×利率政策"
    if any(word in lowered for word in ("dollar", "usd", "fx", "currency", "exchange")):
        return "macro×汇率"
    if any(word in lowered for word in ("gold", "oil", "commodity", "commodities")):
        return "macro×大宗商品"
    return "其他×市场观察"
