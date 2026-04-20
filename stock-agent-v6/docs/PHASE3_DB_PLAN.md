# Stock Agent v6 — Phase 3：SQLite 数据库持久化执行计划

> 版本：2026-04-18
> 状态：**待实施（本文档供审阅，尚未写任何代码）**
> 前置：Phase 1 MVP + Phase 2 真实数据接入均已完成，22/22 测试通过

---

## 一、背景与目标

### 1.1 当前状态

- MVP 4 个 Agent 全部真 LLM 驱动（DeepSeek reasoner + chat）
- 6 个 Research 工具真接入 AkShare，Trigger 可从 AkShare 新闻 LLM 摘要
- 每次运行产出 `outputs/runs/run_YYYYMMDD_HHMMSS.md` —— **基于文件的临时输出，无法查询、无法跨运行对比**

### 1.2 本期目标

- 引入 **SQLite + SQLAlchemy ORM**，把所有业务数据持久化
- 四个 Agent 节点**渐进式落盘**（不是运行结束才写）
- 取消 Markdown 文件输出；需要人读报告时用 CLI 按需从 DB 渲染
- 保证每只推荐股都能反查到**业务层 7 维证据链**（不重复 LangSmith 的 LLM 原始 I/O 审计）

### 1.3 用户确认的关键决策

| # | 问题 | 决定 |
|---|---|---|
| 1 | DB 技术 | **SQLite + SQLAlchemy ORM**（Alembic 管理迁移） |
| 2 | 写入时机 | **四个节点各自落盘（渐进式）** |
| 3 | Markdown 文件 | **取消**，DB 为唯一事实源 |
| 4 | LLM 原始 I/O | **不存 DB**，由 LangSmith 承担审计 |
| 5 | 新闻去重 | `content_hash = SHA256(title + source)`（**不含时间**，跨天重推只存一条） |
| 6 | 时间字段 | 所有表必有 `created_at`；可变实体追加 `updated_at` |
| 7 | **Agent 输出表设计** | **档位 A：统一 `agent_outputs` 通用表**（4 种 agent 合并 1 张顶层表），加新 agent **零 migration** |

---

## 二、设计原则

