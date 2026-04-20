# Stock Agent v6 — 数据库 Schema 参考

> Phase 3 数据持久化层文档。
> SQLite + SQLAlchemy + Alembic。
> 14 张物理表 + 2 SQL 视图。

---

## 一、总览

### 存储位置

- 默认：`data/stock_agent.db`（项目根目录下的 SQLite 文件）
- 测试：`sqlite:///:memory:` 或临时文件（由 `conftest.py` fixture 自动管理）
- 可通过环境变量 `STOCK_AGENT_DB_URL` 覆盖

### 启动

```bash
alembic upgrade head                   # 建表 + 两个 SQL 视图
python scripts/seed_from_json.py       # 把 config/user_profile.json 导入 users + conditions
python main.py                         # 业务跑起来，数据自动入库
```

### 时间字段全表约定

- **所有表**都有 `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` —— 入库时间
- **可变实体**（users / conditions / runs / snapshots）额外有 `updated_at`，SQLAlchemy `onupdate=datetime.utcnow` 自动维护
- **不可变实体**（agent_outputs / condition_scores / skeptic_findings / news_items / tool_calls）只有 `created_at`

### 去重策略

- `news_items.content_hash = SHA256(title + source)` **不含时间** —— 同标题同源跨天重推只存一条
- `triggers.trigger_id` UNIQUE
- `snapshots` 表以 `(code, as_of)` 唯一 —— 跨运行复用，避免重复 AkShare 调用
- `condition_scores (stock_recommendation_id, condition_id)` UNIQUE
- `agent_outputs (run_id, agent_name, sequence)` UNIQUE

### 扩展性

- 每张核心表有 `metadata_json TEXT` 列（JSON 字符串），加新字段不改 schema
- `agent_outputs` 通用表：加新 agent（Critic / Chat）**零 migration**，只需 INSERT

---

## 二、14 张物理表

### 1. `users` — 用户档案

| 字段 | 类型 | 约束 | 中文含义 | 示例值 |
|---|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 | 1 |
| user_id | TEXT | UNIQUE NOT NULL | 业务标识 | `dad_001` |
| name | TEXT | NOT NULL | 用户可读名 | `老爸的策略` |
| recommendation_threshold | REAL | NOT NULL DEFAULT 0.65 | 推荐分数门槛 | 0.65 |
| trading_style | TEXT |  | 交易风格 | `short` / `medium` / `long` |
| metadata_json | TEXT |  | JSON 扩展字段 | `{"risk_tolerance": "medium"}` |
| created_at | DATETIME | NOT NULL | | |
| updated_at | DATETIME | NOT NULL | | |

### 2. `conditions` — 选股条件（Screener 运行时读）

| 字段 | 类型 | 约束 | 含义 | 示例 |
|---|---|---|---|---|
| id | INTEGER | PK | | |
| user_id | TEXT | FK users.user_id | | `dad_001` |
| condition_id | TEXT | NOT NULL | 业务 ID | `C2` |
| name | TEXT | NOT NULL | 条件名 | `行业龙头` |
| layer | TEXT | NOT NULL | `trigger` / `screener` / `entry` | `screener` |
| description | TEXT | NOT NULL | Prompt 注入的文本 | |
| weight | REAL |  | 评估/入场层必填；触发层 NULL | 0.28 |
| keywords_json | TEXT |  | 触发层关键词 JSON | `["补贴","落地"]` |
| active | BOOLEAN | DEFAULT 1 | 软删标记 | 1 |
| metadata_json | TEXT |  | | |
| created_at | DATETIME | NOT NULL | | |
| updated_at | DATETIME | NOT NULL | | |

**唯一索引**: `(user_id, condition_id)`

### 3. `news_items` — 原始新闻（去重 + Trigger Agent 消费）

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| content_hash | TEXT | UNIQUE NOT NULL | SHA256(title+source)，**不含时间** |
| title | TEXT | NOT NULL | 标题 |
| content | TEXT |  | 摘要，≤500 字 |
| source | TEXT | NOT NULL | 7 个渠道之一（见 README Phase 6） |
| published_at | DATETIME | NOT NULL | 新闻原始发布时间 |
| created_at | DATETIME | NOT NULL | 首次入库时间（命中 hash 不更新） |
| metadata_json | TEXT |  | |
| **consumed_by_trigger_id** | INTEGER | FK triggers.id | **Phase 6**：被哪个 trigger 引用消费，NULL 表示未消费 |
| **consumed_at** | DATETIME |  | **Phase 6**：消费时间 |

