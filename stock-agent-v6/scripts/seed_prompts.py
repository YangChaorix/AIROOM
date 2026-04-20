"""把 config/prompts/*.md 5 份文件导入 prompt_versions 表作为初始版本。

用法：
    python scripts/seed_prompts.py           # 首次导入
    python scripts/seed_prompts.py --force   # 即使 DB 已有版本也再导入一条"来自文件"版本

首次运行导入 5 个 agent 的初始 prompt 作为 v<today>0001，并设置 is_active=1。
后续运行：默认跳过已有 agent（不覆盖）；加 --force 追加新版本。
"""
import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from db.engine import get_session  # noqa: E402
from db.repos.prompt_versions_repo import load_active, save_new  # noqa: E402

_PROMPTS_DIR = _ROOT / "config" / "prompts"

# agent_name → 文件名（不带扩展名）
_AGENTS = {
    "supervisor": "supervisor",
    "research":   "research",
    "screener":   "screener",
    "skeptic":    "skeptic",
    "trigger":    "trigger",
}


def seed(force: bool = False) -> None:
    with get_session() as sess:
        for agent_name, filename in _AGENTS.items():
            md_path = _PROMPTS_DIR / f"{filename}.md"
            if not md_path.exists():
                print(f"[skip] {agent_name}: {md_path} 不存在")
                continue

            existing = load_active(sess, agent_name)
            if existing and not force:
                print(f"[skip] {agent_name}: DB 已有激活版本（加 --force 强制追加）")
                continue

            content = md_path.read_text(encoding="utf-8")
            comment = "从 config/prompts 文件导入" if not force else "手动从文件重新导入"
            new_code = save_new(
                sess,
                agent_name=agent_name,
                content=content,
                comment=comment,
                author="seed_script",
                activate=True,
            )
            print(f"[seed] {agent_name} ← {md_path.name} (version {new_code})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="已有版本时也再追加一条")
    args = parser.parse_args()
    seed(force=args.force)