1. **扩展性**：每张核心表带 `metadata_json` TEXT 列（JSON 容器），新增字段不需改 schema
2. **多用户友好**：所有"用户相关"表带 `user_id`（当前默认 `dad_001`）
3. **运行可追溯**：所有数据行带 `run_id` 外键，便于按运行检索全流程
4. **跨运行复用**：`news_items` / `financial_snapshots` / `holder_snapshots` / `technical_snapshots` 独立存储；同一 `(code, as_of)` 只存一份，减少 AkShare 重复调用
5. **时间字段约定**
   - 全部表：`created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
   - 可变实体（users / conditions / runs / snapshots）：追加 `updated_at DATETIME onupdate=now`
   - 不可变实体（agent_outputs / condition_scores / skeptic_findings / news_items / tool_calls）：**只有 `created_at`**
6. **Agent 输出通用化**（档位 A）：
   - 所有 agent（supervisor / research / screener / skeptic / 未来任意新 agent）的**顶层输出**都写入**同一张** `agent_outputs` 表
   - 各 agent 的专属结构化字段放 `payload_json`（JSON 容器），通用文字摘要放 `summary`
   - 明细表（`stock_data_entries` / `condition_scores` / `skeptic_findings` / `tool_calls`）保留，FK 统一指向 `agent_outputs.id`
   - **加新 agent（如 Critic / Chat）只 INSERT，不改 schema**
7. **链路追溯**：每只推荐股可反查到 8 个维度证据（见下文 §4），主视图 `v_recommendation_trace` JOIN 次数减至最少
8. **查询性能**：热路径字段（如 agent_name / stock_code / run_id）建索引；JSON 字段通过 SQLite 的 `json_extract()` 函数按需解析

---

## 三、数据表设计（共 14 张物理表 + 2 SQL 视图）

### 3.1 用户与策略

#### 表 1：`users`

| 字段 | 类型 | 约束 | 中文含义 | 示例值 |
|---|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 | 1 |
| user_id | TEXT | UNIQUE NOT NULL | 业务标识 | `dad_001` |
| name | TEXT | NOT NULL | 用户可读名 | `老爸的策略` |
| recommendation_threshold | REAL | NOT NULL DEFAULT 0.65 | 推荐分数门槛 | 0.65 |
| trading_style | TEXT |  | 交易风格 | short / medium / long |
| metadata_json | TEXT |  | JSON 扩展字段 | `{"risk_tolerance": "medium"}` |
| created_at | DATETIME | NOT NULL | 创建时间 | 2026-04-18 10:00:00 |
| updated_at | DATETIME | NOT NULL | 更新时间 | 2026-04-18 10:00:00 |

#### 表 2：`conditions`（选股条件，Screener 运行时读）

| 字段 | 类型 | 约束 | 中文含义 | 示例值 |
|---|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 | 1 |
| user_id | TEXT | FK `users.user_id` | 所属用户 | `dad_001` |
| condition_id | TEXT | NOT NULL | 业务 ID | `C2` |
| name | TEXT | NOT NULL | 条件名 | `行业龙头` |
| layer | TEXT | NOT NULL | 层级（trigger / screener / entry） | `screener` |
| description | TEXT | NOT NULL | 注入 Prompt 的文本 | `前10大股东以私募...` |
| weight | REAL |  | 评估/入场层权重；触发层 NULL | 0.28 |
| keywords_json | TEXT |  | 触发层关键词 JSON 数组 | `["补贴","落地"]` |
| active | BOOLEAN | DEFAULT 1 | 软删标记（删条件改 0） | 1 |
| metadata_json | TEXT |  | | |
| created_at | DATETIME | NOT NULL | | |
| updated_at | DATETIME | NOT NULL | | |
| **唯一索引** | `(user_id, condition_id)` | | | |

### 3.2 触发信号与新闻

#### 表 3：`news_items`（原始新闻，去重 + 跨运行复用）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 |
| content_hash | TEXT | UNIQUE NOT NULL | **去重键** = `SHA256(title + source)`，**不含时间** |
| title | TEXT | NOT NULL | 新闻标题 |
| content | TEXT |  | 摘要正文（截断 ≤500 字） |
| source | TEXT | NOT NULL | 数据源（央视网 / 东财-财经早餐 / 东财-全球资讯） |
| published_at | DATETIME | NOT NULL | 新闻原始发布时间 |
| created_at | DATETIME | NOT NULL | **首次入库时间**（命中 content_hash 不更新此字段） |
| metadata_json | TEXT |  | 扩展字段（原 URL、标签等） |
| **索引** | `(source, published_at DESC)` | | 时间范围查询用 |

> **去重语义**：同一标题同一源，跨日重推只存一条。多个 trigger 可引用同一 news_item。

#### 表 4：`triggers`

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | 主键 |
| trigger_id | TEXT | UNIQUE NOT NULL | 业务 ID，如 `T-20260418-LIVE` |
| run_id | INTEGER | FK `runs.id` | 产生该 trigger 的运行 |
| headline | TEXT | NOT NULL | 标题 |
| industry | TEXT | NOT NULL | 受影响行业 |
| type | TEXT | NOT NULL | `policy_landing` / `industry_news` / `earnings_beat` / `minor_news` / `price_surge` |
| strength | TEXT | NOT NULL | `high` / `medium` / `low` |
| source | TEXT | NOT NULL | 新闻来源 |
| published_at | DATETIME |  | 新闻原始时间 |
| summary | TEXT | NOT NULL | 对 A 股投资者的含义说明 |
| mode | TEXT | NOT NULL | `live` / `fixture` |
| source_news_ids | TEXT |  | JSON 数组：摘要所用 news_items.id |
| metadata_json | TEXT |  | |
| created_at | DATETIME | NOT NULL | |

### 3.3 运行元信息

#### 表 5：`runs`

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | 运行 ID |
| user_id | TEXT | FK `users.user_id` | |
| trigger_key | TEXT |  | `live` / `default` / `strong_policy` |
| status | TEXT | NOT NULL | `running` / `completed` / `failed` |
| started_at | DATETIME | NOT NULL | |
| finished_at | DATETIME |  | |
| error | TEXT |  | 失败时的堆栈 |
| langsmith_project | TEXT |  | 回溯 trace 用 |
| metadata_json | TEXT |  | |
| created_at | DATETIME | NOT NULL | |
| updated_at | DATETIME | NOT NULL | |

### 3.4 ★ Agent 输出通用表（档位 A 核心）

#### 表 6：`agent_outputs` — 所有 Agent 的顶层输出（统一表）

**设计动机**：过去每种 Agent 独立一张顶层表（research_reports / screener_results / skeptic_results / supervisor_decisions）—— 加新 Agent 必须改 schema。本表采用"**元数据字段 + payload_json 容器**"模式，**所有现有和未来 Agent 的顶层输出都写这一张**，加新 Agent 零 migration。

| 字段 | 类型 | 约束 | 中文含义 | 示例值 |
|---|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 | 42 |
| run_id | INTEGER | FK `runs.id` NOT NULL | 所属运行 | 1 |
| agent_name | TEXT | NOT NULL | Agent 标识 | `supervisor` / `research` / `screener` / `skeptic` / 未来 `critic` |
| sequence | INTEGER | NOT NULL | 本 run 内该 agent 的第几次执行 | Supervisor 1-4；其他通常 1 |
| status | TEXT | NOT NULL | 执行结果 | `success` / `failed` |
| summary | TEXT |  | **通用文字摘要**（任意 agent 都可填）| Supervisor=reasoning；Research=overall_notes；Screener=comparison_summary；Skeptic=覆盖统计；finalize=supervisor notes |
| payload_json | TEXT |  | **各 agent 专属结构化数据**（JSON）| 下表详述各 agent 的 payload 结构 |
| metrics_json | TEXT |  | **通用运行指标**（JSON）| `{"latency_ms": 30123, "llm_tokens": 2450, "cache_hit": false, "retry_count": 0}` |
| metadata_json | TEXT |  | 未来扩展字段 | `{"model": "deepseek-reasoner"}` |
| created_at | DATETIME | NOT NULL | 创建时间 | |
| **唯一索引** | `(run_id, agent_name, sequence)` | | 保证 Supervisor 每轮、其他 agent 每次都唯一 |
| **索引** | `(agent_name, created_at DESC)` | | 跨 run 按 agent 查询 |

**各 agent 的 `payload_json` 形态约定**（应用层用 Pydantic 校验）：

| agent_name | summary 填什么 | payload_json 结构 |
|---|---|---|
| `supervisor` | 本轮 reasoning（≥20 字）| `{"action": "dispatch_research/screener/skeptic/finalize", "instructions": "...", "notes": "finalize 时的综合判断"}` |
| `research` | overall_notes | `{"tool_call_count": 5, "tool_names": ["..."]}` |
| `screener` | **comparison_summary**（横向对比）| `{"threshold_used": 0.65, "candidates_count": 3}` |
| `skeptic` | "本次覆盖 3 只，产出 2 条 logic_risk + 3 条 data_gap" | `{"covered_stocks": ["300750","002594"]}` |
| 未来 `critic` | 对历史推荐的复盘总结 | `{"review_period": "2026-03", "accuracy_rate": 0.68, ...}`（完全自定义） |

**加新 agent 的流程**：
1. 应用层定义 Pydantic 模型（如 `CriticOutput`）描述 payload 结构
2. 在 agent 执行完后 `agent_outputs_repo.insert(run_id=X, agent_name='critic', summary=..., payload_json=model.model_dump_json(), metrics_json=...)`
3. **无需 Alembic migration、无需改 schema、无需改视图**（视图用 WHERE agent_name=... 即可选择性 JOIN）

### 3.5 Research 明细

#### 表 7：`stock_data_entries`（每只研究股的数据，Research 产出）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK `agent_outputs.id` NOT NULL | **通用 FK**：指向 agent_name='research' 的那行 |
| code | TEXT | NOT NULL | 6 位股票代码 |
| name | TEXT | NOT NULL | |
| industry | TEXT | NOT NULL | |
| leadership | TEXT |  | 龙头地位描述 |
| holder_structure | TEXT |  | 股东结构分析 |
| financial_summary | TEXT |  | 财务摘要（YoY 语义） |
| technical_summary | TEXT |  | 技术面摘要（MA20/MACD/量能） |
| price_benefit | TEXT |  | 产品涨价受益 |
| data_gaps_json | TEXT |  | JSON 数组：未拿到的数据项 |
| sources_json | TEXT |  | JSON 数组：调用过的工具名 |
| created_at | DATETIME | NOT NULL | |
| **唯一索引** | `(agent_output_id, code)` | | 同一次 Research 内不重复 |
| **索引** | `(code, created_at DESC)` | | 跨运行按股票查研究历史 |

#### 表 8：`tool_calls`（ReAct 工具调用审计）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK `agent_outputs.id` NOT NULL | **通用 FK**：指向本次 Research 的 agent_outputs 行 |
| sequence | INTEGER | NOT NULL | ReAct 循环内的第几次（1-based） |
| tool_name | TEXT | NOT NULL | 工具名 |
| args_json | TEXT | NOT NULL | 调用参数 JSON |
| stock_code | TEXT |  | **链路辅助列**：若 args 含 `code` 则冗余存一份 |
| result_preview | TEXT |  | 返回 JSON 的前 500 字（审计证据） |
| latency_ms | INTEGER |  | 调用耗时 |
| error | TEXT |  | AkShare 接口失败时的错误消息 |
| created_at | DATETIME | NOT NULL | |
| **索引** | `(agent_output_id, sequence)` / `(stock_code, created_at DESC)` | | |

### 3.6 Screener 明细（业务摘要核心载体）

> **注**：Screener 的横向对比（`comparison_summary`）存在 `agent_outputs.summary`（agent_name='screener'）；门槛和候选数存 `agent_outputs.payload_json`。表 9-10 只放**股票维度的明细**。

#### 表 9：`stock_recommendations`（**推荐摘要 + 优势/风险**）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK `agent_outputs.id` NOT NULL | **通用 FK**：指向 agent_name='screener' 那行 |
| stock_data_entry_id | INTEGER | FK `stock_data_entries.id` | 关联 Research 的研究记录 |
| code | TEXT | NOT NULL | 股票代码（冗余） |
| name | TEXT | NOT NULL | |
| total_score | REAL | NOT NULL | 加权总分 0.0-1.0 |
| recommendation_level | TEXT | NOT NULL | `recommend` / `watch` / `skip` |
| rank | INTEGER |  | 批内排名 |
| **recommendation_rationale** | TEXT |  | **★ 推荐理由摘要**：这只股为什么最终被推荐/观察/跳过（50-150 字，含与同批的简短对比） |
| **key_strengths_json** | TEXT |  | **★ 核心优势列表**（JSON 数组）如 `["细分领域龙头","财务同比高增"]` |
| **key_risks_json** | TEXT |  | **★ 核心风险列表**（JSON 数组）如 `["估值偏高","技术面数据缺失"]` |
| data_gaps_json | TEXT |  | Screener 识别的数据缺口 |
| trigger_ref | TEXT | NOT NULL | 关联触发 |
| created_at | DATETIME | NOT NULL | |
| **索引** | `(agent_output_id, rank)` / `(code, created_at DESC)` | | 第二索引支持跨 run 历史查询 |

#### 表 10：`condition_scores`（每条件打分细节）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| stock_recommendation_id | INTEGER | FK `stock_recommendations.id` NOT NULL | |
| condition_id | TEXT | NOT NULL | 对应 `conditions.condition_id` |
| condition_name | TEXT | NOT NULL | |
| satisfaction | REAL | NOT NULL | 0 / 0.5 / 1 |
| weight | REAL | NOT NULL | |
| weighted_score | REAL | NOT NULL | |
| reasoning | TEXT | NOT NULL | 打分依据（≥15 字） |
| created_at | DATETIME | NOT NULL | |
| **唯一索引** | `(stock_recommendation_id, condition_id)` | | |

### 3.7 Skeptic 明细

> **注**：Skeptic 的顶层（covered_stocks、统计信息）存 `agent_outputs`（agent_name='skeptic'）。表 11 只放每条质疑的明细。

#### 表 11：`skeptic_findings`（每条质疑，**强 FK 到推荐股**）

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| agent_output_id | INTEGER | FK `agent_outputs.id` NOT NULL | **通用 FK**：指向 agent_name='skeptic' 那行 |
| **stock_recommendation_id** | INTEGER | FK `stock_recommendations.id` | **★ 链路 FK**：直接关联推荐股 |
| stock_code | TEXT | NOT NULL | 冗余字段便于查询 |
| finding_type | TEXT | NOT NULL | `logic_risk` / `data_gap` |
| content | TEXT | NOT NULL | 质疑内容（≥20 字） |
| created_at | DATETIME | NOT NULL | |
| **索引** | `(agent_output_id, stock_code)` / `(stock_recommendation_id)` | | |

### 3.8 AkShare 数据快照（跨运行复用）

#### 表 12-14：`financial_snapshots` / `holder_snapshots` / `technical_snapshots`

**共同字段**：

| 字段 | 类型 | 约束 | 中文含义 |
|---|---|---|---|
| id | INTEGER | PK | |
| code | TEXT | NOT NULL | 股票代码 |
| as_of | DATE | NOT NULL | 数据截至日期（财务=报告期；股东=公告期；技术=收盘日） |
| raw_json | TEXT | NOT NULL | AkShare 返回的完整 JSON（审计证据） |
| source | TEXT | NOT NULL | `sina` / `eastmoney` |
| created_at | DATETIME | NOT NULL | 首次入库 |
| updated_at | DATETIME |  | 如后续覆盖更新 |
| **唯一键** | `(code, as_of)` | | 跨运行复用，同股同日期只存一份 |

**`financial_snapshots` 专属列**：
- `latest_period TEXT` / `yoy_period TEXT`（最新期 + 去年同期）
- `financial_summary TEXT`（如 "归母净利润 xx 亿，同比 +35.6%"）
- `raw_metrics_json TEXT`（详细财务指标）

**`holder_snapshots` 专属列**：
- `smart_money_pct REAL` / `state_pct REAL` / `foreign_pct REAL`（聪明钱/国资/外资占比）
- `holder_structure TEXT`（人类可读的股东摘要）

**`technical_snapshots` 专属列**：
- `close REAL` / `ma20 REAL` / `volume_ratio REAL` / `macd_signal TEXT`
- `technical_summary TEXT`

### 3.9 链路追溯视图

#### 表 15（SQL View）：`v_recommendation_trace`

**改造后**：顶层表合并为 `agent_outputs`，外部 JOIN 从 4 个变成 2 个（`agent_outputs`×1 + `triggers` + `stock_data_entries`），其余相关 agent 的摘要用 LATERAL-like 子查询按 `(run_id, agent_name)` 拉取。子查询是按主键索引走，代价可忽略。

```sql
CREATE VIEW v_recommendation_trace AS
SELECT
  -- 股票核心
  r.id AS rec_id,
  r.code, r.name, r.total_score, r.recommendation_level AS level, r.rank,
  -- Screener 业务摘要
  r.recommendation_rationale, r.key_strengths_json, r.key_risks_json,
  ao_screener.summary AS comparison_summary,
  ao_screener.run_id,
  -- 触发源
  t.trigger_id, t.headline AS trigger_headline, t.industry AS trigger_industry,
  t.strength AS trigger_strength, t.mode AS trigger_mode,
  -- Research 5 维度
  sde.leadership, sde.financial_summary, sde.holder_structure,
  sde.technical_summary, sde.price_benefit, sde.data_gaps_json AS research_data_gaps,
  -- 条件打分聚合
  (SELECT json_group_array(json_object(
    'condition_id', cs.condition_id, 'satisfaction', cs.satisfaction,
    'weight', cs.weight, 'weighted_score', cs.weighted_score, 'reasoning', cs.reasoning))
   FROM condition_scores cs WHERE cs.stock_recommendation_id = r.id) AS condition_scores_json,
  -- Skeptic 质疑聚合（通过 FK 精确关联）
  (SELECT json_group_array(json_object(
    'finding_type', sf.finding_type, 'content', sf.content))
   FROM skeptic_findings sf WHERE sf.stock_recommendation_id = r.id) AS skeptic_findings_json,
  -- 工具调用聚合（按 stock_code 过滤 + 限定同一 Research agent_output）
  (SELECT json_group_array(json_object(
    'sequence', tc.sequence, 'tool', tc.tool_name, 'latency_ms', tc.latency_ms, 'error', tc.error))
   FROM tool_calls tc
   WHERE tc.stock_code = r.code AND tc.agent_output_id = sde.agent_output_id) AS tool_calls_json,
  -- Supervisor 综合判断（finalize 那一轮的 notes，从 payload_json 取）
  (SELECT json_extract(ao.payload_json, '$.notes') FROM agent_outputs ao
   WHERE ao.run_id = ao_screener.run_id
     AND ao.agent_name = 'supervisor'
     AND json_extract(ao.payload_json, '$.action') = 'finalize'
   LIMIT 1) AS supervisor_notes,
  r.created_at AS rec_created_at
