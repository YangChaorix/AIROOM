"""
配置模块：从环境变量读取所有配置项
支持通过 .env 文件或系统环境变量配置
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()


@dataclass
class DeepSeekConfig:
    """DeepSeek 模型配置"""
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
    )
    temperature: float = field(
        default_factory=lambda: float(os.getenv("DEEPSEEK_TEMPERATURE", "0.1"))
    )
    max_tokens: int = field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_MAX_TOKENS", "4096"))
    )


@dataclass
class AkshareConfig:
    """Akshare 数据源配置"""
    # 历史K线数据默认获取天数
    kline_days: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_KLINE_DAYS", "90"))
    )
    # 新闻获取条数
    news_count: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_NEWS_COUNT", "20"))
    )
    # 请求超时时间（秒）
    timeout: int = field(
        default_factory=lambda: int(os.getenv("AKSHARE_TIMEOUT", "30"))
    )


@dataclass
class AgentConfig:
    """Agent 运行配置"""
    # 每个子Agent最大迭代次数
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "5"))
    )
    # 是否启用详细日志
    verbose: bool = field(
        default_factory=lambda: os.getenv("AGENT_VERBOSE", "false").lower() == "true"
    )
    # 并行执行超时时间（秒）
    parallel_timeout: int = field(
        default_factory=lambda: int(os.getenv("AGENT_PARALLEL_TIMEOUT", "120"))
    )


@dataclass
class Settings:
    """全局配置汇总"""
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    akshare: AkshareConfig = field(default_factory=AkshareConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

    def validate(self) -> None:
        """验证必要配置项是否完整"""
        if not self.deepseek.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 环境变量未设置。"
                "请在 .env 文件或系统环境变量中配置 DEEPSEEK_API_KEY。"
            )

    @property
    def is_valid(self) -> bool:
        """检查配置是否有效（不抛出异常）"""
        try:
            self.validate()
            return True
        except ValueError:
            return False


# 全局单例配置对象
settings = Settings()
