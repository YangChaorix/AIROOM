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


def _truncate(text: str, max_len: int = 2000) -> str:
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().replace("\n", " ").replace("\r", "")
    return text[:max_len] if len(text) > max_len else text


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
                        "内容": _truncate(str(row.get("内容", ""))),
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
                        "内容": _truncate(str(row.get("摘要", ""))),
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
                        "内容": _truncate(str(row.get("内容", ""))),
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
                    "内容": _truncate(content),
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
                content = _truncate(str(row.get("内容", "")))
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
                summary = _truncate(str(row.get("summary", "")))
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
                    "内容": _truncate(content),
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


def get_metal_industry_news() -> list[dict]:
    """
    上海金属网有色金属行业新闻（akshare futures_news_shmet）
    覆盖：铜、铝、镍、锂、锌、铅等有色金属实时资讯
    """
    import re
    try:
        df = ak.futures_news_shmet()
        cutoff = datetime.now() - timedelta(hours=24)
        result = []
        for _, row in df.iterrows():
            pub_dt = row["发布时间"]
            if hasattr(pub_dt, 'tzinfo') and pub_dt.tzinfo:
                pub_dt = pub_dt.replace(tzinfo=None)
            if pub_dt < cutoff:
                continue
            content = _truncate(str(row["内容"]), 2000)
            m = re.match(r'[【\[](.+?)[】\]]', content)
            title = m.group(1) if m else content[:60]
            result.append({
                "标题": _truncate(title, 200),
                "内容": content,
                "来源": "上海金属网",
                "时间": pub_dt.strftime("%Y-%m-%d %H:%M"),
            })
        logger.info(f"上海金属网: 获取 {len(result)} 条（24小时内）")
        return result
    except Exception as e:
        logger.warning(f"上海金属网新闻获取失败: {e}")
        return []


def get_miit_news(max_articles: int = 5) -> list[dict]:
    """
    爬取工信部官网最新动态
    来源：https://www.miit.gov.cn/（主页新闻链接）
    覆盖：化工、电子、制造业、通信等工业和信息化政策动态
    """
    base_url = "https://www.miit.gov.cn"
    list_url = base_url + "/"  # 主页包含最新新闻链接
    results = []

    try:
        r = requests.get(list_url, headers=_HTTP_HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            logger.warning(f"工信部页面请求失败: status={r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        seen_hrefs: set[str] = set()
        for a in soup.select("a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) <= 8 or not href:
                continue
            # 只取工信部自己的新闻文章链接（含 /xwfb/ 的路径）
            if "/xwfb/" not in href and "/zwgk/" not in href:
                continue
            if href.startswith("http"):
                full_url = href
                if "miit.gov.cn" not in full_url:
                    continue
            elif href.startswith("/"):
                full_url = f"{base_url}{href}"
            else:
                full_url = f"{base_url}/{href.lstrip('./')}"
            # 补全不完整的URL（截断的href）
            if not full_url.endswith(".html") and not full_url.endswith(".htm"):
                full_url += ".html"
            if full_url in seen_hrefs:
                continue
            seen_hrefs.add(full_url)
            links.append({"title": title, "url": full_url})

        logger.info(f"工信部新闻列表获取成功：共 {len(links)} 条，抓取前 {max_articles} 篇正文")

        for item in links[:max_articles]:
            try:
                ar = requests.get(item["url"], headers=_HTTP_HEADERS, timeout=10)
                ar.encoding = "utf-8"
                asoup = BeautifulSoup(ar.text, "html.parser")
                # 工信部文章结构：正文在 .ccontent，时间在 .cinfo
                content_div = (
                    asoup.select_one(".ccontent")
                    or asoup.select_one(".TRS_Editor")
                    or asoup.select_one(".article-content")
                    or asoup.select_one("#zoom")
                )
                content = content_div.get_text(separator=" ", strip=True) if content_div else ""
                time_tag = asoup.select_one(".cinfo, .time, .pubdate, .pub_time")
                pub_time = time_tag.get_text(strip=True) if time_tag else ""
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": _truncate(content),
                    "来源": "工信部",
                    "时间": pub_time,
                    "url": item["url"],
                })
            except Exception as e:
                logger.debug(f"工信部文章正文获取失败 ({item['url']}): {e}")
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": "",
                    "来源": "工信部",
                    "时间": "",
                    "url": item["url"],
                })

        return results

    except Exception as e:
        logger.warning(f"工信部新闻获取失败: {e}")
        return []