FROM stock_recommendations r
JOIN agent_outputs ao_screener
  ON ao_screener.id = r.agent_output_id AND ao_screener.agent_name = 'screener'
LEFT JOIN triggers t ON t.run_id = ao_screener.run_id
LEFT JOIN stock_data_entries sde ON sde.id = r.stock_data_entry_id;
```

**JOIN 次数对比**：

| 项目 | 原设计 | 档位 A |
|---|---|---|
| 顶层表 JOIN | `screener_results` + `supervisor_decisions`（2 个独立 JOIN） | `agent_outputs` ×1（用 agent_name 过滤） |
| 主视图外部 JOIN 总数 | 4 个（`screener_results` + `triggers` + `stock_data_entries` + `supervisor_decisions`） | **3 个** |
| 加新 agent 是否要改视图 | 是（加 LEFT JOIN） | **否**（LLM 想用新 agent 的输出就在应用层查 agent_outputs） |

---

## 四、链路追溯能力（每只推荐股可反查的 8 维证据）

| # | 维度 | 证据来源（档位 A 路径）| 说明 |
|---|---|---|---|
| ① | 源头新闻 | `stock_recommendations` → `agent_outputs`(screener) → `runs` → `triggers.source_news_ids[]` → `news_items` | 追溯到触发本次推荐的原始新闻 |
| ② | Research 各维度数据 | `stock_data_entries.{leadership, holder_structure, financial_summary, technical_summary, price_benefit}` | 5 个研究维度的文本 |
| ③ | 工具调用证据 | `tool_calls` WHERE `stock_code=rec.code AND agent_output_id=sde.agent_output_id` | Research 对这只股调了哪些工具、参数、耗时 |
| ④ | 条件打分细节 | `condition_scores.stock_recommendation_id` | C2/C3/... 各给几分、为什么 |
| ⑤ | **推荐理由摘要** | `stock_recommendations.recommendation_rationale` + `key_strengths_json` + `key_risks_json` | 一句话读懂为什么推荐 |
| ⑥ | **横向对比** | `agent_outputs.summary` WHERE `agent_name='screener'` | 同行业为什么选这只 |
| ⑦ | Skeptic 质疑 | `skeptic_findings.stock_recommendation_id` | logic_risk + data_gap |
| ⑧ | Supervisor 综合判断 | `agent_outputs.payload_json->>'notes'` WHERE `agent_name='supervisor' AND payload_json->>'action'='finalize'` | 整份报告的总结 |

**LLM 原始 prompt / response / reasoning_content 不在 DB 落盘**——由 LangSmith 承担审计；需要时按 `run_id` 在 LangSmith project 里搜 trace。

**加新 agent 维度（如未来 Critic）的自动追溯**：应用层直接 `SELECT * FROM agent_outputs WHERE run_id=X AND agent_name='critic'` 即可，不改视图、不建新表。

---

## 四·补充：与 Phase 4（个股分析）的集成点

Phase 4 的"合成 Trigger"设计零 DB schema 改动，所有数据自然落入上述 14 张表。本节定义 **Phase 4 相关的约定和新增视图**。

### 4·1 `focus_codes` 的存储位置：`triggers.metadata_json`

Phase 4 把用户输入的股票合成一条 trigger 时，`focus_codes` 和 `focus_primary` 写入 `triggers.metadata_json` 的 JSON 容器，不为此加专用列。

**示例**：

```sql
-- 合成 Trigger 时（Phase 4 的 single_stock_trigger.py 里）
INSERT INTO triggers (trigger_id, run_id, headline, industry, type, source, summary, mode, metadata_json, created_at)
VALUES ('T-STOCK-300750-20260419153000', 42,
  '个股深度分析：宁德时代（对标 比亚迪、阳光电源）', '动力电池',
  'individual_stock_analysis', 'user_request',
  '用户请求分析 300750 宁德时代...', 'live',
  '{"focus_codes":["300750","002594","300274"],"focus_primary":"300750","peer_names":["比亚迪","阳光电源"]}',
  CURRENT_TIMESTAMP);
