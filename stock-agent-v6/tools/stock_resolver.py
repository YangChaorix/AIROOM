"""股票代码 ↔ 公司名解析 + 行业反查（Phase 4）。

底层：AkShare stock_info_a_code_name() 返回全市场 A 股 (code, name) 表（Sina，稳定）。
输入：
- 6 位纯数字代码 → 精确查 code
- 非 6 位数字 → 按 name 匹配（先精确，再包含）

行业反查策略：
1. 查 `data/industry_leaders_map.json` 反查
2. 若表里没有，调 AkShare stock_individual_info_em(symbol=code) 取"所属行业"字段
3. 仍失败 → 标为"未分类"
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import akshare as ak

from tools._cache import ttl_cache

_DATA_DIR = Path(__file__).parent.parent / "data"
_INDUSTRY_MAP_PATH = _DATA_DIR / "industry_leaders_map.json"


@ttl_cache(seconds=86400)  # 全市场清单每天刷新一次
def _load_code_name_table() -> List[Dict[str, str]]:
    df = ak.stock_info_a_code_name()  # cols: code, name
    return df.to_dict("records")


def _infer_industry_from_map(code: str) -> Optional[str]:
    try:
        table = json.loads(_INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    for industry_name, entries in table.items():
        if industry_name.startswith("_"):
            continue
        if any(e["code"] == code for e in entries):
            return industry_name
    return None


@ttl_cache(seconds=3600)
def _infer_industry_from_akshare(code: str) -> Optional[str]:
    try:
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return None
        # 返回 item-value 键值对结构
        for _, row in df.iterrows():
            if row.get("item") == "行业":
                industry = str(row.get("value", "")).strip()
                return industry or None
    except Exception:
        pass
    return None


def resolve(stock: str) -> Dict[str, Any]:
    """返回 {"code": "300750", "name": "宁德时代", "industry": "动力电池"}。

    找不到时 raise ValueError。
    """
    stock = stock.strip()
    if not stock:
        raise ValueError("股票输入为空")

    table = _load_code_name_table()
    if stock.isdigit() and len(stock) == 6:
        hits = [r for r in table if r.get("code") == stock]
    else:
        hits = [r for r in table if r.get("name") == stock]  # 先精确
        if not hits:
            hits = [r for r in table if stock in str(r.get("name", ""))]  # 再包含

    if not hits:
        raise ValueError(f"无法找到股票：{stock}")

    if len(hits) > 1:
        names = [f"{h.get('code')} {h.get('name')}" for h in hits[:5]]
        print(f"[stock_resolver] 多个匹配，默认取第一个；候选：{names}", file=sys.stderr)

    code = hits[0].get("code")
    name = hits[0].get("name")

    industry = (
        _infer_industry_from_map(code)
        or _infer_industry_from_akshare(code)
        or "未分类"
    )
    return {"code": code, "name": name, "industry": industry}


def fetch_peers(industry: str, exclude_code: str, limit: int = 2) -> List[Dict[str, str]]:
    """从 industry_leaders_map.json 拉同行业对标股（排除主股自身）。"""
    try:
        table = json.loads(_INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries: List[Dict[str, str]] = []
    for key, val in table.items():
        if key.startswith("_"):
            continue
        if key == industry or industry in key or key in industry:
            entries = val
            break
    return [e for e in entries if e.get("code") != exclude_code][:limit]
