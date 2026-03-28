"""
stock-agent-v3 配置管理
v1.2: LLM 配置改为 config/models.json，支持 provider/model-id 格式
"""

import os
import json
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# ── LLM 模型配置（从 models.json 解析） ───────────────────────────────────────

_MODELS_FILE = os.path.join(os.path.dirname(__file__), "models.json")


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model_name: str
    temperature: float
    max_tokens: int


def _load_models_json() -> dict:
    with open(_MODELS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_llm_config(agent_name: str) -> LLMConfig:
    """
    从 config/models.json 解析指定 Agent 的 LLM 配置。
    model 格式：'provider/model-id'，例如 'deepseek/deepseek-chat'。
    """
    cfg = _load_models_json()

    model_str = cfg["agents"][agent_name]["model"]
    provider_id, model_id = model_str.split("/", 1)

    provider = cfg["providers"][provider_id]
    api_key = os.getenv(provider["api_key_env"], "")
    base_url = provider["base_url"]

    defaults = cfg.get("defaults", {})
    return LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model_name=model_id,
        temperature=float(defaults.get("temperature", 0.1)),
        max_tokens=int(defaults.get("max_tokens", 16000)),
    )


def build_llm(agent_name: str):
    """
    根据 models.json 中的 provider 自动选择 LLM 实现：
    - anthropic → ChatAnthropic
    - deepseek / google / 其他 → ChatOpenAI（OpenAI 兼容接口）
    """
    import logging
    cfg = _load_models_json()
    model_str = cfg["agents"][agent_name]["model"]
    provider_id, _ = model_str.split("/", 1)
    llm_cfg = get_llm_config(agent_name)
    logging.getLogger(__name__).info(f"[{agent_name}] 使用模型：{model_str}")

    if provider_id == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            api_key=llm_cfg.api_key,
            model=llm_cfg.model_name,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_tokens,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
            model=llm_cfg.model_name,
            temperature=llm_cfg.temperature,
            max_tokens=llm_cfg.max_tokens,
        )


# ── 其他配置 ──────────────────────────────────────────────────────────────────

@dataclass
class SerperConfig:
    """Serper Web 搜索 API 配置（用于政策新闻补充）"""

    api_key: str = field(default_factory=lambda: os.getenv("SERPER_API_KEY", ""))
    enabled: bool = field(
        default_factory=lambda: bool(os.getenv("SERPER_API_KEY", ""))
        if os.getenv("SERPER_ENABLED", "").lower() != "false"
        else False
    )
    base_url: str = "https://google.serper.dev/search"


@dataclass
class AkshareConfig:
    kline_days: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_KLINE_DAYS", "90"))
    )
    news_count: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_NEWS_COUNT", "30"))
    )
    timeout: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_TIMEOUT", "30"))
    )


@dataclass
class AgentConfig:
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "10"))
    )
    verbose: bool = field(
        default_factory=lambda: os.getenv("AGENT_VERBOSE", "false").lower() == "true"
    )
    event_history_dir: str = field(
        default_factory=lambda: os.getenv("AGENT_EVENT_HISTORY_DIR", "data/event_history")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("AGENT_DB_PATH", "data/db/stock_agent.db")
    )
    # 采集间隔（分钟）
    collect_interval_high: int = field(
        default_factory=lambda: int(os.getenv("COLLECT_INTERVAL_HIGH", "30"))
    )
    collect_interval_medium: int = field(
        default_factory=lambda: int(os.getenv("COLLECT_INTERVAL_MEDIUM", "60"))
    )
    collect_interval_low: int = field(
        default_factory=lambda: int(os.getenv("COLLECT_INTERVAL_LOW", "120"))
    )
    # 各优先级活跃时段（24h制，支持多段逗号分隔，如 "6-9,15-18"）
    collect_high_hours: str = field(
        default_factory=lambda: os.getenv("COLLECT_HIGH_HOURS", "6-15")
    )
    collect_medium_hours: str = field(
        default_factory=lambda: os.getenv("COLLECT_MEDIUM_HOURS", "6-18")
    )
    collect_low_hours: str = field(
        default_factory=lambda: os.getenv("COLLECT_LOW_HOURS", "6-9,15-18")
    )
    # 新闻入库最大天数（pub_time 超过此天数的新闻跳过，0=不限制）
    news_max_age_days: int = field(
        default_factory=lambda: int(os.getenv("NEWS_MAX_AGE_DAYS", "3"))
    )
    # APScheduler 触发时段（APScheduler hour 表达式，如 "6-17"）
    collect_schedule_hours: str = field(
        default_factory=lambda: os.getenv("COLLECT_SCHEDULE_HOURS", "6-17")
    )
    # APScheduler 触发间隔（分钟）
    collect_schedule_interval: int = field(
        default_factory=lambda: int(os.getenv("COLLECT_SCHEDULE_INTERVAL", "30"))
    )


@dataclass
class Settings:
    serper: SerperConfig = field(default_factory=SerperConfig)
    akshare: AkshareConfig = field(default_factory=AkshareConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def validate(self):
        cfg = get_llm_config("trigger")
        if not cfg.api_key:
            raise ValueError("LLM API Key 未设置，请检查 config/models.json 和对应的环境变量")

    @property
    def is_valid(self):
        try:
            self.validate()
            return True
        except ValueError:
            return False


settings = Settings()