```

**标准 metadata_json 键约定**（会在 `docs/DB_SCHEMA.md` 里列出）：

| Key | 类型 | 用途 |
|---|---|---|
| `focus_codes` | `List[str]` | 本次分析聚焦的所有股票代码（主股 + 对标） |
| `focus_primary` | `str` | 主股代码（由用户主动指定，Skeptic 重点质疑此股） |
| `peer_names` | `List[str]` | 对标股的名称，便于 Markdown 渲染时直接显示 |

### 4·2 ★ 新增 SQL View：`v_stock_analysis_history`（跨模式股票分析历史）

**动机**：合并"事件驱动候选股"与"个股主动分析"两种模式，一条查询看某只股的完整被分析轨迹（含角色标签 primary/peer/candidate）。

```sql
CREATE VIEW v_stock_analysis_history AS
SELECT
  r.code, r.name,
  r.total_score, r.recommendation_level, r.rank,
  r.recommendation_rationale, r.key_strengths_json, r.key_risks_json,
  t.type AS analysis_type,         -- 'individual_stock_analysis' / 'policy_landing' / ...
  t.headline AS trigger_headline,
  t.industry AS trigger_industry,
  CASE
    WHEN t.type = 'individual_stock_analysis'
         AND json_extract(t.metadata_json, '$.focus_primary') = r.code
      THEN 'primary'     -- 主股（用户主动点名分析）
    WHEN t.type = 'individual_stock_analysis'
      THEN 'peer'        -- 对标股（被自动拉进来横向对比）
    ELSE 'candidate'     -- 事件驱动下的候选股
  END AS role,
  ao_screener.run_id,
  r.created_at