def get_nea_news(max_articles: int = 5) -> list[dict]:
    """
    爬取国家能源局官网新闻
    来源：http://www.nea.gov.cn/xwzx/index.htm
    覆盖：石油、天然气、煤炭、电力、新能源等能源政策动态
    """
    base_url = "http://www.nea.gov.cn"
    list_url = f"{base_url}/xwzx/index.htm"
    results = []

    try:
        r = requests.get(list_url, headers=_HTTP_HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            logger.warning(f"国家能源局页面请求失败: status={r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        seen_hrefs: set[str] = set()
        for a in soup.select("ul.list li a, .news_area li a, li a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) <= 5 or not href:
                continue
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"{base_url}{href}"
            elif href.startswith("../"):
                # 如 ../20260319/xxx/c.html → http://www.nea.gov.cn/20260319/xxx/c.html
                full_url = f"{base_url}/{href[3:]}"
            else:
                full_url = f"{base_url}/{href.lstrip('./')}"
            if full_url in seen_hrefs:
                continue
            seen_hrefs.add(full_url)
            links.append({"title": title, "url": full_url})

        logger.info(f"国家能源局新闻列表获取成功：共 {len(links)} 条，抓取前 {max_articles} 篇正文")

        for item in links[:max_articles]:
            try:
                ar = requests.get(item["url"], headers=_HTTP_HEADERS, timeout=10)
                ar.encoding = "utf-8"
                asoup = BeautifulSoup(ar.text, "html.parser")
                # 国家能源局文章结构：正文在 .article-content，时间在 span.times
                content_div = (
                    asoup.select_one(".article-content")
                    or asoup.select_one(".article-box")
                    or asoup.select_one(".TRS_Editor")
                    or asoup.select_one("#zoom")
                )
                content = content_div.get_text(separator=" ", strip=True) if content_div else ""
                time_tag = asoup.select_one("span.times, .time, .pubdate, .pub_time")
                pub_time = time_tag.get_text(strip=True) if time_tag else ""
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": _truncate(content),
                    "来源": "国家能源局",
                    "时间": pub_time,
                    "url": item["url"],
                })
            except Exception as e:
                logger.debug(f"国家能源局文章正文获取失败 ({item['url']}): {e}")
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": "",
                    "来源": "国家能源局",
                    "时间": "",
                    "url": item["url"],
                })

        return results

    except Exception as e:
        logger.warning(f"国家能源局新闻获取失败: {e}")
        return []


def get_mee_news(max_articles: int = 5) -> list[dict]:
    """
    爬取生态环境部官网新闻发布
    来源：https://www.mee.gov.cn/ywdt/xwfb/
    覆盖：环保政策、化工排放、碳排放、双碳目标等政策动态
    """
    base_url = "https://www.mee.gov.cn"
    list_url = f"{base_url}/ywdt/xwfb/"
    results = []

    try:
        r = requests.get(list_url, headers=_HTTP_HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            logger.warning(f"生态环境部页面请求失败: status={r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        seen_hrefs: set[str] = set()
        for li in soup.select("ul li"):
            # 取第一个 a 标签作为标题链接
            a = li.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) <= 5 or not href:
                continue
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"{base_url}{href}"
            elif href.startswith("./"):
                full_url = f"{base_url}/ywdt/xwfb/{href[2:]}"
            else:
                full_url = f"{base_url}/ywdt/xwfb/{href}"
            if full_url in seen_hrefs:
                continue
            seen_hrefs.add(full_url)
            # 提取日期
            span = li.select_one("span")
            pub_time = span.get_text(strip=True) if span else ""
            links.append({"title": title, "url": full_url, "pub_time": pub_time})

        logger.info(f"生态环境部新闻列表获取成功：共 {len(links)} 条，抓取前 {max_articles} 篇正文")

        for item in links[:max_articles]:
            try:
                ar = requests.get(item["url"], headers=_HTTP_HEADERS, timeout=10)
                ar.encoding = "utf-8"
                asoup = BeautifulSoup(ar.text, "html.parser")
                content_div = (
                    asoup.select_one(".TRS_Editor")
                    or asoup.select_one(".article-content")
                    or asoup.select_one("#zoom")
                    or asoup.select_one(".content")
                )
                content = content_div.get_text(separator=" ", strip=True) if content_div else ""
                pub_time = item["pub_time"]
                if not pub_time:
                    time_tag = asoup.select_one(".time, .pubdate, .pub_time, .date")
                    pub_time = time_tag.get_text(strip=True) if time_tag else ""
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": _truncate(content),
                    "来源": "生态环境部",
                    "时间": pub_time,
                    "url": item["url"],
                })
            except Exception as e:
                logger.debug(f"生态环境部文章正文获取失败 ({item['url']}): {e}")
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": "",
                    "来源": "生态环境部",
                    "时间": item["pub_time"],
                    "url": item["url"],
                })

        return results

    except Exception as e:
        logger.warning(f"生态环境部新闻获取失败: {e}")
        return []