**索引**: `(source, published_at DESC)` / `(consumed_by_trigger_id)` / `(consumed_by_trigger_id, created_at)`

**查询模式**：
- 未消费候选池：`WHERE consumed_by_trigger_id IS NULL AND created_at >= datetime('now', '-6 hours')`
- 某 trigger 引用了哪些 news：`WHERE consumed_by_trigger_id = X`

### 4. `triggers` — 触发信号（Phase 6 升级为事件队列）

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| trigger_id | TEXT | UNIQUE NOT NULL | `T-20260419-LIVE` / `T-STOCK-300750-...` / `T-AGENT-...` |
| run_id | INTEGER | FK runs.id | **遗留字段**：产生该 trigger 的 run（旧模型，Phase 6 之前） |
| headline | TEXT | NOT NULL | 标题 |
| industry | TEXT | NOT NULL | 受影响行业 |
| type | TEXT | NOT NULL | `policy_landing` / `industry_news` / `individual_stock_analysis` / `earnings_beat` / `minor_news` / `price_surge` |
| strength | TEXT | NOT NULL | `high` / `medium` / `low` |
| source | TEXT | NOT NULL | 新闻来源 |
| published_at | DATETIME |  | |
| summary | TEXT | NOT NULL | 对 A 股投资者的含义说明 |
| mode | TEXT | NOT NULL | `live` / `fixture` / `individual_stock` / **`agent_generated`**（Trigger Agent 生成） |
| source_news_ids | TEXT |  | JSON 数组：引用的 news_items.id |
| metadata_json | TEXT |  | Phase 4：`focus_codes` / `focus_primary` / `peer_names` |
| created_at | DATETIME | NOT NULL | |
| **status** | TEXT | NOT NULL DEFAULT 'pending' | **Phase 6**：`pending` / `processing` / `completed` / `failed` |
| **consumed_by_run_id** | INTEGER | FK runs.id | **Phase 6**：消费该 trigger 的 run |
| **priority** | INTEGER | NOT NULL DEFAULT 5 | **Phase 6**：1-10，Trigger Agent 打分；消费时 DESC 优先 |
| **processed_at** | DATETIME |  | **Phase 6**：完成/失败时间 |

### 5. `runs` — 每次运行元信息

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | 运行 ID |
| user_id | TEXT | FK users.user_id | |
| trigger_key | TEXT |  | `live` / `default` / `stock:300750` |
| status | TEXT | NOT NULL | `running` / `completed` / `failed` |
| started_at | DATETIME | NOT NULL | |
| finished_at | DATETIME |  | |
| error | TEXT |  | 失败堆栈 |
| langsmith_project | TEXT |  | 回溯 trace 用 |
| metadata_json | TEXT |  | |
| created_at, updated_at | DATETIME | NOT NULL | |

### 6. ★ `agent_outputs` — 所有 Agent 的顶层输出（通用表）

**档位 A 核心**：4 种现有 agent（+ 未来任意新 agent）的顶层输出都写这一张表；各自专属结构放 `payload_json`；**加新 agent 零 migration**。

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| run_id | INTEGER | FK runs.id NOT NULL | |
| agent_name | TEXT | NOT NULL | `supervisor` / `research` / `screener` / `skeptic` / 未来任意 |
| sequence | INTEGER | NOT NULL | Supervisor 1-4；其他通常 1 |
| status | TEXT | NOT NULL | `success` / `failed` |
| summary | TEXT |  | 通用摘要 |
| payload_json | TEXT |  | 各 agent 专属结构（见下） |
| metrics_json | TEXT |  | `{"latency_ms": ..., "tokens": ...}` |
| metadata_json | TEXT |  | |
| created_at | DATETIME | NOT NULL | |

**唯一索引**: `(run_id, agent_name, sequence)`
**索引**: `(agent_name, created_at DESC)`

**各 agent 的 summary / payload_json 形态约定**：

| agent_name | summary 内容 | payload_json 结构 |
|---|---|---|
| `supervisor` | 本轮 reasoning（≥20 字） | `{"action": "...", "instructions": "...", "notes": "finalize 综合判断"}` |
| `research` | overall_notes | `{"tool_call_count": 5, "tool_names": [...], "candidates_count": 3, "data_gaps_count": 2}` |
| `screener` | **comparison_summary**（横向对比 100-300 字） | `{"threshold_used": 0.65, "candidates_count": 3}` |
| `skeptic` | 覆盖统计 | `{"covered_stocks": [...], "logic_risk_count": N, "data_gap_count": N}` |