FROM stock_recommendations r
JOIN agent_outputs ao_screener
  ON ao_screener.id = r.agent_output_id AND ao_screener.agent_name = 'screener'
JOIN triggers t ON t.run_id = ao_screener.run_id;
```

**典型查询**：

```sql
-- 1. 某股所有被分析历史（不管主动还是事件驱动）
SELECT created_at, analysis_type, role, total_score, recommendation_level, trigger_headline
FROM v_stock_analysis_history WHERE code='300750' ORDER BY created_at DESC;

-- 2. 只看用户主动发起的分析
SELECT * FROM v_stock_analysis_history WHERE code='300750' AND role='primary' ORDER BY created_at DESC;

-- 3. 最近 30 天被主动分析过的所有股 + 最近一次评分
SELECT code, name, MAX(created_at) AS last_at, total_score, recommendation_level
FROM v_stock_analysis_history
WHERE role='primary' AND created_at >= date('now','-30 days')
GROUP BY code ORDER BY last_at DESC;

-- 4. 对比同一股在"主动分析"vs"事件驱动候选"两种 role 下的平均评分
SELECT code, role, AVG(total_score) AS avg_score, COUNT(*) AS n
FROM v_stock_analysis_history WHERE code='300750' GROUP BY role;
```

### 4·3 Phase 3 与 Phase 4 的互相不依赖保证

- **Phase 3 不依赖 Phase 4**：完全自给自足，事件驱动模式跑通即可
- **Phase 4 不依赖 Phase 3**：若 DB 还没建，个股分析仍走 state 内存 + Markdown 文件输出
- **同时有时**：`v_stock_analysis_history` 视图需 Phase 3 建完才有效；Phase 4 合成 Trigger 的 `metadata_json` 约定对 Phase 3 `triggers` 表完全兼容

---

## 五、实施步骤（共 7 步，预计 8 小时）

### 步骤 D1：依赖 + 骨架（0.5h）

- `requirements.txt` 加 `sqlalchemy>=2.0`、`alembic>=1.13`
- 新建 `db/` 目录：
  - `db/__init__.py`
  - `db/engine.py` — `get_engine()` / `get_session()` / 默认 `DB_URL=sqlite:///data/stock_agent.db`（可被 `STOCK_AGENT_DB_URL` 环境变量覆盖）
  - `db/models.py` — 所有 SQLAlchemy 模型（17 张表）
  - `db/repos/` — 按聚合根拆 Repository（runs_repo / triggers_repo / research_repo / screener_repo / skeptic_repo / snapshots_repo）