def get_nhsa_news(max_articles: int = 5) -> list[dict]:
    """
    爬取国家医保局官网新闻动态
    来源：https://www.nhsa.gov.cn/（主页含大量静态文章链接）
    覆盖：医保目录调整、集中带量采购（集采）、DRG/DIP支付改革、医保统计数据
    """
    base_url = "https://www.nhsa.gov.cn"
    list_url = base_url + "/"  # 主页包含静态文章链接（col列表页为JS渲染，无法直接抓取）
    results = []

    try:
        r = requests.get(list_url, headers=_HTTP_HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            logger.warning(f"国家医保局页面请求失败: status={r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        seen_hrefs: set[str] = set()
        for a in soup.select("a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) <= 8 or not href:
                continue
            # 只取医保局自己的文章链接（含 /art/ 的路径）
            if "/art/" not in href:
                continue
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"{base_url}{href}"
            else:
                continue
            if full_url in seen_hrefs:
                continue
            seen_hrefs.add(full_url)
            links.append({"title": title, "url": full_url, "pub_time": ""})

        logger.info(f"国家医保局新闻列表获取成功：共 {len(links)} 条，抓取前 {max_articles} 篇正文")

        import re as _re
        for item in links[:max_articles]:
            # 从 URL 中提取日期（如 /art/2026/3/26/art_xxx.html → 2026-03-26）
            m = _re.search(r"/art/(\d{4})/(\d{1,2})/(\d{1,2})/", item["url"])
            pub_time = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
            try:
                ar = requests.get(item["url"], headers=_HTTP_HEADERS, timeout=10)
                ar.encoding = "utf-8"
                asoup = BeautifulSoup(ar.text, "html.parser")
                # 国家医保局文章结构：正文在 #zoom
                content_div = asoup.select_one("#zoom") or asoup.select_one(".TRS_Editor")
                content = content_div.get_text(separator=" ", strip=True) if content_div else ""
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": _truncate(content),
                    "来源": "国家医保局",
                    "时间": pub_time,
                    "url": item["url"],
                })
            except Exception as e:
                logger.debug(f"国家医保局文章正文获取失败 ({item['url']}): {e}")
                results.append({
                    "标题": _truncate(item["title"], 200),
                    "内容": "",
                    "来源": "国家医保局",
                    "时间": pub_time,
                    "url": item["url"],
                })

        return results

    except Exception as e:
        logger.warning(f"国家医保局新闻获取失败: {e}")
        return []


def get_all_trigger_news() -> dict:
    """
    汇总所有触发Agent需要的新闻数据
    v1.1 新增：财联社电报
    v1.2 新增：上海金属网、工信部、国家能源局、生态环境部
    v1.3 新增：国家医保局

    Returns:
        结构化字典供LLM分析
    """
    result = {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "今日宏观政策新闻": get_today_macro_news(),
        "财经政策资讯": get_policy_news(),
        "财联社电报": get_cls_telegraph(),
        "国家发改委": get_ndrc_news(max_articles=5),
        "工信部": get_miit_news(max_articles=5),
        "国家能源局": get_nea_news(max_articles=5),
        "生态环境部": get_mee_news(max_articles=5),
        "国家医保局": get_nhsa_news(max_articles=5),
        "上海金属网": get_metal_industry_news(),
    }
    return result
