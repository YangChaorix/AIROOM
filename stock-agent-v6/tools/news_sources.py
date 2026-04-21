"""政务网站新闻爬虫（部委官网）。

每个 fetcher 返回 List[Dict]，字段与 news_items_repo.bulk_upsert 对齐：
    - title: 标题
    - content: 正文摘要（<500 字）
    - source: 来源标签（"国家发改委" 等）
    - published_at: 发布时间字符串（"YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"）

所有 fetcher 失败返回空列表（不 raise），交由 scheduler 层统一处理。
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
_REQ_TIMEOUT = 10


def _truncate(text: str, max_len: int = 500) -> str:
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().replace("\n", " ").replace("\r", "")
    return text[:max_len] if len(text) > max_len else text


def _get_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=_REQ_TIMEOUT)
        r.encoding = "utf-8"
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.debug(f"GET {url} 失败: {e}")
        return None


def get_ndrc_news(max_articles: int = 5) -> List[Dict[str, Any]]:
    """国家发改委新闻发布。"""
    base_url = "https://www.ndrc.gov.cn"
    list_url = f"{base_url}/xwdt/xwfb/"
    soup = _get_soup(list_url)
    if not soup:
        return []

    links: List[Dict[str, str]] = []
    for a in soup.select("ul.u-list li a, li > a"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) <= 5 or not href:
            continue
        if href.startswith("./"):
            href = f"{base_url}/xwdt/xwfb/{href[2:]}"
        elif href.startswith("/"):
            href = f"{base_url}{href}"
        links.append({"title": title, "url": href})

    results: List[Dict[str, Any]] = []
    for item in links[:max_articles]:
        asoup = _get_soup(item["url"])
        content = ""
        pub_time = ""
        if asoup:
            content_div = asoup.select_one(".TRS_Editor")
            content = content_div.get_text(separator=" ", strip=True) if content_div else ""
            time_tag = asoup.select_one(".time")
            pub_time = time_tag.get_text(strip=True) if time_tag else ""
        results.append({
            "title": _truncate(item["title"], 200),
            "content": _truncate(content),
            "source": "国家发改委",
            "published_at": pub_time,
        })
    return results


def get_miit_news(max_articles: int = 5) -> List[Dict[str, Any]]:
    """工信部官网最新动态（覆盖化工/电子/制造/通信）。"""
    base_url = "https://www.miit.gov.cn"
    soup = _get_soup(f"{base_url}/")
    if not soup:
        return []

    seen: set[str] = set()
    links: List[Dict[str, str]] = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) <= 8 or not href:
            continue
        if "/xwfb/" not in href and "/zwgk/" not in href:
            continue
        if href.startswith("http"):
            if "miit.gov.cn" not in href:
                continue
            full_url = href
        elif href.startswith("/"):
            full_url = f"{base_url}{href}"
        else:
            full_url = f"{base_url}/{href.lstrip('./')}"
        if not full_url.endswith((".html", ".htm")):
            full_url += ".html"
        if full_url in seen:
            continue
        seen.add(full_url)
        links.append({"title": title, "url": full_url})

    results: List[Dict[str, Any]] = []
    for item in links[:max_articles]:
        asoup = _get_soup(item["url"])
        content = ""
        pub_time = ""
        if asoup:
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
            "title": _truncate(item["title"], 200),
            "content": _truncate(content),
            "source": "工信部",
            "published_at": pub_time,
        })
    return results


def get_nea_news(max_articles: int = 5) -> List[Dict[str, Any]]:
    """国家能源局新闻（石油/天然气/电力/新能源）。"""
    base_url = "http://www.nea.gov.cn"
    soup = _get_soup(f"{base_url}/xwzx/index.htm")
    if not soup:
        return []

    seen: set[str] = set()
    links: List[Dict[str, str]] = []
    for li in soup.select("ul.list li, .news_area li, li"):
        a = li.find("a")
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
        elif href.startswith("../"):
            full_url = f"{base_url}/{href[3:]}"
        else:
            full_url = f"{base_url}/{href.lstrip('./')}"
        if full_url in seen:
            continue
        seen.add(full_url)
        date_tag = li.find("span", class_="date")
        list_date = date_tag.get_text(strip=True).strip("()") if date_tag else ""
        links.append({"title": title, "url": full_url, "list_date": list_date})

    results: List[Dict[str, Any]] = []
    for item in links[:max_articles]:
        asoup = _get_soup(item["url"])
        if not asoup:
            continue
        content_div = (
            asoup.select_one(".article-content")
            or asoup.select_one(".article-box")
            or asoup.select_one(".TRS_Editor")
            or asoup.select_one("#zoom")
        )
        content = content_div.get_text(separator=" ", strip=True) if content_div else ""
        pub_time = item.get("list_date", "")
        if not pub_time:
            time_tag = (
                asoup.select_one("div.mheader div.info")
                or asoup.select_one("span.times")
                or asoup.select_one(".pubdate")
                or asoup.select_one(".pub_time")
            )
            if time_tag:
                pub_time = time_tag.get_text(strip=True).split("来源")[0].strip()
            if not pub_time:
                meta = asoup.find("meta", attrs={"name": "publishdate"})
                pub_time = meta["content"].strip() if meta and meta.get("content") else ""
        if not pub_time:
            continue
        results.append({
            "title": _truncate(item["title"], 200),
            "content": _truncate(content),
            "source": "国家能源局",
            "published_at": pub_time,
        })
    return results


def get_mee_news(max_articles: int = 5) -> List[Dict[str, Any]]:
    """生态环境部新闻发布（环保/化工排放/双碳）。"""
    base_url = "https://www.mee.gov.cn"
    list_url = f"{base_url}/ywdt/xwfb/"
    soup = _get_soup(list_url)
    if not soup:
        return []

    seen: set[str] = set()
    links: List[Dict[str, str]] = []
    for li in soup.select("ul li"):
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
        if full_url in seen:
            continue
        seen.add(full_url)
        span = li.select_one("span")
        pub_time = span.get_text(strip=True) if span else ""
        links.append({"title": title, "url": full_url, "pub_time": pub_time})

    results: List[Dict[str, Any]] = []
    for item in links[:max_articles]:
        asoup = _get_soup(item["url"])
        content = ""
        pub_time = item["pub_time"]
        if asoup:
            content_div = (
                asoup.select_one(".TRS_Editor")
                or asoup.select_one(".article-content")
                or asoup.select_one("#zoom")
                or asoup.select_one(".content")
            )
            content = content_div.get_text(separator=" ", strip=True) if content_div else ""
            if not pub_time:
                time_tag = asoup.select_one(".time, .pubdate, .pub_time, .date")
                pub_time = time_tag.get_text(strip=True) if time_tag else ""
        results.append({
            "title": _truncate(item["title"], 200),
            "content": _truncate(content),
            "source": "生态环境部",
            "published_at": pub_time,
        })
    return results


def get_nhsa_news(max_articles: int = 5) -> List[Dict[str, Any]]:
    """国家医保局新闻（医保目录/集采/DRG-DIP）。"""
    base_url = "https://www.nhsa.gov.cn"
    soup = _get_soup(f"{base_url}/")
    if not soup:
        return []

    seen: set[str] = set()
    links: List[Dict[str, str]] = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or len(title) <= 8 or not href:
            continue
        if "/art/" not in href:
            continue
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = f"{base_url}{href}"
        else:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        links.append({"title": title, "url": full_url})

    results: List[Dict[str, Any]] = []
    for item in links[:max_articles]:
        m = re.search(r"/art/(\d{4})/(\d{1,2})/(\d{1,2})/", item["url"])
        pub_time = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
        asoup = _get_soup(item["url"])
        content = ""
        if asoup:
            content_div = asoup.select_one("#zoom") or asoup.select_one(".TRS_Editor")
            content = content_div.get_text(separator=" ", strip=True) if content_div else ""
        results.append({
            "title": _truncate(item["title"], 200),
            "content": _truncate(content),
            "source": "国家医保局",
            "published_at": pub_time,
        })
    return results


# ─── AkShare 封装（处理异常列名 / 时间重组，统一成 bulk_upsert 字段） ───

def get_shmet_metal_news(hours: int = 24) -> List[Dict[str, Any]]:
    """上海金属网（有色金属行业新闻，ak.futures_news_shmet）。"""
    import akshare as ak
    try:
        df = ak.futures_news_shmet()
    except Exception as e:
        logger.warning(f"上海金属网获取失败: {e}")
        return []

    if df is None or df.empty:
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    results: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        pub_dt = row.get("发布时间")
        if pub_dt is None:
            continue
        if hasattr(pub_dt, "tzinfo") and pub_dt.tzinfo:
            pub_dt = pub_dt.replace(tzinfo=None)
        try:
            if pub_dt < cutoff:
                continue
        except Exception:
            pass
        content = _truncate(str(row.get("内容", "")))
        m = re.match(r'[【\[](.+?)[】\]]', content)
        title = m.group(1) if m else content[:60]
        results.append({
            "title": _truncate(title, 200),
            "content": content,
            "source": "上海金属网",
            "published_at": pub_dt.strftime("%Y-%m-%d %H:%M") if hasattr(pub_dt, "strftime") else str(pub_dt),
        })
    return results


def get_cls_flash(limit: int = 100) -> List[Dict[str, Any]]:
    """财联社快讯（ak.stock_info_global_cls）。"""
    import akshare as ak
    try:
        df = ak.stock_info_global_cls()
    except Exception as e:
        logger.warning(f"财联社快讯获取失败: {e}")
        return []
    if df is None or df.empty:
        return []

    results: List[Dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        pub_date = str(row.get("发布日期", "")).strip()
        pub_time = str(row.get("发布时间", "")).strip()
        published_at = (f"{pub_date} {pub_time}").strip()
        title = _truncate(str(row.get("标题", "")), 200)
        if not title or title == "nan":
            continue
        results.append({
            "title": title,
            "content": _truncate(str(row.get("内容", ""))),
            "source": "财联社",
            "published_at": published_at,
        })
    return results


def get_ths_flash(limit: int = 100) -> List[Dict[str, Any]]:
    """同花顺快讯（ak.stock_info_global_ths）。"""
    import akshare as ak
    try:
        df = ak.stock_info_global_ths()
    except Exception as e:
        logger.warning(f"同花顺快讯获取失败: {e}")
        return []
    if df is None or df.empty:
        return []

    results: List[Dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        title = _truncate(str(row.get("标题", "")), 200)
        if not title or title == "nan":
            continue
        results.append({
            "title": title,
            "content": _truncate(str(row.get("内容", ""))),
            "source": "同花顺",
            "published_at": str(row.get("发布时间", "")),
        })
    return results


def get_sina_flash(limit: int = 50) -> List[Dict[str, Any]]:
    """新浪财经全球快讯（ak.stock_info_global_sina，只有内容字段）。"""
    import akshare as ak
    try:
        df = ak.stock_info_global_sina()
    except Exception as e:
        logger.warning(f"新浪财经获取失败: {e}")
        return []
    if df is None or df.empty:
        return []

    results: List[Dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        content = _truncate(str(row.get("内容", "")))
        if not content or content == "nan":
            continue
        title = content[:80]
        results.append({
            "title": _truncate(title, 200),
            "content": content,
            "source": "新浪财经",
            "published_at": str(row.get("时间", "")),
        })
    return results


def get_caixin_news(limit: int = 30) -> List[Dict[str, Any]]:
    """财新财经新闻（ak.stock_news_main_cx）。"""
    import akshare as ak
    try:
        df = ak.stock_news_main_cx()
    except Exception as e:
        logger.warning(f"财新获取失败: {e}")
        return []
    if df is None or df.empty:
        return []

    results: List[Dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        summary = _truncate(str(row.get("summary", "")))
        if not summary or summary == "nan":
            continue
        results.append({
            "title": _truncate(summary[:80], 200),
            "content": summary,
            "source": "财新",
            "published_at": str(row.get("pub_time", row.get("interval_time", ""))),
        })
    return results