- `alembic init db/migrations`，`env.py` 的 `target_metadata` 指向 `db.models.Base.metadata`
- 生成初始 migration：`alembic revision --autogenerate -m "initial schema"`
- **手写 migration 补两个 SQL View**（Alembic autogenerate 不支持 VIEW）：
  - `v_recommendation_trace`（§3.9）—— 推荐股链路追溯
  - `v_stock_analysis_history`（§4·2）—— 跨模式股票分析历史
  - 两个视图都用 `op.execute("CREATE VIEW ...")` 写进 migration
- `.env.example` 加 `STOCK_AGENT_DB_URL=sqlite:///data/stock_agent.db`
- `.gitignore` 加 `data/stock_agent.db`

### 步骤 D2：用户 & 条件迁移到 DB（1h）

- `main.py` 启动时：`alembic upgrade head`
- 新增 `scripts/seed_from_json.py`：把 `config/user_profile.json` 导入 `users` + `conditions`
- `agents/screener.py::_load_profile` 改为从 DB 读
- **侵入性变更说明**：过去改 `user_profile.json` 立即生效；现在改 JSON 后需重新 seed（或直接改 DB）——文档要说清楚

### 步骤 D3：四节点渐进式落盘（通用 agent_outputs）+ Screener 业务摘要扩展（2.2h）

- `db/repos/runs_repo.py::create_run(user_id, trigger_key) -> run_id`：`main.py` 入口调用
- **通用 repo**：`db/repos/agent_outputs_repo.py::log(run_id, agent_name, sequence, summary, payload_json, metrics_json) -> agent_output_id` —— 所有 agent 共用一个函数落顶层
- 改造每个 agent node（产出 `agent_output_id` 再写自己的明细表）：
  - `agents/supervisor.py::supervisor_node` → `agent_outputs_repo.log(agent_name='supervisor', sequence=round, summary=reasoning, payload_json={action, instructions, notes})`
  - `agents/research.py::research_node` → `agent_outputs_repo.log(agent_name='research', ...)` → 拿到 `agent_output_id` 写 `stock_data_entries` + `tool_calls`
  - `agents/screener.py::screener_node` → `agent_outputs_repo.log(agent_name='screener', summary=comparison_summary, ...)` → 写 `stock_recommendations`（含 rationale/strengths/risks）+ `condition_scores`
  - `agents/skeptic.py::skeptic_node` → `agent_outputs_repo.log(agent_name='skeptic', ...)` → 写 `skeptic_findings`（含 FK `stock_recommendation_id`）
