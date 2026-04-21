"""时间工具：所有入库 / 查询 cutoff 用的"当前时间"统一走 APP_TIMEZONE。

由环境变量 `APP_TIMEZONE`（IANA 时区名，如 `Asia/Shanghai`、`America/New_York`）
决定实际时区，默认 `Asia/Shanghai`。SQLite DateTime 列不带 tzinfo，全仓库约定
存"朴素 datetime（naive）"，其字段值代表 APP_TIMEZONE 本地时间。
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))


def now_local() -> datetime:
    """返回 APP_TIMEZONE 时区的 naive datetime（DB DateTime 列默认值 / 查询 cutoff 用）。"""
    return datetime.now(APP_TZ).replace(tzinfo=None)


def today_local():
    """APP_TIMEZONE 时区的当日 date。"""
    return now_local().date()
