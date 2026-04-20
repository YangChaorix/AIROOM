"""把单股分析请求合成为一条 Trigger（复用现有流水线）。

结构与 live/fixture trigger 完全一致，仅多 focus_codes / focus_primary 字段指示
Research 只聚焦这几只股。Phase 3 DB：这些字段会落入 triggers.metadata_json。
"""
from datetime import datetime
from typing import Any, Dict

from tools.stock_resolver import fetch_peers, resolve


def build_single_stock_trigger(stock: str, with_peers: bool = True) -> Dict[str, Any]:
    """根据输入（code 或 name）构造个股分析 Trigger。"""
    main = resolve(stock)
    peers = fetch_peers(main["industry"], main["code"], limit=2) if with_peers else []
    focus_codes = [main["code"]] + [p["code"] for p in peers]
    peer_names = [p["name"] for p in peers]
    peer_label = "、".join(peer_names) if peer_names else "无对标"

    now = datetime.now()
    return {
        "trigger_id": f"T-STOCK-{main['code']}-{now.strftime('%Y%m%d%H%M%S')}",
        "headline": f"个股深度分析：{main['name']}（对标 {peer_label}）",
        "industry": main["industry"],
        "type": "individual_stock_analysis",
        "strength": "medium",
        "source": "user_request",
        "published_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": (
            f"用户请求分析 {main['name']}（{main['code']}，行业：{main['industry']}）。"
            f"本次同时拉取对标股 {peer_label} 做横向对比。"
        ),
        # ★ Phase 4 新字段（进 triggers.metadata_json）
        "focus_codes": focus_codes,
        "focus_primary": main["code"],
        "peer_names": peer_names,
    }
