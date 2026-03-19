"""
stock-agent-v3 配置管理
v1.1: 新增 SerperConfig（Web搜索）和 event_history_dir（事件历史追踪）
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DeepSeekConfig:
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))
    )
    max_tokens: int = field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_MAX_TOKENS", "16000"))
    )


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
    data_dir: str = field(
        default_factory=lambda: os.getenv("AGENT_DATA_DIR", "data/daily_push")
    )
    event_history_dir: str = field(
        default_factory=lambda: os.getenv("AGENT_EVENT_HISTORY_DIR", "data/event_history")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("AGENT_DB_PATH", "data/stock_agent.db")
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
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    serper: SerperConfig = field(default_factory=SerperConfig)
    akshare: AkshareConfig = field(default_factory=AkshareConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def validate(self):
        if not self.deepseek.api_key:
            raise ValueError("DEEPSEEK_API_KEY 未设置")

    @property
    def is_valid(self):
        try:
            self.validate()
            return True
        except ValueError:
            return False


settings = Settings()