### 7. `stock_data_entries` — Research 给出的每只候选股

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK agent_outputs.id NOT NULL | 指向 agent_name='research' 那行 |
| code | TEXT | NOT NULL | 6 位股票代码 |
| name | TEXT | NOT NULL | |
| industry | TEXT | NOT NULL | |
| leadership, holder_structure, financial_summary, technical_summary, price_benefit | TEXT | | 5 个研究维度的文本（可空） |
| data_gaps_json | TEXT |  | 未拿到的数据项清单（JSON 数组） |
| sources_json | TEXT |  | 调用过的工具名清单 |
| created_at | DATETIME | NOT NULL | |

**唯一索引**: `(agent_output_id, code)`
**索引**: `(code, created_at DESC)` — 跨运行按股票查研究历史

### 8. `tool_calls` — Research ReAct 工具调用审计

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK agent_outputs.id NOT NULL | |
| sequence | INTEGER | NOT NULL | ReAct 第几次调用（1-based） |
| tool_name | TEXT | NOT NULL | |
| args_json | TEXT | NOT NULL | |
| stock_code | TEXT |  | 链路辅助列：args 里有 code 就冗余存一份 |
| result_preview | TEXT |  | 返回 JSON 前 500 字 |
| latency_ms | INTEGER |  | |
| error | TEXT |  | |
| created_at | DATETIME | NOT NULL | |

### 9. ★ `stock_recommendations` — 每只股评分 + 业务摘要

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK agent_outputs.id NOT NULL | 指向 agent_name='screener' 那行 |
| stock_data_entry_id | INTEGER | FK stock_data_entries.id | 关联 Research 研究记录 |
| code | TEXT | NOT NULL | |
| name | TEXT | NOT NULL | |
| total_score | REAL | NOT NULL | 加权总分 0-1 |
| recommendation_level | TEXT | NOT NULL | `recommend` / `watch` / `skip` |
| rank | INTEGER |  | 批内排名 |
| **recommendation_rationale** | TEXT |  | 这只股为什么最终推荐/观察/跳过（50-150 字） |
| **key_strengths_json** | TEXT |  | 核心优势（JSON 数组） |
| **key_risks_json** | TEXT |  | 核心风险（JSON 数组） |
| data_gaps_json | TEXT |  | Screener 识别的数据缺口 |
| trigger_ref | TEXT | NOT NULL | 关联触发 ID |
| created_at | DATETIME | NOT NULL | |

**索引**: `(agent_output_id, rank)` / `(code, created_at DESC)`（跨 run 查股票历史）

### 10. `condition_scores` — 每条件打分

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| stock_recommendation_id | INTEGER | FK stock_recommendations.id NOT NULL | |
| condition_id | TEXT | NOT NULL | `C2` / `C3` / ... |
| condition_name | TEXT | NOT NULL | |
| satisfaction | REAL | NOT NULL | 0 / 0.5 / 1 |
| weight | REAL | NOT NULL | |
| weighted_score | REAL | NOT NULL | |
| reasoning | TEXT | NOT NULL | 打分依据（≥15 字） |
| created_at | DATETIME | NOT NULL | |

**唯一索引**: `(stock_recommendation_id, condition_id)`

### 11. `skeptic_findings` — 每条 Skeptic 质疑

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK agent_outputs.id NOT NULL | 指向 agent_name='skeptic' |
| **stock_recommendation_id** | INTEGER | FK stock_recommendations.id | **★ 强 FK**：直接关联推荐股 |
| stock_code | TEXT | NOT NULL | 冗余 |
| finding_type | TEXT | NOT NULL | `logic_risk` / `data_gap` |
| content | TEXT | NOT NULL | 质疑内容（≥20 字） |
| created_at | DATETIME | NOT NULL | |

### 12-14. `financial_snapshots` / `holder_snapshots` / `technical_snapshots` — AkShare 缓存

**共同字段**：id / code / as_of / raw_json / source / created_at / updated_at
**唯一键**: `(code, as_of)` —— 同股同日期只存一条，跨运行复用

专属列见 `db/models.py`。

### 15. `system_logs` — 全局日志（Phase 5 新增）

