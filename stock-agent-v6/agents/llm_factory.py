"""LLM client factory —— 按 config/models.json 为每个 agent 造 ChatOpenAI 客户端。

所有 agent 统一走 langchain-openai 的 ChatOpenAI；base_url/api_key 从环境变量读。
测试阶段 provider=deepseek → base_url=$DEEPSEEK_BASE_URL，api_key=$DEEPSEEK_API_KEY。
"""
import json
import os
from pathlib import Path
from typing import Any, Dict

from langchain_openai import ChatOpenAI

_MODELS_PATH = Path(__file__).parent.parent / "config" / "models.json"
_REASONER_MODELS = {"deepseek-reasoner", "o1-mini", "o1-preview", "o1"}


def _load_models() -> Dict[str, Dict[str, Any]]:
    return json.loads(_MODELS_PATH.read_text(encoding="utf-8"))


def build_llm(agent_name: str) -> ChatOpenAI:
    models = _load_models()
    if agent_name not in models:
        raise KeyError(f"agent '{agent_name}' not in config/models.json")

    cfg = models[agent_name]
    provider = cfg["provider"]
    model = cfg["model"]

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY 未设置。请复制 .env.example 为 .env 并填入 DeepSeek key。"
            )
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未设置。")
    else:
        raise ValueError(f"不支持的 provider: {provider}")

    kwargs: Dict[str, Any] = {"model": model, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    # reasoner 模型不接受自定义 temperature
    if model not in _REASONER_MODELS:
        kwargs["temperature"] = cfg.get("temperature", 0.3)

    return ChatOpenAI(**kwargs)
