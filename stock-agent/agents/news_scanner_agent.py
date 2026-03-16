"""
新闻扫描 + 行业关键词匹配（Python纯规则，0 LLM token）

流程：
1. 拉取今日 CCTV新闻联播 + 同花顺全球财经快讯
2. 从标题中提取命中的行业关键词
3. 给候选股票打新闻相关度分
"""

import re
from datetime import datetime, timedelta
from typing import Any

import akshare as ak


# 行业关键词映射表：行业名称 → 触发关键词列表
# 关键词与 stock_individual_info_em 返回的「行业」字段做模糊匹配
INDUSTRY_KEYWORD_MAP: dict[str, list[str]] = {
    # 大消费
    "白酒":     ["白酒", "酱香", "茅台", "五粮液", "汾酒", "洋河", "酒类", "烈酒"],
    "食品饮料": ["食品", "饮料", "消费品", "以旧换新", "消费升级", "餐饮", "乳制品"],
    "医药":     ["医药", "医疗", "医保", "新药", "药品", "创新药", "生物医药", "疫苗", "临床试验"],
    "零售":     ["零售", "商超", "电商", "消费券", "促消费", "内需"],
    # 科技
    "半导体":   ["半导体", "芯片", "集成电路", "晶圆", "存储", "算力", "EDA", "光刻"],
    "人工智能": ["人工智能", "AI", "大模型", "智能", "机器人", "具身智能", "AGI", "算法"],
    "北斗导航": ["北斗", "卫星导航", "卫星", "航天", "低空经济", "无人机"],
    "软件":     ["软件", "信创", "国产化", "数字化", "云计算", "SaaS", "操作系统"],
    # 新能源
    "电池":     ["电池", "储能", "锂电", "碳酸锂", "钠电池", "固态电池", "充电"],
    "光伏设备": ["光伏", "太阳能", "组件", "硅料", "逆变器"],
    "风电设备": ["风电", "风机", "海上风电", "陆上风电"],
    "新能源车": ["新能源车", "电动车", "EV", "汽车", "造车", "换电"],
    # 金融
    "银行":     ["银行", "信贷", "存款", "贷款", "降准", "降息", "LPR", "货币政策"],
    "保险":     ["保险", "养老保险", "社保", "险资"],
    "证券":     ["券商", "证券", "资本市场", "IPO", "注册制", "并购"],
    "房地产":   ["房地产", "房产", "购房", "楼市", "首付", "房贷", "商业用房"],
    # 基建/工业
    "建筑":     ["基建", "建设", "工程", "专项债", "超长期国债", "城镇化", "PPP"],
    "钢铁":     ["钢铁", "钢材", "铁矿石", "粗钢"],
    "化工":     ["化工", "化学品", "MDI", "聚氨酯", "涂料"],
    "有色金属": ["有色", "铜", "铝", "锌", "镍", "黄金", "贵金属", "锂矿", "稀土"],
    # 能源
    "煤炭":     ["煤炭", "煤矿", "动力煤", "焦煤"],
    "石油":     ["石油", "天然气", "LNG", "原油", "页岩气", "油气"],
    # 农业
    "农业":     ["农业", "农村", "粮食", "种业", "化肥", "农药", "生猪", "养殖"],
    # 交通物流
    "交运":     ["交通", "物流", "运输", "高铁", "港口", "航运", "快递", "供应链"],
    # 军工
    "军工":     ["军工", "国防", "武器", "军事", "导弹", "航母", "歼击机"],
    # 医疗器械
    "医疗器械": ["医疗器械", "耗材", "IVD", "手术机器人", "影像"],
}


def fetch_todays_news() -> dict[str, Any]:
    """
    拉取今日 CCTV新闻联播 + 同花顺全球财经快讯

    Returns:
        {
            "titles": [str, ...],    # 所有标题列表（用于关键词匹配）
            "summary": str,          # 精简摘要（用于LLM预筛输入）
        }
    """
    titles = []

    # 同花顺全球财经快讯（实时，最多20条）
    try:
        df = ak.stock_info_global_ths()
        if df is not None and not df.empty:
            titles += df["标题"].tolist()
    except Exception:
        pass

    # 央视新闻联播（当天可能无数据，往前最多3天）
    try:
        for delta in range(3):
            date_str = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
            df = ak.news_cctv(date=date_str)
            if df is not None and not df.empty:
                titles += df["title"].tolist()
                break
    except Exception:
        pass

    # 生成精简摘要（取前15条标题，供LLM预筛使用）
    summary = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles[:15]))

    return {"titles": titles, "summary": summary}


def extract_hot_industries(news_titles: list[str]) -> dict[str, int]:
    """
    从新闻标题中提取命中的行业及命中次数

    Returns:
        {"白酒": 2, "半导体": 1, ...}
    """
    hit_count: dict[str, int] = {}
    combined_text = " ".join(news_titles)

    for industry, keywords in INDUSTRY_KEYWORD_MAP.items():
        count = sum(combined_text.count(kw) for kw in keywords)
        if count > 0:
            hit_count[industry] = count

    return hit_count


def score_stocks_by_news(
    stocks: list[dict[str, Any]],
    hot_industries: dict[str, int],
) -> list[dict[str, Any]]:
    """
    根据新闻命中行业给候选股票打分，并按综合得分排序

    综合得分 = 涨幅归一化分 * 0.5 + 新闻匹配分 * 0.5
    """
    if not stocks:
        return stocks

    max_pct = max(s["涨跌幅"] for s in stocks) or 1.0

    for s in stocks:
        industry = s.get("行业", "")
        news_score = 0

        # 精确匹配：行业字段包含热点行业名
        for hot_industry, hit_count in hot_industries.items():
            if hot_industry in industry or industry in hot_industry:
                news_score += hit_count * 10
                s.setdefault("命中新闻", []).append(hot_industry)

        # 股票名称兜底匹配（部分股名含行业关键词）
        if news_score == 0:
            name = s.get("名称", "")
            for hot_industry, hit_count in hot_industries.items():
                for kw in INDUSTRY_KEYWORD_MAP.get(hot_industry, []):
                    if kw in name:
                        news_score += hit_count * 5
                        s.setdefault("命中新闻", []).append(hot_industry)
                        break

        pct_score = (s["涨跌幅"] / max_pct) * 100
        s["新闻匹配分"] = news_score
        s["综合初筛分"] = round(pct_score * 0.5 + min(news_score, 100) * 0.5, 1)
        s.setdefault("命中新闻", [])

    return sorted(stocks, key=lambda x: x["综合初筛分"], reverse=True)
