"""Research Agent 的真实工具集合（AkShare）。

与旧版 mock_research_tools.py 的函数签名**完全一致**——agents/research.py 和
config/tools/research_tools.json 无需改动，只是把底层从写死数据换成 AkShare 调用。

底层接口 & 局限：
- search_news_from_db : news_cctv + stock_info_cjzc_em + stock_info_global_em
                        （AkShare 不支持关键词检索，本地过滤近 48 h 要闻）
- akshare_industry_leaders : stock_board_industry_cons_em（eastmoney push 接口）
                             失败时降级到 data/industry_leaders_map.json 表
- stock_financial_data : stock_financial_abstract（Sina）+ 可选 stock_zh_a_daily 最新收盘
- stock_holder_structure : stock_main_stock_holder（eastmoney info 接口，稳定）
- stock_technical_indicators : stock_zh_a_daily（Sina）→ pandas 计算 MA20/MACD/量能
- price_trend_data : futures_spot_price（现货价格汇总）近 N 日对比

所有函数 **不 raise**：失败时把错误放入返回 JSON 的 data_gap / error 字段。
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import akshare as ak
import pandas as pd

from tools._cache import ttl_cache

_DATA_DIR = Path(__file__).parent.parent / "data"
_INDUSTRY_MAP_PATH = _DATA_DIR / "industry_leaders_map.json"


def _j(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _safe(func):
    """把异常转成带 error 字段的 JSON 返回，保证工具层不 raise。"""
    from functools import wraps

    @wraps(func)
    def wrapped(*args, **kwargs) -> str:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return _j({
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "tool": func.__name__,
                "args": {"args": args, "kwargs": kwargs},
                "data_gap": f"工具 {func.__name__} 执行失败，下游请记入 data_gaps",
            })

    return wrapped


# ───────────────────────────────────────────────────────────────
# 1) search_news_from_db
# ───────────────────────────────────────────────────────────────

@ttl_cache(seconds=600)
def _load_recent_news(limit_global: int = 200) -> List[Dict[str, Any]]:
    """合并几个 AkShare 新闻源，返回统一结构。"""
    items: List[Dict[str, Any]] = []

    # 央视网时政新闻
    try:
        df = ak.news_cctv()
        for _, row in df.iterrows():
            items.append({
                "title": row.get("title", ""),
                "content": str(row.get("content", ""))[:500],
                "source": "央视网",
                "published_at": str(row.get("date", "")),
            })
    except Exception:
        pass

    # 东财财经早餐
    try:
        df = ak.stock_info_cjzc_em()
        for _, row in df.head(limit_global).iterrows():
            items.append({
                "title": row.get("标题", row.get("title", "")),
                "content": str(row.get("摘要", row.get("content", "")))[:500],
                "source": "东财-财经早餐",
                "published_at": str(row.get("发布时间", row.get("date", ""))),
            })
    except Exception:
        pass

    # 东财全球资讯
    try:
        df = ak.stock_info_global_em()
        for _, row in df.head(limit_global).iterrows():
            items.append({
                "title": row.get("标题", ""),
                "content": str(row.get("摘要", ""))[:500],
                "source": "东财-全球资讯",
                "published_at": str(row.get("发布时间", "")),
            })
    except Exception:
        pass

    return items


@_safe
def search_news_from_db(keywords: str, hours: int = 48) -> str:
    """按关键词 + 时间窗口从 AkShare 新闻源聚合检索。

    局限：AkShare 不支持服务端关键词检索，本函数拉近期要闻后在本地过滤。
    """
    all_items = _load_recent_news()
    kws = [k.strip() for k in keywords.replace("，", ",").replace(" ", ",").split(",") if k.strip()]

    def hit(item: Dict[str, Any]) -> bool:
        text = f"{item.get('title','')} {item.get('content','')}"
        return any(kw in text for kw in kws) if kws else False

    matched = [it for it in all_items if hit(it)]
    # 截断前 15 条，避免塞爆 LLM
    matched = matched[:15]
    return _j({
        "keywords": keywords,
        "hours": hours,
        "results": [{"title": it["title"][:120], "source": it["source"],
                     "published_at": it["published_at"]} for it in matched],
        "total": len(matched),
        "note": "AkShare 不支持关键词检索，本函数拉最近约 600 条要闻后在本地过滤" if not matched else None,
    })


# ───────────────────────────────────────────────────────────────
# 2) akshare_industry_leaders
# ───────────────────────────────────────────────────────────────

def _load_industry_map() -> Dict[str, Any]:
    return json.loads(_INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))


@_safe
def akshare_industry_leaders(industry: str) -> str:
    """查询某行业的龙头企业名单。

    优先调 AkShare stock_board_industry_cons_em；该接口不可用时降级到 data/industry_leaders_map.json。
    """
    # Primary: AkShare
    leaders: List[Dict[str, str]] = []
    source = "akshare"
    try:
        df = ak.stock_board_industry_cons_em(symbol=industry)
        # 按总市值降序取前 5
        if "总市值" in df.columns:
            df = df.sort_values("总市值", ascending=False)
        for _, row in df.head(5).iterrows():
            leaders.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "leadership": f"{industry} 板块，总市值 {row.get('总市值', 'n/a')}",
            })
    except Exception:
        pass  # 走降级

    # Fallback: industry_leaders_map.json
    if not leaders:
        source = "industry_leaders_map.json (fallback)"
        table = _load_industry_map()
        for key, entries in table.items():
            if key.startswith("_"):
                continue
            if industry in key or key in industry:
                leaders = [
                    {"code": e["code"], "name": e["name"], "leadership": e.get("note", "")}
                    for e in entries
                ]
                break

    return _j({
        "industry": industry,
        "leaders": leaders,
        "source": source,
        "data_gap": None if leaders else f"未找到行业「{industry}」的龙头映射",
    })


# ───────────────────────────────────────────────────────────────
# 3) stock_financial_data
# ───────────────────────────────────────────────────────────────

def _try_db_get(getter, *args):
    """尝试从 DB 取缓存；任何异常都返回 None（让上层 fallback AkShare）。"""
    try:
        from db.engine import get_session
        with get_session() as sess:
            return getter(sess, *args)
    except Exception:
        return None


def _try_db_upsert(upserter, *args, **kwargs) -> None:
    try:
        from db.engine import get_session
        with get_session() as sess:
            upserter(sess, *args, **kwargs)
    except Exception:
        pass


@_safe
def stock_financial_data(code: str) -> str:
    """查询某股票的财务数据：营收/净利/毛利率等近几期。

    底层：stock_financial_abstract（Sina，稳定）+ DB 快照缓存（跨运行复用，按当日缓存）。
    """
    code = str(code).zfill(6)
    # ── Phase 3 缓存：(code, today) 命中则直接返回 ──
    from db.repos.snapshots_repo import get_financial, upsert_financial, _today
    today_date = _today()
    cached = _try_db_get(get_financial, code, today_date)
    if cached:
        return _j(cached)

    df = ak.stock_financial_abstract(symbol=code)
    if df is None or df.empty:
        return _j({"code": code, "error": "empty financial data"})

    # 报告期列：8 位数字日期；降序排列（最新在前）
    period_cols = sorted(
        [c for c in df.columns if isinstance(c, str) and c.isdigit() and len(c) == 8],
        reverse=True,
    )[:8]

    # 抽出关键指标
    key_metrics = ["营业收入", "归属母公司净利润", "净利润", "毛利率", "市盈率", "每股收益", "净资产收益率"]
    snapshot: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        indicator = str(row.get("指标", ""))
        if any(m in indicator for m in key_metrics):
            snapshot[indicator] = {p: row.get(p) for p in period_cols}
            if len(snapshot) >= 12:
                break

    # 报告期字符串规整，寻找同比（去年同期）对比项，避免 Q1 vs Q4 的累计误差
    latest_period = period_cols[0] if period_cols else ""

    def _yoy_period(p: str) -> str:
        """返回去年同期的 period key（例如 20260331 → 20250331）。"""
        if len(p) == 8:
            return str(int(p[:4]) - 1) + p[4:]
        return ""

    yoy_period = _yoy_period(latest_period)

    lines: List[str] = []
    for indicator, values in snapshot.items():
        latest = values.get(latest_period)
        yoy = values.get(yoy_period) if yoy_period in values else None
        if pd.notna(latest):
            line = f"{indicator}({latest_period}): {latest}"
            # 同比（YoY）：与去年同期比较，语义稳定；避免 Q1-vs-Q4 的错误"环比"
            if pd.notna(yoy) and isinstance(latest, (int, float)) and isinstance(yoy, (int, float)) and yoy:
                chg = (latest - yoy) / abs(yoy) * 100
                line += f" (同比 {chg:+.1f}%, 去年同期 {yoy})"
            lines.append(line)

    financial_summary = "；".join(lines[:8]) if lines else "无财务数据"

    payload = {
        "code": code,
        "latest_period": latest_period,
        "yoy_period": yoy_period,
        "financial_summary": financial_summary,
        "raw_keys": list(snapshot.keys()),
        "source": "sina (stock_financial_abstract)",
        "note": "同比=当期 vs 去年同期；避免跨季度累计口径造成的伪环比",
    }
    _try_db_upsert(upsert_financial, code, today_date, payload)
    return _j(payload)


# ───────────────────────────────────────────────────────────────
# 4) stock_holder_structure
# ───────────────────────────────────────────────────────────────

_SMART_MONEY_HINTS = ("基金", "投资", "资产", "资本", "私募", "有限合伙")
_STATE_HINTS = ("国资", "国有", "社保", "养老", "汇金", "控股有限公司", "集团")
# HKSCC / NOMINEES 是港股通/QFII 托管席位，大量 A 股外资持仓会以此身份出现
_FOREIGN_HINTS = (
    "香港中央结算", "HKSCC", "NOMINEES",
    "QFII", "摩根", "贝莱德", "先锋", "花旗", "高盛", "瑞银", "瑞信",
)


@_safe
def stock_holder_structure(code: str) -> str:
    """查询某股票的前十大股东构成 + 聪明钱 / 国资 / 外资粗分类。

    底层：stock_main_stock_holder（eastmoney）+ DB 快照缓存。
    """
    code = str(code).zfill(6)
    from db.repos.snapshots_repo import get_holder, upsert_holder, _today
    today_date = _today()
    cached = _try_db_get(get_holder, code, today_date)
    if cached:
        return _j(cached)

    df = ak.stock_main_stock_holder(stock=code)
    if df is None or df.empty:
        return _j({"code": code, "error": "empty holder data"})

    # 取最新公告期
    latest_date = df["截至日期"].max() if "截至日期" in df.columns else None
    if latest_date is not None:
        latest = df[df["截至日期"] == latest_date].copy()
    else:
        latest = df.head(10).copy()
    # 取前 10 大
    latest = latest.head(10)

    smart_pct = state_pct = foreign_pct = 0.0
    total_pct = 0.0
    holder_lines: List[str] = []
    for _, row in latest.iterrows():
        name = str(row.get("股东名称", ""))
        raw_pct = row.get("持股比例", None)
        pct = float(raw_pct) if pd.notna(raw_pct) else 0.0
        total_pct += pct
        holder_lines.append(f"{name}({pct:.2f}%)" if pct > 0 else f"{name}(持股未披露)")
        if any(h in name for h in _FOREIGN_HINTS):
            foreign_pct += pct
        elif any(h in name for h in _STATE_HINTS):
            state_pct += pct
        elif any(h in name for h in _SMART_MONEY_HINTS):
            smart_pct += pct

    holder_structure = (
        f"截至 {latest_date}：前十大股东合计占比约 {total_pct:.1f}%；"
        f"聪明钱(基金/资本/私募) {smart_pct:.1f}%，"
        f"国资/社保 {state_pct:.1f}%，外资 {foreign_pct:.1f}%。"
        f"具体：{'; '.join(holder_lines[:5])}"
    )

    payload = {
        "code": code,
        "as_of": str(latest_date),
        "holder_structure": holder_structure,
        "smart_money_pct": round(smart_pct, 2),
        "state_pct": round(state_pct, 2),
        "foreign_pct": round(foreign_pct, 2),
        "source": "eastmoney (stock_main_stock_holder)",
    }
    _try_db_upsert(upsert_holder, code, today_date, payload)
    return _j(payload)


# ───────────────────────────────────────────────────────────────
# 5) stock_technical_indicators
# ───────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


@_safe
def stock_technical_indicators(code: str) -> str:
    """计算量能 / MA20 / MACD。

    底层：stock_zh_a_daily（Sina 日K）+ DB 快照缓存。
    """
    code = str(code).zfill(6)
    from db.repos.snapshots_repo import get_technical, upsert_technical, _today
    today_date = _today()
    cached = _try_db_get(get_technical, code, today_date)
    if cached:
        return _j(cached)

    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust="")
    if df is None or df.empty or len(df) < 20:
        return _j({"code": code, "error": "日K 数据不足", "rows": len(df) if df is not None else 0})

    df = df.sort_values("date").reset_index(drop=True)
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma5"] = df["close"].rolling(5).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # MACD
    ema12 = _ema(df["close"], 12)
    ema26 = _ema(df["close"], 26)
    df["dif"] = ema12 - ema26
    df["dea"] = _ema(df["dif"], 9)
    df["macd"] = (df["dif"] - df["dea"]) * 2

    last = df.iloc[-1]
    prev = df.iloc[-2]

    vol_ratio = float(last["volume"] / last["vol_ma20"]) if pd.notna(last["vol_ma20"]) and last["vol_ma20"] > 0 else None
    # macd_signal 是 DB 枚举：英文值（golden_cross / death_cross / no_cross）
    # 自然语言摘要里的中文描述由 _MACD_LABEL 映射产生
    macd_cross = None
    if pd.notna(prev["dif"]) and pd.notna(prev["dea"]) and pd.notna(last["dif"]) and pd.notna(last["dea"]):
        if prev["dif"] < prev["dea"] and last["dif"] > last["dea"]:
            macd_cross = "golden_cross"
        elif prev["dif"] > prev["dea"] and last["dif"] < last["dea"]:
            macd_cross = "death_cross"
        else:
            macd_cross = "no_cross"

    _MACD_LABEL = {"golden_cross": "金叉", "death_cross": "死叉", "no_cross": "无交叉"}
    macd_display = _MACD_LABEL.get(macd_cross, macd_cross) if macd_cross else None

    summary_parts = [
        f"最新收盘 {last['close']:.2f}",
        f"MA5 {last['ma5']:.2f}" if pd.notna(last["ma5"]) else None,
        f"MA20 {last['ma20']:.2f}" if pd.notna(last["ma20"]) else None,
        f"成交量/20日均量 {vol_ratio:.2f}x" if vol_ratio else None,
        f"MACD {macd_display}" if macd_display else None,
    ]
    technical_summary = "；".join(p for p in summary_parts if p)

    payload = {
        "code": code,
        "as_of": str(last["date"]),
        "technical_summary": technical_summary,
        "close": float(last["close"]),
        "ma20": float(last["ma20"]) if pd.notna(last["ma20"]) else None,
        "volume_ratio": vol_ratio,
        "macd_signal": macd_cross,
        "source": "sina (stock_zh_a_daily) + pandas",
    }
    _try_db_upsert(upsert_technical, code, today_date, payload)
    return _j(payload)


# ───────────────────────────────────────────────────────────────
# 6) price_trend_data
# ───────────────────────────────────────────────────────────────

# AkShare 现货汇总覆盖的典型产品关键词 → symbol 映射（可按需扩展）
_COMMODITY_MAP = {
    "铜": "CU", "铝": "AL", "锌": "ZN", "铅": "PB", "镍": "NI", "锡": "SN", "黄金": "AU", "白银": "AG",
    "螺纹钢": "RB", "热卷": "HC", "铁矿": "I", "焦炭": "J", "焦煤": "JM", "锰硅": "SM", "硅铁": "SF",
    "玻璃": "FG", "纯碱": "SA", "尿素": "UR", "甲醇": "MA", "PTA": "TA", "PVC": "V", "塑料": "L", "聚丙烯": "PP",
    "豆粕": "M", "豆油": "Y", "棕榈": "P", "白糖": "SR", "棉花": "CF", "苹果": "AP", "鸡蛋": "JD", "生猪": "LH",
    "碳酸锂": "LC", "工业硅": "SI",
}


def _find_symbol(product: str) -> str:
    for k, v in _COMMODITY_MAP.items():
        if k in product:
            return v
    return ""


@_safe
def price_trend_data(product: str) -> str:
    """查询某大宗商品 / 中间品的近期价格走势。

    底层：futures_spot_price（每日现货汇总）；只覆盖大宗期货品种。
    非大宗（如某型号电池、特定化学品）返回 data_gap。
    """
    symbol = _find_symbol(product)
    if not symbol:
        return _j({
            "product": product,
            "trend_summary": None,
            "data_gap": f"AkShare futures_spot_price 不覆盖「{product}」这类产品",
            "covered_list": list(_COMMODITY_MAP.keys())[:20],
        })

    today = datetime.now()
    snapshots: List[Dict[str, Any]] = []
    for i in range(0, 30, 3):
        date_str = (today - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = ak.futures_spot_price(date_str)
            if df is None or df.empty:
                continue
            row = df[df["symbol"].astype(str).str.upper() == symbol]
            if not row.empty:
                r = row.iloc[0]
                snapshots.append({
                    "date": date_str,
                    "spot": float(r.get("spot_price", 0)),
                    "dominant": float(r.get("dominant_contract_price", 0)),
                })
                if len(snapshots) >= 6:
                    break
        except Exception:
            continue

    if not snapshots:
        return _j({
            "product": product,
            "trend_summary": None,
            "data_gap": f"近 30 日未取得「{product}」({symbol}) 现货价格",
        })

    first_spot = snapshots[-1]["spot"]  # 最早
    last_spot = snapshots[0]["spot"]  # 最新
    chg_pct = (last_spot - first_spot) / first_spot * 100 if first_spot else 0.0

    trend_summary = (
        f"{product}({symbol}) 现货：{first_spot:.0f} ({snapshots[-1]['date']}) → "
        f"{last_spot:.0f} ({snapshots[0]['date']})，涨幅 {chg_pct:+.2f}%。"
    )

    return _j({
        "product": product,
        "symbol": symbol,
        "trend_summary": trend_summary,
        "snapshots": snapshots,
        "source": "akshare (futures_spot_price)",
    })


# ───────────────────────────────────────────────────────────────
# 函数映射表（agents/research.py 按 research_tools.json 的 name 查表）
# ───────────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "search_news_from_db": search_news_from_db,
    "akshare_industry_leaders": akshare_industry_leaders,
    "stock_financial_data": stock_financial_data,
    "stock_holder_structure": stock_holder_structure,
    "stock_technical_indicators": stock_technical_indicators,
    "price_trend_data": price_trend_data,
}