- **扩展 Screener 业务摘要**（★ 核心变更）：
  - `schemas/screener.py`：
    - `ScreenerResult` 新增 `comparison_summary: Optional[str]`
    - `StockRecommendation` 新增 `recommendation_rationale: Optional[str]` / `key_strengths: List[str] = []` / `key_risks: List[str] = []`
  - `config/prompts/screener.md`：在输出格式加这 4 字段，要求 LLM 一次 JSON 产出
- `main.py` 末尾：`runs_repo.mark_finished(run_id)`；异常时 `runs_repo.mark_failed(run_id, error)`

### 步骤 D4：AkShare 快照入库 + 跨运行复用（1.5h）

- `tools/real_research_tools.py` 里每个工具增加一层："查 snapshot 表 → 命中则返回缓存；否则调 AkShare → 落盘 → 返回"
- `tools/trigger_fetcher.py::fetch_latest_news()` 拉下的 news 立即落 `news_items`（content_hash 去重）
- `summarize_as_trigger` 完成后把 `source_news_ids` 写入 `triggers.source_news_ids`

### 步骤 D5：删除 Markdown 文件输出 + 新增查看 CLI（0.5h）

- `render/markdown_report.py::finalize_node` 不再写 `outputs/runs/*.md`，只 `runs_repo.mark_finished(run_id)`
- `render/markdown_report.py::_render` 函数保留（供 CLI 调用）
- 新增 `scripts/show_run.py`：`python scripts/show_run.py [run_id]`（默认最新一条），从 DB 查数据 + 渲染 Markdown 到 stdout
- `main.py` 结束时打印：`Done. run_id=42. View: python scripts/show_run.py 42`

### 步骤 D6：测试适配（1.5h）

- `tests/conftest.py` 新增 fixture：每个测试用 `sqlite:///:memory:`，自动 `create_all()`
- 原 `test_smoke.py` 断言 "md 文件存在" 改为 "DB 里 runs 表有 `status=completed` 记录 + 三类结果表各 ≥1 行"
- `S1` 测试：不再改 `user_profile.json`，改为 `conditions_repo.soft_delete(user_id, 'C3')`
- `S2` 测试：`conditions_repo.update_weight(user_id, 'C2', 0.05)`
- 新增 `tests/test_db_persistence.py`：
  - `test_run_creates_runs_row`
  - `test_supervisor_decisions_ordered_by_round`
  - `test_news_items_dedup_by_content_hash`
  - `test_snapshots_cross_run_reuse`（同股票跨两次运行应只调一次 AkShare）
  - `test_v_recommendation_trace_joins_all_dimensions`

### 步骤 D7：README + 管理 CLI + 表结构文档（1h）

- `README.md` 加 `## 数据库` 一节（安装 / seed / show_run / 直连 SQL）
- 新增 `scripts/list_runs.py`（列最近 N 条）
- 新增 `scripts/export_recommendations_csv.py`（可选，导出推荐历史）
- **新增 `docs/DB_SCHEMA.md`**：14 张表 + 2 SQL View 完整字段清单（每字段：名 / 类型 / 约束 / 中文含义 / 示例值）+ 去重策略 + 时间字段约定 + **`metadata_json` 标准键约定**（含 `focus_codes` / `focus_primary` / `peer_names` 等 Phase 4 约定）+ 常用 SQL 查询模板

---

## 六、关键文件清单

### 新建
- `db/__init__.py` / `db/engine.py` / `db/models.py`
- `db/repos/*.py`（5-6 个 Repository：`users_repo`, `runs_repo`, **`agent_outputs_repo`**（核心）, `triggers_repo`, `snapshots_repo`, `news_items_repo`）
- `db/migrations/`（Alembic）
- `scripts/seed_from_json.py` / `scripts/show_run.py` / `scripts/list_runs.py`
- `tests/test_db_persistence.py`
- `data/stock_agent.db`（首次运行生成，`.gitignore`）
- `docs/DB_SCHEMA.md`

### 修改
- `main.py` — 启动时 `alembic upgrade head` + 创建 run + 异常时 mark_failed
- `agents/*.py`（4 个）— 每个 node 追加 `*_repo.insert(...)`
- `agents/screener.py::_load_profile` — 从 DB 读取
- `schemas/screener.py` — `ScreenerResult` + `StockRecommendation` 新增 4 字段
- `config/prompts/screener.md` — Prompt 里新增 4 字段的输出要求
- `tools/real_research_tools.py` — 快照缓存层
- `tools/trigger_fetcher.py` — news 落盘 + trigger 落盘
- `render/markdown_report.py::finalize_node` — 不再写 md 文件
- `tests/helpers.py` / 6 个测试文件 — 适配 DB 断言
- `requirements.txt` — 加 sqlalchemy / alembic
- `.env.example` — 加 DB_URL
- `.gitignore` — 加 `*.db`

### 删除
- 无（Markdown 渲染逻辑保留供 CLI 用；`outputs/runs/` 目录保留作历史归档）

---

## 七、验证方案

### 单元测试
```bash
pytest tests/test_db_persistence.py -v   # 新增 DB 测试
pytest tests/ -v                         # 22 原测试全绿（经适配）
pytest tests/ -v -m real_data            # 8 real_data 仍绿
```

