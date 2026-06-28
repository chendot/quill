import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        env_path = ".env"
        if not os.path.exists(env_path):
            return False
        with open(env_path, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
        return False

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# Providers
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
)

# Models
PRIMARY_MODEL = "claude-sonnet-4-6"
TEST_MODEL = "gemini-2.5-flash"
GROQ_MODEL = "llama-3.1-8b-instant"
PROVIDER_MODELS = {
    "anthropic": PRIMARY_MODEL,
    "gemini": TEST_MODEL,
    "groq": GROQ_MODEL,
    "cowork": PRIMARY_MODEL,  # Cowork 模式：Claude 直接处理，无外部 API 调用
}

# Parameters
MAX_TOKENS = 2000
TEMPERATURE_CREATIVE = 0.7
TEMPERATURE_STRICT = 0.2
REQUEST_TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
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

# Paths
PROMPTS_DIR = "prompts"
INPUTS_DIR = "inputs"
OUTPUTS_DIR = "outputs"

# Cost estimates in USD per token
PROVIDER_COSTS_USD_PER_TOKEN = {
    "anthropic": {
        "input": 0.000003,
        "output": 0.000015,
    },
    "gemini": {
        "input": 0.00000030,
        "output": 0.00000250,
    },
    "groq": {
        "input": 0.00000005,
        "output": 0.00000008,
    },
    "cowork": {
        "input": None,
        "output": None,
    },
}
COST_PER_INPUT_TOKEN = PROVIDER_COSTS_USD_PER_TOKEN["anthropic"]["input"]
COST_PER_OUTPUT_TOKEN = PROVIDER_COSTS_USD_PER_TOKEN["anthropic"]["output"]

# Hard compliance rules
HARD_BANNED_WORDS = [
    "稳赚",
    "翻倍",
    "必涨",
    "必跌",
    "保本",
    "零风险",
    "荐股",
    "内部消息",
    "百分之百",
    "稳定收益",
    "guaranteed",
    "risk-free",
]
