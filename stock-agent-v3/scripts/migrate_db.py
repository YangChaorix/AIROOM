#!/usr/bin/env python3
"""
数据库迁移脚本 — 累积版本
============================================
适用场景：线上 Docker 旧版本 → 新版本升级前手动迁移数据库
安全性  ：全部操作幂等，可重复执行，不会破坏已有数据

变更内容（按版本累积）：

[v1 — Critic Agent]
  1. prompts 表 — 新增 source 列（human / critic / system）
  2. 新建 critic_reports 表
  3. 新建 critic_stock_performance 表
  4. 新增系统配置项（批评Agent调度时间）
  5. 裁剪 system_prompt：将旧版完整 Prompt 中的固定输出格式尾部移除
  6. 种子化 output_format：为每个 Agent 写入固定格式条目（source=system）

[v2 — UI 功能增强]
  7. review_reports 表 — 新增 4 列（触发检测优化建议）
  8. 新增系统配置项（Prompt 自动激活开关、新闻保留天数）

[v3 — Prompt 版本追踪]
  9. triggers / screener_stocks 表 — 新增 prompt_id 列（记录每批次使用的提示词版本）

用法：
  python3 scripts/migrate_db.py [--db PATH] [--dry-run] [--verbose]
"""

import argparse
import sqlite3
import sys
import os
from datetime import datetime

# ── 固定输出格式常量（与代码保持一致） ────────────────────────────────────────

_TRIGGER_OUTPUT_FORMAT = """**最终请以JSON格式输出**，结构如下：
{
  "date": "YYYY-MM-DD",
  "has_triggers": true/false,
  "triggers": [
    {
      "summary": "信息摘要",
      "type": "政策|涨价|转折事件",
      "industries": ["行业1", "行业2"],
      "companies": {
        "上游": ["企业A", "企业B"],
        "核心": ["企业C", "企业D"],
        "下游": ["企业E"]
      },
      "strength": "强|中|弱",
      "reason": "判断理由",
      "caution": "注意事项",
      "freshness": "高|低",
      "freshness_reason": "判断理由"
    }
  ],
  "summary": "今日触发情况简述"
}"""

_SCREENER_OUTPUT_FORMAT = """**请以JSON格式输出**，结构如下：
{
  "date": "YYYY-MM-DD",
  "top20": [
    {
      "rank": 1,
      "name": "企业名称",
      "code": "股票代码",
      "trigger_reason": "触发原因",
      "scores": {
        "D1_龙头地位": {"score": 3, "reason": "简短理由"},
        "D2_受益程度": {"score": 3, "reason": "简短理由"},
        "D3_股东结构": {"score": 2, "reason": "简短理由"},
        "D4_上涨趋势": {"score": 2, "reason": "简短理由"},
        "D5_技术突破": {"score": 3, "reason": "简短理由"},
        "D6_估值合理": {"score": 1, "reason": "简短理由"}
      },
      "total_score": 14,
      "recommendation": "综合推荐理由（3-5句话）",
      "risk": "主要风险点"
    }
  ],
  "analysis_summary": "本次精筛总体说明"
}"""

_REVIEW_OUTPUT_FORMAT = """**输出格式（Markdown，请严格按此结构输出）**
# 每日复盘 - {date}

## 1. 今日市场概况
（大盘指数、成交量、板块轮动方向）

## 2. 热点板块分析
（Top 3板块 + 驱动因素 + 持续性判断）

## 3. 当日推送验证
（每只股票：名称-实际涨跌-成交量变化-验证结论）

## 4. 今日发现
（市场上有强烈反应但未被系统捕捉的机会，简要分析原因）

## 5. 明日关注
（基于今日复盘，明日重点观察的信号）

## 6. 本周经验积累（仅周五）
（本周复盘总结）

**判断原则**
政策要有实质性措施才可能有持续性；
只有领导人讲话没有具体措施，通常是一两天行情；
行业整治类政策（限制供给）往往比补贴类政策（扩大需求）更有持续性；
上下游轮动有规律：核心行业先涨，原材料上游随后，耗材下游最后。"""

