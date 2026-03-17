"""
配置模块：从环境变量读取所有配置项
支持通过 .env 文件或系统环境变量配置
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DeepSeekConfig:
    """DeepSeek 模型配置"""
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
class AkshareConfig:
    """Akshare 数据源配置"""
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
    """Agent 运行配置"""
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "10"))
    )
    verbose: bool = field(
        default_factory=lambda: os.getenv("AGENT_VERBOSE", "false").lower() == "true"
    )
    data_dir: str = field(
        default_factory=lambda: os.getenv("AGENT_DATA_DIR", "data/daily_push")
    )


@dataclass
class Settings:
    """全局配置汇总"""
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    akshare: AkshareConfig = field(default_factory=AkshareConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def validate(self) -> None:
        if not self.deepseek.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 环境变量未设置。"
                "请在 .env 文件或系统环境变量中配置 DEEPSEEK_API_KEY。"
            )

    @property
    def is_valid(self) -> bool:
        try:
            self.validate()
            return True
        except ValueError:
            return False


settings = Settings()
