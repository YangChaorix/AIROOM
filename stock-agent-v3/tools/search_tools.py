"""
Web 搜索工具（v1.1 新增）
使用 Serper API 搜索政策新闻，作为 akshare 新闻采集的补充
"""

import logging
from typing import Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)

# 默认政策新闻搜索查询列表
DEFAULT_POLICY_QUERIES = [
    "今日产业政策 发改委 工信部",
    "今日行业政策 补贴 限制",
    "今日大宗商品 涨价",
    "国家能源局 商务部 最新政策",
]


def search_policy_news(query: str, num: int = 10) -> list[dict]:
    """
    使用 Serper API 搜索政策新闻

    Args:
        query: 搜索关键词
        num: 返回结果数量（最多10）

    Returns:
        新闻列表，每条包含 {title, snippet, link, date}
        如果未配置 API key，返回空列表
    """
    if not settings.serper.api_key:
        logger.debug("SERPER_API_KEY 未配置，跳过 Web 搜索")
        return []

    if not settings.serper.enabled:
        logger.debug("Serper 搜索已禁用（SERPER_ENABLED=false）")
        return []

    try:
        headers = {
            "X-API-KEY": settings.serper.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "num": min(num, 10),
            "gl": "cn",
            "hl": "zh-cn",
        }

        resp = requests.post(
            settings.serper.base_url,
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
                "date": item.get("date", ""),
            })

        # 也包含新闻结果（如果有 news block）
        for item in data.get("news", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
                "date": item.get("date", ""),
            })

        logger.debug(f"Serper 搜索 '{query}' 返回 {len(results)} 条结果")
        return results

    except requests.exceptions.Timeout:
        logger.warning(f"Serper 搜索超时（query='{query}'）")
        return []
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Serper API 请求失败: {e} (status={e.response.status_code if e.response else 'N/A'})")
        return []
    except Exception as e:
        logger.warning(f"Serper 搜索异常: {e}")
        return []


def search_multiple_queries(
    queries: Optional[list[str]] = None,
) -> list[dict]:
    """
    批量搜索多个政策查询，去重后返回合并结果

    Args:
        queries: 搜索词列表，默认使用 DEFAULT_POLICY_QUERIES

    Returns:
        去重后的新闻列表（按 title+link 去重）
    """
    if queries is None:
        queries = DEFAULT_POLICY_QUERIES

    if not settings.serper.api_key or not settings.serper.enabled:
        logger.info("Serper 未启用，跳过政策新闻 Web 搜索")
        return []

    all_results: list[dict] = []
    seen_links: set[str] = set()

    for query in queries:
        logger.info(f"Serper 搜索: {query}")
        items = search_policy_news(query, num=10)
        for item in items:
            link = item.get("link", "")
            title = item.get("title", "")
            dedup_key = link or title
            if dedup_key and dedup_key not in seen_links:
                seen_links.add(dedup_key)
                item["query"] = query  # 记录来源查询
                all_results.append(item)

    logger.info(f"Serper 多查询搜索完成，共 {len(all_results)} 条去重结果（{len(queries)} 个查询）")
    return all_results