_CRITIC_OUTPUT_FORMAT = """━━━ 第二部分：改进后的精筛Prompt ━━━
在下方分隔符后，输出改进版精筛System Prompt的**可编辑部分**。

**重要约束（必须遵守）：**
1. 保持D1-D6六个维度的结构不变（只改各维度的评分标准文字）
2. 只输出精筛Prompt的可编辑分析准则部分，JSON格式模板由系统自动附加（不要在建议中包含JSON格式）
3. 保持0-3分制不变
4. 改进内容仅限于：维度的评分标准描述、注意事项、典型案例说明
5. 不得新增或删除维度，不得修改维度名称（D1_龙头地位等）

---SUGGESTED_PROMPT_BELOW---
（此处只输出精筛Prompt的可编辑分析准则部分，不包含JSON格式模板，系统会自动追加）"""

# 各 Agent system_prompt 裁剪标记（遇到此标记时截断，保留之前的内容）
_SPLIT_MARKERS = {
    "trigger":  "**最终请以JSON格式输出**",
    "screener": "**请以JSON格式输出**",
    "review":   "**输出格式（Markdown",
    "critic":   "━━━ 第二部分",
}

_OUTPUT_FORMATS = {
    "trigger":  _TRIGGER_OUTPUT_FORMAT,
    "screener": _SCREENER_OUTPUT_FORMAT,
    "review":   _REVIEW_OUTPUT_FORMAT,
    "critic":   _CRITIC_OUTPUT_FORMAT,
}

# ── 新增系统配置项（幂等，已存在则跳过） ──────────────────────────────────────
_NEW_CONFIGS = [
    # v1 — Critic Agent 调度
    ("schedule_critic_hour",          "15",        "number", "批评Agent执行小时",          "收盘验证时间（北京时间）"),
    ("schedule_critic_minute",        "40",        "number", "批评Agent执行分钟",          ""),
    ("schedule_critic_days",          "1,2,3,4,5", "text",   "批评Agent执行日",            ""),
    # v2 — 保留策略 & Prompt 自动激活开关
    ("log_retention_days",            "3",         "number", "日志保留天数",               "自动清理超出天数的日志文件，0=不清理"),
    ("news_retention_days",           "90",        "number", "新闻保留天数",               "自动清理超出天数的新闻记录（默认90天），0=不清理"),
    ("critic_screener_auto_activate", "false",     "text",   "批评Agent自动激活精筛Prompt", "true=自动激活，false=待人工审核"),
    ("review_trigger_auto_activate",  "false",     "text",   "复盘Agent自动激活触发Prompt", "true=自动激活，false=待人工审核"),
]


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def step(label, dry_run=False):
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"\n{'='*60}")
    print(f"  {tag}{label}")
    print(f"{'='*60}")


def ok(msg):   print(f"  ✓ {msg}")
def skip(msg): print(f"  - {msg} (已存在，跳过)")
def warn(msg): print(f"  ⚠ {msg}")
def info(msg): print(f"  → {msg}")


# ── 主迁移逻辑 ────────────────────────────────────────────────────────────────