调度器 / Agent / 工具层都可写入；DB 内统一查询。

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| level | TEXT | NOT NULL | `info` / `warning` / `error` |
| source | TEXT | NOT NULL | 调用点标识，如 `scheduler.news_cctv` / `agents.research` |
| message | TEXT | NOT NULL | 人可读短消息 |
| context_json | TEXT |  | 异常堆栈 / 参数 / 返回预览（JSON） |
| run_id | INTEGER | FK runs.id | 可选：关联 run |
| created_at | DATETIME | NOT NULL | |

**索引**: `(level, created_at DESC)` / `(source, created_at DESC)`

**典型查询**：

```sql
-- 最近 1 小时的 error 级日志
SELECT source, message, created_at FROM system_logs
WHERE level='error' AND created_at >= datetime('now', '-1 hour')
ORDER BY created_at DESC;

-- 某渠道的抓取历史
SELECT created_at, level, message FROM system_logs
WHERE source='scheduler.news_cctv'
ORDER BY created_at DESC LIMIT 20;
```

---

## 三、2 SQL 视图

### `v_recommendation_trace` — 推荐股完整链路追溯

一条 SQL 返回某只推荐股的 **8 维证据**（推荐摘要 / 横向对比 / 触发 / Research / 条件打分 / Skeptic 质疑 / 工具调用 / Supervisor 综合判断）。

查询示例见 `docs/PHASE3_DB_PLAN.md` §3.9。

### `v_stock_analysis_history` — 跨模式股票分析历史

合并"事件驱动候选股"与"个股主动分析"两种模式，一条查询看某股的完整被分析轨迹。

`role` 字段自动标注：`primary`（主股） / `peer`（对标股） / `candidate`（事件驱动候选）。

查询示例见 `docs/PHASE3_DB_PLAN.md` §4·2。

---

## 四、metadata_json 标准键约定

### `triggers.metadata_json`

| Key | 类型 | 含义 | 来源 |
|---|---|---|---|
| `focus_codes` | `List[str]` | 本次分析聚焦的股票代码列表 | Phase 4 个股分析 |
| `focus_primary` | `str` | 主股代码（用户主动指定） | Phase 4 |
| `peer_names` | `List[str]` | 对标股名称列表 | Phase 4 |

### `runs.metadata_json`

暂无标准键。预留扩展。

### `agent_outputs.metadata_json`

暂无标准键。预留扩展（如 `{"model": "deepseek-reasoner"}`）。

---

## 五、常用 SQL 查询

### 最近一条推荐股的完整链路

```sql
SELECT * FROM v_recommendation_trace ORDER BY rec_created_at DESC LIMIT 1;
```

### 某只股跨 run 历史

```sql
SELECT rec_created_at, analysis_type, role, total_score, recommendation_level, trigger_headline
FROM v_stock_analysis_history
WHERE code='300750'
ORDER BY rec_created_at DESC;
```

### 某只股被用户主动分析的轨迹（Phase 4）

```sql
SELECT rec_created_at, total_score, recommendation_level, recommendation_rationale
FROM v_stock_analysis_history
WHERE code='300750' AND role='primary'
ORDER BY rec_created_at DESC;
```

### 最近 30 天所有 recommend 级的股

```sql
SELECT DISTINCT code, name, MAX(created_at) AS last_recommended
FROM stock_recommendations
WHERE recommendation_level='recommend' AND created_at >= date('now','-30 days')
GROUP BY code ORDER BY last_recommended DESC;
```

### Research Agent 对某股调过哪些工具（审计）

```sql
SELECT sequence, tool_name, latency_ms, error
FROM tool_calls
WHERE stock_code='300750'
ORDER BY created_at DESC LIMIT 20;
```

### 快照缓存命中率（某天有多少股票已有缓存）

```sql
SELECT COUNT(DISTINCT code) FROM financial_snapshots WHERE as_of = date('now');
```

---

## 六、变更日志

- 2026-04-19 Phase 3 初始 schema（14 表 + 2 视图）
- 2026-04-19 Phase 4 约定 `triggers.metadata_json` 标准键（focus_codes / focus_primary / peer_names）
- 2026-04-19 Phase 5 新增 `system_logs` 表（info/warning/error 三级）
- 2026-04-19 Phase 6 **事件队列升级**：
  - `triggers` 加 status / consumed_by_run_id / priority / processed_at
  - `news_items` 加 consumed_by_trigger_id / consumed_at（一对一消费去重）
  - 新增 mode 值 `agent_generated`（Trigger Agent 生成）
  - triggers.run_id 退化为遗留字段
