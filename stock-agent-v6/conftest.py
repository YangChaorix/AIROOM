"""pytest 启动钩子：

1. 加载 .env，让 has_api_key() 判断生效
2. 每个测试用独立 SQLite 文件 DB（tmp_path）+ 自动迁移 + 自动 seed default 用户
   —— 这样测试不会污染生产 DB（data/stock_agent.db）
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """每个测试用独立的临时 SQLite DB + 自动建表 + seed user_profile.json。"""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("STOCK_AGENT_DB_URL", db_url)

    # 重置全局 engine，让 get_engine() 按新 URL 重建
    from db import engine as eng_mod
    eng_mod.reset_engine()

    # create_all 建表（比 alembic upgrade 快，测试够用；视图缺失不影响大多数单元测试）
    from db.models import Base
    Base.metadata.create_all(eng_mod.get_engine())

    # 自动 seed default 用户（若存在 config/user_profile.json）
    profile_path = Path(__file__).parent / "config" / "user_profile.json"
    if profile_path.exists():
        from scripts.seed_from_json import seed
        try:
            seed(profile_path)
        except Exception:
            pass  # seed 失败不阻塞测试

    yield db_url

    # 清理：重置 engine，让下个测试重新创建
    eng_mod.reset_engine()