def migrate(db_path: str, dry_run: bool = False, verbose: bool = False):
    if not os.path.exists(db_path):
        print(f"[ERROR] 数据库文件不存在: {db_path}")
        sys.exit(1)

    print(f"\n数据库路径: {db_path}")
    print(f"模式: {'DRY-RUN（只读，不写入）' if dry_run else '实际执行'}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        # ── 步骤 1：prompts 表加 source 列 ────────────────────────────────────
        step("步骤 1/8 — prompts 表新增 source 列", dry_run)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prompts)").fetchall()]
        if "source" not in cols:
            info("添加 source 列，默认值 'human'")
            if not dry_run:
                conn.execute("ALTER TABLE prompts ADD COLUMN source TEXT NOT NULL DEFAULT 'human'")
                conn.commit()
            ok("source 列已添加")
        else:
            skip("source 列")

        # ── 步骤 2：建 critic_reports 表 ─────────────────────────────────────
        step("步骤 2/8 — 创建 critic_reports 表", dry_run)
        if "critic_reports" not in tables:
            info("创建 critic_reports 表")
            if not dry_run:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS critic_reports (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_date            TEXT NOT NULL,
                        run_id              TEXT NOT NULL DEFAULT '',
                        screener_run_id     TEXT NOT NULL DEFAULT '',
                        critique_markdown   TEXT,
                        avg_pick_return     REAL,
                        market_avg_return   REAL,
                        beat_count          INTEGER,
                        miss_count          INTEGER,
                        suggested_prompt    TEXT,
                        suggested_prompt_id INTEGER,
                        previous_prompt_id  INTEGER,
                        created_at          TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_critic_date ON critic_reports(run_date);
                """)
                conn.commit()
            ok("critic_reports 表已创建")
        else:
            skip("critic_reports 表")

        # ── 步骤 3：建 critic_stock_performance 表 ────────────────────────────
        step("步骤 3/8 — 创建 critic_stock_performance 表", dry_run)
        if "critic_stock_performance" not in tables:
            info("创建 critic_stock_performance 表")
            if not dry_run:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS critic_stock_performance (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_date        TEXT NOT NULL,
                        critic_run_id   TEXT NOT NULL,
                        stock_code      TEXT NOT NULL,
                        stock_name      TEXT,
                        rank            INTEGER,
                        total_score     INTEGER,
                        d1_score INTEGER, d2_score INTEGER, d3_score INTEGER,
                        d4_score INTEGER, d5_score INTEGER, d6_score INTEGER,
                        open_price      REAL,
                        close_price     REAL,
                        pct_return      REAL,
                        market_avg      REAL,
                        beat_market     INTEGER,
                        created_at      TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_csp_date ON critic_stock_performance(run_date);
                    CREATE INDEX IF NOT EXISTS idx_csp_run  ON critic_stock_performance(run_date, critic_run_id);
                    CREATE INDEX IF NOT EXISTS idx_csp_code ON critic_stock_performance(stock_code);
                """)
                conn.commit()
            ok("critic_stock_performance 表已创建")
        else:
            skip("critic_stock_performance 表")

        # ── 步骤 4：review_reports 表新增触发检测优化列 ───────────────────────
        step("步骤 4/8 — review_reports 表新增触发检测优化列", dry_run)
        rv_cols = [r[1] for r in conn.execute("PRAGMA table_info(review_reports)").fetchall()]
        added_rv = []
        for col, typedef in [
            ("suggested_trigger_prompt",    "TEXT"),
            ("suggested_trigger_prompt_id", "INTEGER"),
            ("previous_trigger_prompt_id",  "INTEGER"),
            ("trigger_review_markdown",     "TEXT"),
        ]:
            if col not in rv_cols:
                info(f"添加列 {col} {typedef}")
                if not dry_run:
                    conn.execute(f"ALTER TABLE review_reports ADD COLUMN {col} {typedef}")
                added_rv.append(col)
            else:
                if verbose:
                    skip(f"review_reports.{col}")
        if added_rv:
            if not dry_run:
                conn.commit()
            ok(f"已添加列：{', '.join(added_rv)}")
        else:
            skip("review_reports 触发检测优化列（均已存在）")

        # ── 步骤 5：triggers / screener_stocks 加 prompt_id 列 ───────────────
        step("步骤 5/9 — triggers / screener_stocks 新增 prompt_id 列", dry_run)
        for tbl in ("triggers", "screener_stocks"):
            tcols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
            if "prompt_id" not in tcols:
                info(f"添加列 {tbl}.prompt_id INTEGER")
                if not dry_run:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN prompt_id INTEGER")
                    conn.commit()
                ok(f"{tbl}.prompt_id 已添加")
            else:
                if verbose:
                    skip(f"{tbl}.prompt_id")
        else:
            if all("prompt_id" in [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()] for t in ("triggers", "screener_stocks")):
                if verbose:
                    skip("triggers/screener_stocks prompt_id（均已存在）")

        # ── 步骤 6：新增系统配置项 ────────────────────────────────────────────
        step("步骤 6/9 — 新增系统配置项", dry_run)
        added_cfg = []
        for key, value, typ, label, note in _NEW_CONFIGS:
            existing = conn.execute(
                "SELECT 1 FROM system_config WHERE key=?", (key,)
            ).fetchone()
            if not existing:
                info(f"插入配置 {key} = {value!r}")
                if not dry_run:
                    conn.execute(
                        """INSERT INTO system_config (key, value, type, label, note, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (key, value, typ, label, note, now),
                    )
                added_cfg.append(key)
            else:
                if verbose:
                    skip(f"配置 {key}")
        if added_cfg:
            if not dry_run:
                conn.commit()
            ok(f"已添加配置：{', '.join(added_cfg)}")
        else:
            skip("所有配置项（均已存在）")

        # ── 步骤 6：裁剪旧 system_prompt（去除固定输出格式尾部） ──────────────
        step("步骤 7/9 — 裁剪 system_prompt（移除固定格式尾部）", dry_run)
        total_trimmed = 0
        for agent, marker in _SPLIT_MARKERS.items():
            rows = conn.execute(
                "SELECT id, version, length(content) as len, content FROM prompts "
                "WHERE agent_name=? AND prompt_name='system_prompt'",
                (agent,),
            ).fetchall()
            for row in rows:
                content = row["content"] or ""
                if marker in content:
                    editable = content[:content.index(marker)].rstrip()
                    info(f"[{agent}] 版本 {row['version']}：{row['len']} → {len(editable)} 字符（裁剪 {row['len']-len(editable)} 字符）")
                    if not dry_run:
                        conn.execute(
                            "UPDATE prompts SET content=? WHERE id=?",
                            (editable, row["id"]),
                        )
                    total_trimmed += 1
                else:
                    if verbose:
                        info(f"[{agent}] 版本 {row['version']}：无需裁剪")
        if not dry_run:
            conn.commit()
        ok(f"共裁剪 {total_trimmed} 条 system_prompt 记录")

        # ── 步骤 7：种子化 output_format ──────────────────────────────────────
        step("步骤 8/9 — 种子化固定输出格式（output_format）", dry_run)
        for agent, fmt_content in _OUTPUT_FORMATS.items():
            existing = conn.execute(
                "SELECT 1 FROM prompts WHERE agent_name=? AND prompt_name='output_format' LIMIT 1",
                (agent,),
            ).fetchone()
            if not existing:
                info(f"[{agent}] 写入 output_format（{len(fmt_content)} 字符）")
                if not dry_run:
                    conn.execute(
                        """INSERT INTO prompts
                           (agent_name, prompt_name, content, version, is_active, created_at, note, source)
                           VALUES (?, 'output_format', ?, 'v1', 1, ?, '系统固定输出格式（请勿修改）', 'system')""",
                        (agent, fmt_content, now),
                    )
                ok(f"[{agent}] output_format 已写入")
            else:
                skip(f"[{agent}] output_format")
        if not dry_run:
            conn.commit()

        # ── 步骤 8：种子化 critic 默认 system_prompt（若 DB 中不存在） ─────────
        step("步骤 9/9 — 种子化 critic system_prompt 默认值", dry_run)
        critic_seed = conn.execute(
            "SELECT 1 FROM prompts WHERE agent_name='critic' AND prompt_name='system_prompt' LIMIT 1"
        ).fetchone()
        if not critic_seed:
            _CRITIC_EDITABLE_SEED = """你是一个A股选股系统的批评分析师。你会收到今日精筛Agent推荐的股票列表，以及这些股票当日实际的开盘→收盘涨跌幅数据。

**你的任务分两部分，必须按格式输出：**

━━━ 第一部分：批评报告（Markdown） ━━━

# 选股批评报告 - {date}

## 1. 今日概况
- 推荐 {total} 只，跑赢大盘（市场均值 {market_avg:.2f}%）{beat_count} 只，胜率 {win_rate:.0f}%
- 推荐平均收益：{avg_return:.2f}%，大盘均值：{market_avg:.2f}%，超额：{excess:.2f}%

## 2. 表现排行
### Top 5 最佳推荐
（从表现最好的5只中分析：推荐理由与实际结果是否吻合，哪个维度判断最准确）

### Bottom 5 最差推荐
（从表现最差的5只中分析：哪个维度判断失误，根因是什么）

## 3. 维度准确性分析
| 维度 | 高分股（≥2分）跑赢大盘比例 | 低分股（0-1分）跑赢大盘比例 | 预测价值 |
|------|--------------------------|--------------------------|---------|
| D1 行业龙头地位 | X% | X% | 高/中/低 |
| D2 主营产品受益 | X% | X% | 高/中/低 |
| D3 股东结构    | X% | X% | 高/中/低 |
| D4 上涨趋势    | X% | X% | 高/中/低 |
| D5 技术突破    | X% | X% | 高/中/低 |
| D6 估值合理    | X% | X% | 高/中/低 |

## 4. 系统性偏差
（描述本次推荐中存在的固定错误模式，如：过度偏向某类行业、特定维度系统性高估等）

## 5. 具体改进建议
（至少3条，格式：**问题**：...  **建议**：...）"""
            info("写入 critic system_prompt 默认种子")
            if not dry_run:
                conn.execute(
                    """INSERT INTO prompts
                       (agent_name, prompt_name, content, version, is_active, created_at, note, source)
                       VALUES ('critic', 'system_prompt', ?, 'v1', 1, ?, '默认种子', 'human')""",
                    (_CRITIC_EDITABLE_SEED, now),
                )
                conn.commit()
            ok("critic system_prompt 默认值已写入")
        else:
            skip("critic system_prompt（已存在）")

        # ── 验证输出 ──────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("  验证结果")
        print(f"{'='*60}")

        # prompts 表
        rows = conn.execute(
            "SELECT agent_name, prompt_name, source, version, length(content) as len "
            "FROM prompts ORDER BY agent_name, prompt_name, id DESC"
        ).fetchall()
        print(f"\n  {'agent':<14} {'prompt_name':<16} {'source':<8} {'ver':<6} {'len'}")
        print(f"  {'-'*58}")
        for r in rows:
            marker = " ✓" if r["prompt_name"] == "output_format" else ""
            print(f"  {r['agent_name']:<14} {r['prompt_name']:<16} {r['source']:<8} {r['version']:<6} {r['len']}{marker}")

        # critic 相关表行数
        c_count   = conn.execute("SELECT COUNT(*) FROM critic_reports").fetchone()[0]
        csp_count = conn.execute("SELECT COUNT(*) FROM critic_stock_performance").fetchone()[0]
        print(f"\n  critic_reports 行数             : {c_count}")
        print(f"  critic_stock_performance 行数   : {csp_count}")

        # review_reports 列检查
        rv_cols_now = [r[1] for r in conn.execute("PRAGMA table_info(review_reports)").fetchall()]
        new_rv_cols = ["suggested_trigger_prompt", "suggested_trigger_prompt_id",
                       "previous_trigger_prompt_id", "trigger_review_markdown"]
        print(f"\n  review_reports 触发优化列:")
        for col in new_rv_cols:
            status = "✓ 存在" if col in rv_cols_now else "✗ 缺失"
            print(f"    {col:<40} {status}")

        # 关键配置项
        cfg_keys = [
            "schedule_critic_hour", "schedule_critic_minute", "schedule_critic_days",
            "log_retention_days", "news_retention_days",
            "critic_screener_auto_activate", "review_trigger_auto_activate",
        ]
        cfg_rows = conn.execute(
            f"SELECT key, value FROM system_config WHERE key IN ({','.join('?'*len(cfg_keys))})",
            cfg_keys,
        ).fetchall()
        cfg_map = {r["key"]: r["value"] for r in cfg_rows}
        print(f"\n  系统配置项:")
        for k in cfg_keys:
            v = cfg_map.get(k, "❌ 未找到")
            print(f"    {k:<40} = {v}")

        print(f"\n{'='*60}")
        if dry_run:
            print("  [DRY-RUN 完成] 以上为预览，数据库未修改")
        else:
            print("  迁移完成！")
        print(f"{'='*60}\n")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="stock-agent-v3 数据库迁移脚本（累积版）")
    parser.add_argument(
        "--db",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "db", "stock_agent.db"),
        help="数据库文件路径（默认 data/db/stock_agent.db）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只读预览，不实际写入")
    parser.add_argument("--verbose", action="store_true", help="显示详细日志（包含已跳过项）")
    args = parser.parse_args()

    migrate(os.path.abspath(args.db), dry_run=args.dry_run, verbose=args.verbose)
