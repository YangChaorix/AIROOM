"""把 config/user_profile.json 导入 users + conditions 表。

用法：
    python scripts/seed_from_json.py
    python scripts/seed_from_json.py --profile config/user_profile.json --user-id dad_001
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from db.engine import get_session  # noqa: E402
from db.repos.users_repo import upsert_condition, upsert_user  # noqa: E402


def seed(profile_path: Path, user_id_override: Optional[str] = None) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    user_id = user_id_override or profile.get("user_id", "default")
    name = profile.get("name", user_id)
    adv = profile.get("advanced_settings", {})

    with get_session() as sess:
        upsert_user(
            sess,
            user_id=user_id,
            name=name,
            recommendation_threshold=adv.get("recommendation_threshold", 0.65),
            trading_style=adv.get("trading_style"),
        )
        sess.flush()  # 让 User 先落库，满足 conditions 的 FK 约束
        for cond in profile.get("conditions", []):
            upsert_condition(sess, user_id=user_id, cond=cond)
        sess.commit()

    print(f"Seeded user_id={user_id} with {len(profile.get('conditions', []))} conditions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=str(_ROOT / "config" / "user_profile.json"))
    parser.add_argument("--user-id", dest="user_id", default=None,
                        help="覆盖 JSON 里的 user_id（方便多 profile）")
    args = parser.parse_args()
    seed(Path(args.profile), args.user_id)
