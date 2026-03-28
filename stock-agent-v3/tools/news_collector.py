"""
新闻采集与缓存管理器（v1.3：时段配置化）

采集策略（按时效性分级，时段和间隔均可通过 .env 配置）：
  HIGH   ：财联社快讯、东方财富快讯、同花顺快讯
  MEDIUM ：新浪财经快讯、财联社电报
  LOW    ：国家发改委官网、财新

默认时段规则：
  早盘前（6-9点）  → HIGH 30m、MEDIUM 60m、LOW 首次采集
  盘中 （9-15点）  → HIGH 30m、MEDIUM 60m、LOW 不采
  盘后 （15-18点） → MEDIUM 60m、LOW 再次采集、HIGH 不采
  夜间 （18-6点）  → 全部不采

.env 可配置项：
  COLLECT_INTERVAL_HIGH=30       采集间隔（分钟）
  COLLECT_INTERVAL_MEDIUM=60
  COLLECT_INTERVAL_LOW=120
  COLLECT_HIGH_HOURS=6-15        活跃时段（支持 "6-9,15-18" 多段）
  COLLECT_MEDIUM_HOURS=6-18
  COLLECT_LOW_HOURS=6-9,15-18
  COLLECT_SCHEDULE_HOURS=6-17    APScheduler 触发时段（hour 表达式）
  COLLECT_SCHEDULE_INTERVAL=30   APScheduler 触发间隔（分钟）
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Tuple

logger = logging.getLogger(__name__)


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# 默认间隔（分钟），运行时从 settings 读取
_DEFAULT_INTERVALS = {
    Priority.HIGH: 30,
    Priority.MEDIUM: 60,
    Priority.LOW: 120,
}

# 兼容旧代码直接引用此常量
PRIORITY_INTERVALS = _DEFAULT_INTERVALS


def _parse_hour_windows(spec: str) -> List[Tuple[int, int]]:
    """
    将时段字符串解析为 (start, end) 列表，end 不包含。
    例：'6-15'       → [(6, 15)]
        '6-9,15-18'  → [(6, 9), (15, 18)]
    """
    windows = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            windows.append((int(start), int(end)))
        elif part:
            h = int(part)
            windows.append((h, h + 1))
    return windows


def _is_hour_in_windows(hour: int, windows: List[Tuple[int, int]]) -> bool:
    """当前小时是否在任意时段窗口内（start 含，end 不含）"""
    return any(start <= hour < end for start, end in windows)


def _get_priority_interval(priority: Priority) -> int:
    """从 settings 读取该优先级的采集间隔（分钟）"""
    try:
        from config.settings import settings
        mapping = {
            Priority.HIGH: settings.agent.collect_interval_high,
            Priority.MEDIUM: settings.agent.collect_interval_medium,
            Priority.LOW: settings.agent.collect_interval_low,
        }
        return mapping[priority]
    except Exception:
        return _DEFAULT_INTERVALS[priority]


def _get_priority_windows(priority: Priority) -> List[Tuple[int, int]]:
    """从 settings 读取该优先级的活跃时段"""
    try:
        from config.settings import settings
        mapping = {
            Priority.HIGH: settings.agent.collect_high_hours,
            Priority.MEDIUM: settings.agent.collect_medium_hours,
            Priority.LOW: settings.agent.collect_low_hours,
        }
        return _parse_hour_windows(mapping[priority])
    except Exception:
        defaults = {
            Priority.HIGH: "6-15",
            Priority.MEDIUM: "6-18",
            Priority.LOW: "6-9,15-18",
        }
        return _parse_hour_windows(defaults[priority])


@dataclass
class NewsItem:
    id: str           # MD5 hash of title[:60]
    title: str
    content: str
    source: str
    pub_time: str     # from the source
    collected_at: str # when we collected it (ISO format)
    priority: str     # Priority enum value


def _make_news_id(title: str) -> str:
    """生成新闻唯一ID：MD5(title[:60].strip().lower())[:16]"""
    key = title[:60].strip().lower()
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class NewsCacheManager:
    """
    新闻缓存管理器（v1.2：读写 SQLite DB，接口与 v1.1 兼容）

    内部使用 news_items 表 + news_source_timestamps 表代替 JSON 文件。
    load_today() 返回与旧版相同的 dict 结构，使 collect_all_due_sources() 无需修改。
    """

    def __init__(self, cache_dir: str = None):
        # cache_dir 参数保留以兼容旧调用，不再用于存储
        self._cache_dir = cache_dir  # unused

    def load_today(self) -> dict:
        """从 DB 加载当日新闻缓存，返回与旧版相同的 dict 结构。"""
        from tools.db import db
        today = _today_str()
        try:
            news_rows = db.get_news(today)
            source_timestamps = db.get_source_last_collected(today)
            news_list = [
                {
                    "id": row["news_hash"],
                    "title": row["title"],
                    "content": row["content"],
                    "source": row["source"],
                    "pub_time": row["pub_time"],
                    "collected_at": row["collected_at"],
                    "priority": row["priority"],
                }
                for row in news_rows
            ]
            return {
                "date": today,
                "last_updated": "",
                "source_last_collected": source_timestamps,
                "news": news_list,
            }
        except Exception as e:
            logger.warning(f"从 DB 加载新闻缓存失败，返回空: {e}")
            return {
                "date": today,
                "last_updated": "",
                "source_last_collected": {},
                "news": [],
            }

    def save(self, cache: dict) -> None:
        """DB 写入是实时的，此方法保留为 no-op 以兼容旧调用。"""
        total = len(cache.get("news", []))
        logger.debug(f"新闻缓存（DB）当日共 {total} 条")

    def is_source_due(self, source_name: str, priority: Priority, cache: dict) -> bool:
        """
        判断来源是否到了采集时间，需同时满足两个条件：
        1. 当前时刻在该优先级的活跃时段内（时段由 settings 配置）
        2. 距上次采集已超过该优先级的间隔（间隔由 settings 配置）
        """
        # 条件1：时段检查
        current_hour = datetime.now().hour
        windows = _get_priority_windows(priority)
        if not _is_hour_in_windows(current_hour, windows):
            logger.debug(
                f"  [{source_name}] 当前 {current_hour}:xx 不在活跃时段 "
                f"{windows}，跳过"
            )
            return False

        # 条件2：间隔检查
        last_collected_str = cache.get("source_last_collected", {}).get(source_name)
        if not last_collected_str:
            return True
        try:
            last_dt = datetime.strptime(last_collected_str, "%Y-%m-%d %H:%M:%S")
            interval = _get_priority_interval(priority)
            return datetime.now() - last_dt >= timedelta(minutes=interval)
        except Exception:
            return True

    def add_news(self, items: list[dict], source: str, cache: dict) -> int:
        """
        将新闻写入 DB，同时更新内存 cache dict（保持旧接口）。
        返回新增条数。
        """
        from tools.db import db
        today = _today_str()
        existing_ids: set[str] = {item["id"] for item in cache.get("news", []) if "id" in item}
        added = 0
        now_str = _now_str()
        new_db_items = []

        # 读取最大天数限制
        try:
            from config.settings import settings
            max_age_days = settings.agent.news_max_age_days
        except Exception:
            max_age_days = 3
        now_dt = datetime.now()

        for item in items:
            if "错误" in item:
                continue
            title = item.get("标题", "").strip()
            if not title or title == "nan":
                continue

            news_id = _make_news_id(title)

            # 无发布时间不入库
            pub_time_str = item.get("时间", "").strip()
            if not pub_time_str:
                logger.debug(f"  [无发布时间跳过]「{title[:30]}」")
                continue

            # 新闻时效过滤：pub_time 超过 max_age_days 天的跳过
            if max_age_days > 0:
                pub_dt = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        pub_dt = datetime.strptime(pub_time_str[:len(fmt)], fmt)
                        break
                    except ValueError:
                        continue
                if pub_dt and (now_dt - pub_dt).days >= max_age_days:
                    logger.debug(f"  [过期跳过] {pub_time_str}「{title[:30]}」")
                    continue

            # 跨日去重：若同 hash 在历史日期出现过，更新 event_history 后跳过
            first_date = db.news_seen_before(news_id, today)
            if first_date:
                db.upsert_event(
                    event_hash=news_id,
                    summary=title[:100],
                    event_type="重复新闻",
                    first_seen=first_date,
                    last_seen=now_str,
                    source=source,
                )
                logger.debug(f"  [跨日重复] 跳过「{title[:30]}…」(首见:{first_date})")
                continue

            # 当日缓存去重
            if news_id in existing_ids:
                continue

            existing_ids.add(news_id)
            news_item = {
                "id": news_id,
                "title": title,
                "content": item.get("内容", ""),
                "source": source,
                "pub_time": item.get("时间", ""),
                "collected_at": now_str,
                "priority": _source_priority(source).value,
            }
            cache["news"].append(news_item)
            new_db_items.append(news_item)
            added += 1

        if new_db_items:
            try:
                db.add_news_items(new_db_items, today)
            except Exception as e:
                logger.warning(f"写入新闻到 DB 失败: {e}")

        return added

    def mark_source_collected(self, source: str, cache: dict) -> None:
        """更新 DB + 内存 cache 中的来源采集时间戳。"""
        from tools.db import db
        today = _today_str()
        try:
            db.mark_source_collected(today, source)
        except Exception as e:
            logger.warning(f"mark_source_collected DB 写入失败: {e}")
        cache.setdefault("source_last_collected", {})[source] = _now_str()

    def get_news_for_analysis(self, hours: int = 12,
                              sources: list = None,
                              lookback_hours: int = 0) -> dict:
        """
        从 DB 读取新闻，格式化为 LLM 分析输入。
        sources: None/[] = 所有渠道；否则只取指定渠道
        lookback_hours: 0 = 今天0点起；>0 = 过去N小时（可跨昨天）
        返回含采集统计 + 按来源分组的 dict。
        """
        from tools.db import db
        from datetime import timedelta
        if lookback_hours and lookback_hours > 0:
            since_dt = (datetime.now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            since_dt = None  # db.get_news_filtered 默认今天0点起
        raw_rows = db.get_news_filtered(sources=sources or None, since_dt=since_dt)
        news_items = [
            {
                "id": row["news_hash"],
                "title": row["title"],
                "content": row["content"],
                "source": row["source"],
                "pub_time": row["pub_time"],
                "collected_at": row["collected_at"],
                "priority": row["priority"],
            }
            for row in raw_rows
        ]

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # 统计各来源数量
        source_counts: dict[str, int] = {}
        for item in news_items:
            src = item.get("source", "未知")
            source_counts[src] = source_counts.get(src, 0) + 1

        # 计算时间跨度（按 collected_at）
        collected_times = []
        for item in news_items:
            ct = item.get("collected_at", "")
            if ct:
                try:
                    collected_times.append(datetime.strptime(ct, "%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass

        if collected_times:
            earliest = min(collected_times).strftime("%H:%M")
            latest = max(collected_times).strftime("%H:%M")
            time_range = f"{earliest} - {latest}"
        else:
            time_range = "无数据"

        # 最近1小时新增数
        recent_count = 0
        for item in news_items:
            ct = item.get("collected_at", "")
            if ct:
                try:
                    ct_dt = datetime.strptime(ct, "%Y-%m-%d %H:%M:%S")
                    if ct_dt >= one_hour_ago:
                        recent_count += 1
                except Exception:
                    pass

        result: dict = {
            "采集统计": {
                "总条数": len(news_items),
                "时间跨度": time_range,
                "各来源条数": source_counts,
                "最近1小时新增": recent_count,
            }
        }

        # 按来源分组
        source_groups: dict[str, list] = {}
        for item in news_items:
            src = item.get("source", "未知")
            if src not in source_groups:
                source_groups[src] = []

            is_recent = False
            ct = item.get("collected_at", "")
            if ct:
                try:
                    ct_dt = datetime.strptime(ct, "%Y-%m-%d %H:%M:%S")
                    is_recent = ct_dt >= one_hour_ago
                except Exception:
                    pass

            source_groups[src].append({
                "标题": item.get("title", ""),
                "内容": item.get("content", ""),
                "时间": item.get("pub_time", ""),
                "标签": "🔴 最新" if is_recent else "",
            })

        # 按预定义顺序输出来源
        source_order = ["财联社", "东方财富", "同花顺", "新浪财经", "财联社电报", "上海金属网", "国家发改委", "工信部", "国家能源局", "生态环境部", "国家医保局", "财新"]
        for src in source_order:
            if src in source_groups:
                result[src] = source_groups[src]
        # 输出未在预定义顺序中的来源
        for src, items in source_groups.items():
            if src not in result:
                result[src] = items

        return result


def _source_priority(source: str) -> Priority:
    """根据来源名称返回优先级"""
    HIGH_SOURCES = {"财联社", "东方财富", "同花顺"}
    MEDIUM_SOURCES = {"新浪财经", "财联社电报", "上海金属网"}
    LOW_SOURCES = {"国家发改委", "工信部", "国家能源局", "生态环境部", "国家医保局", "财新"}
    if source in HIGH_SOURCES:
        return Priority.HIGH
    if source in MEDIUM_SOURCES:
        return Priority.MEDIUM
    if source in LOW_SOURCES:
        return Priority.LOW
    return Priority.MEDIUM


def collect_all_due_sources(cache_manager: NewsCacheManager = None) -> dict:
    """
    Main collection function. Checks each source's priority and last collected time.
    Only fetches sources that are due for refresh.
    Returns: {source_name: items_added, ...}
    """
    from tools.news_tools import (
        get_today_macro_news,
        get_policy_news,
        get_cls_telegraph,
        get_ndrc_news,
        get_metal_industry_news,
        get_miit_news,
        get_nea_news,
        get_mee_news,
        get_nhsa_news,
    )

    if cache_manager is None:
        cache_manager = NewsCacheManager()

    cache = cache_manager.load_today()
    result: dict[str, int] = {}

    # HIGH 来源：财联社、东方财富、同花顺
    # 这三个来源由 get_today_macro_news() 一次性返回（按 来源 字段区分）
    HIGH_SOURCES = ["财联社", "东方财富", "同花顺"]
    high_due = [
        src for src in HIGH_SOURCES
        if cache_manager.is_source_due(src, Priority.HIGH, cache)
    ]
    if high_due:
        logger.info(f"HIGH 来源待采集: {high_due}，调用 get_today_macro_news()...")
        try:
            macro_items = get_today_macro_news()
            # 按 来源 字段拆分
            by_source: dict[str, list] = {}
            for item in macro_items:
                src = item.get("来源", "")
                if src:
                    by_source.setdefault(src, []).append(item)

            for src in HIGH_SOURCES:
                items_for_src = by_source.get(src, [])
                added = cache_manager.add_news(items_for_src, src, cache)
                cache_manager.mark_source_collected(src, cache)
                result[src] = added
                logger.info(f"  {src}: 新增 {added} 条（获取 {len(items_for_src)} 条）")
        except Exception as e:
            logger.warning(f"HIGH 来源采集失败: {e}")
            for src in HIGH_SOURCES:
                result[src] = 0
    else:
        logger.info("HIGH 来源（财联社/东方财富/同花顺）尚未到采集时间，跳过")

    # MEDIUM 来源 1：新浪财经、财新（由 get_policy_news() 返回）
    POLICY_SOURCES = ["新浪财经", "财新"]
    policy_due = [
        src for src in POLICY_SOURCES
        if cache_manager.is_source_due(src, Priority.MEDIUM, cache)
    ]
    if policy_due:
        logger.info(f"MEDIUM 来源待采集（政策）: {policy_due}，调用 get_policy_news()...")
        try:
            policy_items = get_policy_news()
            by_source: dict[str, list] = {}
            for item in policy_items:
                src = item.get("来源", "")
                if src:
                    by_source.setdefault(src, []).append(item)

            for src in POLICY_SOURCES:
                items_for_src = by_source.get(src, [])
                added = cache_manager.add_news(items_for_src, src, cache)
                cache_manager.mark_source_collected(src, cache)
                result[src] = added
                logger.info(f"  {src}: 新增 {added} 条（获取 {len(items_for_src)} 条）")
        except Exception as e:
            logger.warning(f"MEDIUM 政策来源采集失败: {e}")
            for src in POLICY_SOURCES:
                result[src] = 0
    else:
        logger.info("MEDIUM 来源（新浪财经/财新）尚未到采集时间，跳过")

    # MEDIUM 来源 2：财联社电报（独立接口）
    CLS_TEL = "财联社电报"
    if cache_manager.is_source_due(CLS_TEL, Priority.MEDIUM, cache):
        logger.info(f"MEDIUM 来源待采集: {CLS_TEL}，调用 get_cls_telegraph()...")
        try:
            tel_items = get_cls_telegraph()
            added = cache_manager.add_news(tel_items, CLS_TEL, cache)
            cache_manager.mark_source_collected(CLS_TEL, cache)
            result[CLS_TEL] = added
            logger.info(f"  {CLS_TEL}: 新增 {added} 条（获取 {len(tel_items)} 条）")
        except Exception as e:
            logger.warning(f"财联社电报采集失败: {e}")
            result[CLS_TEL] = 0
    else:
        logger.info("财联社电报尚未到采集时间，跳过")

    # MEDIUM 来源 3：上海金属网（有色金属行业新闻）
    SHMET = "上海金属网"
    if cache_manager.is_source_due(SHMET, Priority.MEDIUM, cache):
        logger.info(f"MEDIUM 来源待采集: {SHMET}，调用 get_metal_industry_news()...")
        try:
            metal_items = get_metal_industry_news()
            added = cache_manager.add_news(metal_items, SHMET, cache)
            cache_manager.mark_source_collected(SHMET, cache)
            result[SHMET] = added
            logger.info(f"  {SHMET}: 新增 {added} 条（获取 {len(metal_items)} 条）")
        except Exception as e:
            logger.warning(f"上海金属网采集失败: {e}")
            result[SHMET] = 0
    else:
        logger.info("上海金属网尚未到采集时间，跳过")

    # LOW 来源：国家发改委
    NDRC = "国家发改委"
    if cache_manager.is_source_due(NDRC, Priority.LOW, cache):
        logger.info(f"LOW 来源待采集: {NDRC}，调用 get_ndrc_news()...")
        try:
            ndrc_items = get_ndrc_news(max_articles=5)
            added = cache_manager.add_news(ndrc_items, NDRC, cache)
            cache_manager.mark_source_collected(NDRC, cache)
            result[NDRC] = added
            logger.info(f"  {NDRC}: 新增 {added} 条（获取 {len(ndrc_items)} 条）")
        except Exception as e:
            logger.warning(f"发改委采集失败: {e}")
            result[NDRC] = 0
    else:
        logger.info("国家发改委尚未到采集时间，跳过")

    # LOW 来源：工信部（化工/电子/制造业政策）
    MIIT = "工信部"
    if cache_manager.is_source_due(MIIT, Priority.LOW, cache):
        logger.info(f"LOW 来源待采集: {MIIT}，调用 get_miit_news()...")
        try:
            miit_items = get_miit_news(max_articles=5)
            added = cache_manager.add_news(miit_items, MIIT, cache)
            cache_manager.mark_source_collected(MIIT, cache)
            result[MIIT] = added
            logger.info(f"  {MIIT}: 新增 {added} 条（获取 {len(miit_items)} 条）")
        except Exception as e:
            logger.warning(f"工信部采集失败: {e}")
            result[MIIT] = 0
    else:
        logger.info("工信部尚未到采集时间，跳过")

    # LOW 来源：国家能源局（石油/天然气/电力/新能源政策）
    NEA = "国家能源局"
    if cache_manager.is_source_due(NEA, Priority.LOW, cache):
        logger.info(f"LOW 来源待采集: {NEA}，调用 get_nea_news()...")
        try:
            nea_items = get_nea_news(max_articles=5)
            added = cache_manager.add_news(nea_items, NEA, cache)
            cache_manager.mark_source_collected(NEA, cache)
            result[NEA] = added
            logger.info(f"  {NEA}: 新增 {added} 条（获取 {len(nea_items)} 条）")
        except Exception as e:
            logger.warning(f"国家能源局采集失败: {e}")
            result[NEA] = 0
    else:
        logger.info("国家能源局尚未到采集时间，跳过")

    # LOW 来源：生态环境部（环保/化工排放/碳排放政策）
    MEE = "生态环境部"
    if cache_manager.is_source_due(MEE, Priority.LOW, cache):
        logger.info(f"LOW 来源待采集: {MEE}，调用 get_mee_news()...")
        try:
            mee_items = get_mee_news(max_articles=5)
            added = cache_manager.add_news(mee_items, MEE, cache)
            cache_manager.mark_source_collected(MEE, cache)
            result[MEE] = added
            logger.info(f"  {MEE}: 新增 {added} 条（获取 {len(mee_items)} 条）")
        except Exception as e:
            logger.warning(f"生态环境部采集失败: {e}")
            result[MEE] = 0
    else:
        logger.info("生态环境部尚未到采集时间，跳过")

    # LOW 来源：国家医保局（医保目录、集采、DRG/DIP改革）
    NHSA = "国家医保局"
    if cache_manager.is_source_due(NHSA, Priority.LOW, cache):
        logger.info(f"LOW 来源待采集: {NHSA}，调用 get_nhsa_news()...")
        try:
            nhsa_items = get_nhsa_news(max_articles=5)
            added = cache_manager.add_news(nhsa_items, NHSA, cache)
            cache_manager.mark_source_collected(NHSA, cache)
            result[NHSA] = added
            logger.info(f"  {NHSA}: 新增 {added} 条（获取 {len(nhsa_items)} 条）")
        except Exception as e:
            logger.warning(f"国家医保局采集失败: {e}")
            result[NHSA] = 0
    else:
        logger.info("国家医保局尚未到采集时间，跳过")

    # 保存缓存
    cache_manager.save(cache)
    logger.info(f"采集完成，当日缓存总计 {len(cache.get('news', []))} 条，本次各来源: {result}")
    return result
