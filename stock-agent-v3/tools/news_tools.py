"""
新闻采集工具（v1.1 升级）
获取发改委/财联社/新华社/同花顺等来源的新闻
v1.1 新增：财联社电报（stock_telegraph_cls_em）带容错处理
供 trigger_agent 使用
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

import akshare as ak
import pandas as pd

from config.settings import settings

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

logger = logging.getLogger(__name__)


def _truncate(text: str, max_len: int = 300) -> str:
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().replace("\n", " ").replace("\r", "")
    return text[:max_len] + "..." if len(text) > max_len else text


def _parse_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
        try:
            dt = datetime.strptime(str(date_str)[: len(fmt)], fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return str(date_str)


def get_today_macro_news() -> list[dict]:
    """
    获取今日宏观政策新闻（财联社快讯 + 东方财富 + 同花顺）
    返回新闻列表，供 trigger_agent 分析触发条件
    """
    news_list = []
    seen_titles: set[str] = set()

    def _add(item: dict):
        title = item.get("标题", "")
        if title and title != "nan" and title not in seen_titles:
            seen_titles.add(title)
            news_list.append(item)

    # 1. 财联社快讯
    try:
        df = ak.stock_info_global_cls()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                time_str = (
                    str(row.get("发布日期", "")) + " " + str(row.get("发布时间", ""))
                )
                _add(
                    {
                        "标题": _truncate(str(row.get("标题", "")), 200),
                        "内容": _truncate(str(row.get("内容", "")), 300),
                        "来源": "财联社",
                        "时间": _parse_date(time_str.strip()),
                    }
                )
    except Exception as e:
        logger.warning(f"财联社快讯获取失败: {e}")
        news_list.append({"来源": "财联社", "错误": str(e)})

    # 2. 东方财富快讯（200条，覆盖全天）
    try:
        df = ak.stock_info_global_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _add(
                    {
                        "标题": _truncate(str(row.get("标题", "")), 200),
                        "内容": _truncate(str(row.get("摘要", "")), 300),
                        "来源": "东方财富",
                        "时间": _parse_date(str(row.get("发布时间", ""))),
                    }
                )
    except Exception as e:
        logger.warning(f"东方财富快讯获取失败: {e}")
        news_list.append({"来源": "东方财富", "错误": str(e)})

    # 3. 同花顺快讯
    try:
        df = ak.stock_info_global_ths()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _add(
                    {
                        "标题": _truncate(str(row.get("标题", "")), 200),
                        "内容": _truncate(str(row.get("内容", "")), 300),
                        "来源": "同花顺",
                        "时间": _parse_date(str(row.get("发布时间", ""))),
                    }
                )
    except Exception as e:
        logger.warning(f"同花顺快讯获取失败: {e}")
        news_list.append({"来源": "同花顺", "错误": str(e)})

    return news_list


def get_cls_telegraph() -> list[dict]:
    """
    获取财联社电报（v1.1 新增）
    使用 ak.stock_telegraph_cls_em()，带容错处理

    Returns:
        电报列表，每条含 {标题, 内容, 来源, 时间}
        如果接口失败，返回包含错误信息的列表
    """
    try:
        df = ak.stock_telegraph_cls_em()
        if df is None or df.empty:
            logger.info("财联社电报：接口返回空数据")
            return []

        results = []
        for _, row in df.iterrows():
            # 尝试多种可能的列名
            title = str(
                row.get("标题", row.get("title", row.get("content", "")))
            )
            content = str(
                row.get("内容", row.get("content", row.get("summary", "")))
            )
            time_val = str(
                row.get("发布时间", row.get("time", row.get("pub_time", "")))
            )

            if not title or title == "nan":
                continue

            results.append(
                {
                    "标题": _truncate(title, 200),
                    "内容": _truncate(content, 300),
                    "来源": "财联社电报",
                    "时间": _parse_date(time_val),
                }
            )

        logger.info(f"财联社电报获取成功：{len(results)} 条")
        return results

    except AttributeError:
        # akshare 版本不支持此接口
        msg = "财联社电报接口不可用（当前 akshare 版本可能不支持 stock_telegraph_cls_em）"
        logger.warning(msg)
        return [{"来源": "财联社电报", "错误": msg}]
    except Exception as e:
        logger.warning(f"财联社电报获取失败: {e}")
        return [{"来源": "财联社电报", "错误": str(e)}]


def get_policy_news() -> list[dict]:
    """
    获取财经政策新闻（专注于实质性政策）
    来源：新浪财经全球快讯 + 财新
    （stock_news_main_sina 已废弃，替换为 stock_info_global_sina + stock_news_main_cx）
    """
    news_list = []
    seen_titles: set[str] = set()

    # 1. 新浪财经全球快讯（替换废弃的 stock_news_main_sina）
    try:
        df = ak.stock_info_global_sina()
        if df is not None and not df.empty:
            for _, row in df.head(30).iterrows():
                content = _truncate(str(row.get("内容", "")), 300)
                if content and content != "nan" and content not in seen_titles:
                    seen_titles.add(content)
                    news_list.append({
                        "标题": content[:80],   # 新浪只有内容字段，截取前80字作为标题
                        "内容": content,
                        "来源": "新浪财经",
                        "时间": _parse_date(str(row.get("时间", ""))),
                    })
    except Exception as e:
        logger.debug(f"新浪财经快讯获取失败: {e}")

    # 2. 财新财经新闻（政策类质量较高）
    try:
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            for _, row in df.head(20).iterrows():
                summary = _truncate(str(row.get("summary", "")), 300)
                if summary and summary != "nan" and summary not in seen_titles:
                    seen_titles.add(summary)
                    news_list.append({
                        "标题": summary[:80],
                        "内容": summary,
                        "来源": "财新",
                        "时间": "",
                    })
    except Exception as e:
        logger.debug(f"财新新闻获取失败: {e}")

    return news_list


def get_ndrc_news(max_articles: int = 5) -> list[dict]:
    """
    爬取国家发改委官网新闻发布页，获取最新政策动态
    来源：https://www.ndrc.gov.cn/xwdt/xwfb/

    Args:
        max_articles: 抓取的文章数量（每篇会额外请求正文），默认5篇

    Returns:
        新闻列表，每条含 {标题, 内容, 来源, 时间, url}
    """
    base_url = "https://www.ndrc.gov.cn"
    list_url = f"{base_url}/xwdt/xwfb/"
    results = []

    try:
        r = requests.get(list_url, headers=_HTTP_HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            logger.warning(f"发改委页面请求失败: status={r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.select("ul.u-list li a, li > a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if title and len(title) > 5 and href:
                # 补全相对路径
                if href.startswith("./"):
                    href = f"{base_url}/xwdt/xwfb/{href[2:]}"
                elif href.startswith("/"):
                    href = f"{base_url}{href}"
                links.append({"title": title, "url": href})

        logger.info(f"发改委新闻列表获取成功：共 {len(links)} 条，抓取前 {max_articles} 篇正文")

        for item in links[:max_articles]:
            try:
                ar = requests.get(item["url"], headers=_HTTP_HEADERS, timeout=10)
                ar.encoding = "utf-8"
                asoup = BeautifulSoup(ar.text, "html.parser")
                # 发改委文章结构：正文在 .TRS_Editor（直接文本节点，无p标签）
                content_div = asoup.select_one(".TRS_Editor")
                if content_div:
                    content = content_div.get_text(separator=" ", strip=True)
                else:
                    content = ""
                time_tag = asoup.select_one(".time")
                pub_time = time_tag.get_text(strip=True) if time_tag else ""
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": _truncate(content, 500),
                    "来源": "国家发改委",
                    "时间": pub_time,
                    "url": item["url"],
                })
            except Exception as e:
                logger.debug(f"发改委文章正文获取失败 ({item['url']}): {e}")
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": "",
                    "来源": "国家发改委",
                    "时间": "",
                    "url": item["url"],
                })

        return results

    except Exception as e:
        logger.warning(f"发改委新闻获取失败: {e}")
        return []


def get_all_trigger_news() -> dict:
    """
    汇总所有触发Agent需要的新闻数据
    v1.1 新增：财联社电报

    Returns:
        结构化字典供LLM分析
    """
    result = {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "今日宏观政策新闻": get_today_macro_news(),
        "财经政策资讯": get_policy_news(),
        "财联社电报": get_cls_telegraph(),
        "国家发改委": get_ndrc_news(max_articles=5),
    }
    return result
