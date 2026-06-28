from __future__ import annotations


def infer_track(text: str) -> str:
    lowered = text.lower()
    ai_terms = ("ai", "llm", "agent", "model", "productivity", "copilot")
    crypto_terms = ("bitcoin", "crypto", "ethereum", "defi", "blockchain")
    if any(word in lowered for word in ai_terms):
        return "AI×Productivity"
    if any(word in lowered for word in crypto_terms):
        return "Crypto Research"
    return "Global Investing"
