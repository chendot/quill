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
RATE_LIMIT_DELAY_SECONDS = 15  # Gemini免费tier用，切换正式模型后设为0
SCOUT_TOP_N = int(os.environ.get("SCOUT_TOP_N", "5"))
SCOUT_DEFAULT_TIERS = os.environ.get("SCOUT_DEFAULT_TIERS", "1,2,3")

# Paths
PROMPTS_DIR = "prompts"
INPUTS_DIR = "inputs"
OUTPUTS_DIR = "outputs"

# Cost estimates in USD per token
COST_PER_INPUT_TOKEN = 0.000003
COST_PER_OUTPUT_TOKEN = 0.000015

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