### 端到端
```bash
alembic upgrade head
python scripts/seed_from_json.py
python main.py                            # live 模式
# 输出：Done. run_id=1. View: python scripts/show_run.py 1
python scripts/show_run.py                # 查看最新
python scripts/list_runs.py               # 列最近 run
```

### 链路追溯 SQL 验证
```bash
# 1. 某只推荐股的完整 8 维证据（一条 SQL）
sqlite3 data/stock_agent.db "SELECT * FROM v_recommendation_trace ORDER BY rec_created_at DESC LIMIT 1;"

# 2. 某只股票跨 run 历史轨迹
sqlite3 data/stock_agent.db "SELECT rec_created_at, trigger_headline, total_score, level \
  FROM v_recommendation_trace WHERE code='300750';"

# 3. ★ 为什么推荐这只股（业务摘要）
sqlite3 data/stock_agent.db "SELECT code, recommendation_level, recommendation_rationale, \
  key_strengths_json, key_risks_json FROM stock_recommendations ORDER BY id DESC LIMIT 1;"

# 4. ★ 同行业横向对比说明
sqlite3 data/stock_agent.db "SELECT s.comparison_summary, r.code, r.total_score, r.rank \
  FROM screener_results s JOIN stock_recommendations r ON r.screener_result_id=s.id \
  WHERE s.run_id=1 ORDER BY r.rank;"

# 5. Research 对某股调的工具历史
sqlite3 data/stock_agent.db "SELECT sequence, tool_name, latency_ms, error \
  FROM tool_calls WHERE stock_code='300750' ORDER BY created_at DESC LIMIT 20;"

# 6. 某推荐股的 Skeptic 质疑（FK 精确 join）
sqlite3 data/stock_agent.db "SELECT sf.finding_type, sf.content \
  FROM skeptic_findings sf JOIN stock_recommendations sr \
  ON sf.stock_recommendation_id=sr.id WHERE sr.id=1;"

# LLM 原始 prompt/response/reasoning → LangSmith project (LANGSMITH_PROJECT=stock-agent-v6-mvp)
```

### 扩展性验证
```sql
-- a) 不改 schema 往 metadata_json 加字段
UPDATE triggers SET metadata_json = json_set(COALESCE(metadata_json, '{}'), '$.risk_level', 'high') WHERE id=1;

-- b) 加新用户（多用户扩展）
INSERT INTO users (user_id, name, recommendation_threshold) VALUES ('mom_001', '老妈的策略', 0.70);

-- c) 加新选股条件
INSERT INTO conditions (user_id, condition_id, name, layer, description, weight)
VALUES ('dad_001', 'C8', '现金流健康', 'screener', '经营性现金流 > 净利润', 0.10);
-- 下次 Screener 运行自动纳入评分
```

---

## 八、关键风险与应对

| 风险 | 应对 |
|---|---|
| Alembic 自动迁移对 `CREATE VIEW` 不友好 | 视图定义手写在一个 raw SQL migration 里，不用 autogenerate |
| SQLite 默认不支持外键约束 | engine 创建时 `PRAGMA foreign_keys=ON` |
| 大量 Pydantic ↔ SQLAlchemy 映射样板 | 在各 repo 里封装 `from_pydantic(model) -> ORM`、`to_pydantic(orm) -> model` 辅助函数 |
| 测试并发 `:memory:` DB 不共享 | 每测试独立 engine + create_all；用 `pytest-xdist` 时也 OK |
| AkShare snapshot 覆盖策略（同 code 同 as_of 但数据变了） | 用 `INSERT ... ON CONFLICT(code,as_of) DO UPDATE ...` 刷新 raw_json + `updated_at` |

---

## 九、工作量估算

| 步骤 | 时长 |
|---|---|
| D1 骨架 + Alembic（14 张表 + 2 SQL View 手写 migration） | 0.5h |
| D2 users+conditions 入库 | 1h |
| D3 四节点落盘（统一 agent_outputs_repo）+ Screener 业务摘要扩展 | 2.2h |
| D4 AkShare 快照入库 | 1.5h |
| D5 删 Markdown + show_run CLI | 0.5h |
| D6 测试适配 | 1.5h |
| D7 README + 管理 CLI + DB_SCHEMA.md | 1h |
| **总计** | **≈ 8h**（与档位 A 改造前持平，但后续加新 agent 零成本） |

---

## 十、审阅要点

请对照以下问题判断方案是否合理：

1. **14 张表**（已从 17 张减到 14 张，4 顶层表合并为 `agent_outputs`）是否有冗余？是否有遗漏的业务实体？
2. **链路追溯 8 维**是否覆盖了你想查询的所有维度？
3. **Screener 的 3 个新字段**（recommendation_rationale / key_strengths / key_risks）是不是你说的"模型参数分析的业务摘要"？
4. **news_items 去重策略**（title + source，不含时间）是否符合你的预期？
5. **取消 Markdown 文件**、改为 `scripts/show_run.py [id]` 按需渲染，是否可接受？
6. **改 `user_profile.json` 需重新 seed**的侵入性，可接受还是希望保留 JSON 双向同步？
7. **档位 A（agent_outputs 通用表）**：加新 agent 零 migration 的设计，是否符合扩展性预期？JSON payload 查询略弱于强类型列的代价，你能接受吗？

确认无误后我就按 D1→D7 顺序实施。如需调整，告诉我要改哪一条。
