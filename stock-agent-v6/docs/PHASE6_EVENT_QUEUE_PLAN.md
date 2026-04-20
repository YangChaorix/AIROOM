# Stock Agent v6 — Phase 6：事件驱动架构升级计划

> 版本：2026-04-19
> 状态：**已实施完成**（本文档为事后计划+设计快照，供审阅对照）
> 前置：Phase 1 MVP / Phase 2 真实数据 / Phase 3 DB / Phase 4 个股分析 / Phase 5 调度器均已完成

---

## 一、背景与动机

### 1.1 Phase 5 完成后发现的架构断层

Phase 5 完成后，Scheduler 每天持续抓 7 个渠道 600-1000 条新闻到 `news_items` 表。但**现有数据流不读这张表**：

```
Scheduler ─持续抓─→ news_items（堆积 1000 条/天）
                        ↓
                   【无人读取】
                        ↓
User 跑 main.py --live
                        ↓
trigger_fetcher.fetch_latest_news()  ← 现场再调 AkShare 拉一次（冗余）
                        ↓
summarize_as_trigger(LLM)  ← 一次性函数调用，没有审计
                        ↓
Supervisor → Research → ...
```

**3 个问题**：
1. Scheduler 积累的 news 没被利用；每次 run 又重新抓
2. trigger 生成过程是函数调用，没落 `agent_outputs` 表，不可审计
3. 没有"已分析新闻"概念，同一事件可能被多次处理

### 1.2 用户需求（2026-04-19 对话）

用户提出明确需求：
- 新闻渠道要扩展（列了 3 个具体接口）
- Trigger Agent 写入事件表后需要**去重**，不能重复分析同一新闻
- 事件表直接作为 Supervisor 数据源（**事件驱动**，非 run-driven）

### 1.3 用户决策（AskUserQuestion 记录）

| 问题 | 决定 |
|---|---|
| news 消费粒度 | **一条 news 最多贡献 1 个 trigger**（FK 一对一） |
| Trigger Agent 触发时机 | **Scheduler 定时跑**（每 30 分钟） |
| main.py 消费行为 | `--consume N` 限量模式 |
| 新增 AkShare 渠道 | 百度经济日历 + 停牌公告 + 券商研报 |

### 1.4 目标流程

```
Scheduler (新闻抓取) ──定时─→ news_items (去重入库)
                                      │
Scheduler (Trigger Agent) ──定时─→  读未消费 news → LLM 筛选
                                      ↓
                         triggers (status='pending', priority 1-10)
                                      ↓
                         news_items.consumed_by_trigger_id 标记  ← 去重
                                      ↓
                  ←── python main.py --consume N ──→
                         按 priority DESC 取出 pending
                         → status=processing → run Supervisor → status=completed
```

---

## 二、设计要点

### 2.1 事件队列的状态机

```
pending ──(claim)──→ processing ──(成功)──→ completed
                         │
                         └──(异常)──→ failed ──(手动 requeue)──→ pending
```

- 原子性：`claim_next_pending` 用 `SELECT ... FOR UPDATE` 锁住（SQLite 忽略但 PG 兼容）
- 优先级：`ORDER BY priority DESC, created_at ASC`（优先级相同时 FIFO）

### 2.2 去重的两层语义

1. **入库去重（Phase 5 已有）**：`news_items.content_hash = SHA256(title + source)` UNIQUE —— 同标题同源跨天不重复入
2. **消费去重（Phase 6 新增）**：`news_items.consumed_by_trigger_id` FK —— 一条 news 被 trigger 引用后永久标记；Trigger Agent 下次跑 `WHERE consumed_by_trigger_id IS NULL`

### 2.3 候选池均衡采样（防"单渠道挤占"）

早期测试发现：按 `created_at DESC LIMIT 80` 时，新入库的 223 条研报一次性占满 80 条候选池，LLM 看不到其他源。

解决：**按 source 分组各取 N 条**（`_fetch_pending_news` 里实现），保证多源并存。

### 2.4 Agent 级调度和渠道级调度分离

- `config/news_channels.json` —— 管 "抓取 → 入库 news_items" 类任务
- `config/agent_schedule.json` —— 管 "Agent 任务"（当前只有 Trigger Agent，未来 Critic Agent 也加这里）

职责分离 + 扩展性强。

### 2.5 Trigger Agent 的"skip"能力

关键设计：Trigger Agent **允许判断没有值得分析的新闻**，返回 `{"action": "skip"}`，什么都不做（不产生 trigger）。避免 LLM 被迫"凑数"生成低质量 trigger。

实测：candidate pool 里只有研报和零散公告时，Agent 会 skip 并写 system_logs；遇到"发改委储能补贴细则"这种强信号会 generate + priority=10。

---

## 三、Schema 变更（Alembic `217751d42ff2` + `39227475371b`）

### 3.1 `triggers` 表新增字段

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `status` | TEXT NOT NULL | `'pending'` | 状态机 |
| `consumed_by_run_id` | INTEGER FK runs.id | NULL | 消费该 trigger 的 run |
| `priority` | INTEGER NOT NULL | `5` | 1-10，Trigger Agent 打分 |
| `processed_at` | DATETIME | NULL | 完成/失败时间 |

`triggers.run_id` 字段**语义变化**：
- 旧模型：产生该 trigger 的 run（一起创建）
- Phase 6 保留但退化为遗留字段；Trigger Agent 生成的 trigger `run_id=NULL`

Migration 里对历史数据做修复：`UPDATE triggers SET status='completed', consumed_by_run_id=run_id WHERE run_id IS NOT NULL`

### 3.2 `news_items` 表新增字段

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `consumed_by_trigger_id` | INTEGER FK triggers.id | NULL | 被哪个 trigger 引用 |
| `consumed_at` | DATETIME | NULL | 消费时间 |

**索引**：`(consumed_by_trigger_id)` + `(consumed_by_trigger_id, created_at)`（支持"未消费 + 最新"双条件查询）

### 3.3 枚举值统一英文（Alembic `39227475371b`）

`technical_snapshots.macd_signal`：`金叉/死叉/无交叉` → `golden_cross/death_cross/no_cross`（数据清洗 migration 幂等）。

---

## 四、代码变更

### 4.1 新建文件

| 文件 | 职责 |
|---|---|
| `agents/trigger.py` | Trigger Agent 主函数（`run_trigger`） |
| `config/prompts/trigger.md` | LLM system prompt |
| `config/agent_schedule.json` | Trigger Agent 定时配置 |
| `db/repos/triggers_queue_repo.py` | 队列原子操作（claim / mark_completed / mark_failed） |
| `scheduler/tasks.py::run_trigger` + `AGENT_TASKS` | Scheduler 调度层包装 |

### 4.2 修改文件

| 文件 | 改动要点 |
|---|---|
| `db/models.py` | Trigger 加 4 字段、NewsItem 加 2 字段 + 索引 |
| `config/news_channels.json` | 加 3 个新 AkShare 渠道 + `adapter` 字段 |
| `scheduler/tasks.py::_df_to_items` | 增加 3 个 adapter 分支（economic_event / suspend_notice / research_report） |
| `scheduler/run.py` | 支持 agent_schedule.json；`--once` 接受渠道/agent/'all'/'agents' |
| `main.py` | 新增 `consume_queue()` + `--consume N` CLI；拆出 `_run_with_trigger()` 复用 |
| `db/repos/news_items_repo.py` | `bulk_upsert` 返回 `{"ids", "inserted", "dedup_hit"}`，日志可区分新增 vs 命中 |
| `scripts/show_run.py` | 查 trigger 时兼容 `consumed_by_run_id`（新）和 `run_id`（旧）双语义 |
| `tools/real_research_tools.py` | `macd_signal` 写入英文枚举；`technical_summary` 展示保持中文 |

---

## 五、7 个 AkShare 渠道的最终配置

| 渠道 name | 接口 | cron | 实测条数 | adapter |
|---|---|---|---|---|
| news_cctv | `news_cctv` | 每天 08:00 | 12 | generic |
| stock_info_cjzc_em | `stock_info_cjzc_em` | 每天 07:00 | 400 | generic |
| stock_info_global_em | `stock_info_global_em` | 9-16 点每小时 5 分 | 200 | generic |
| stock_info_global_em_offhour | 同上 | 0/3/6/17/20/23 点 10 分 | 200（去重） | generic |
| **news_economic_baidu** | `news_economic_baidu` | 每天 08:15 | 99 | economic_event |
| **news_trade_notify_suspend_baidu** | 同名 | 9/12/15 点 | 8 | suspend_notice |
| **stock_research_report_em** | `stock_research_report_em` | 每天 09:30 | 223 | research_report |

**一次 `--once all` 实测入库 942 条**，SHA256 去重工作正常（第二次跑 0 新增）。

---

## 六、Trigger Agent 端到端验证（run_id=3）

### 6.1 输入
人工注入一条强信号 news：
```
news 943 | "发改委：储能行业补贴细则 2026 年 5 月起每千瓦时 0.35 元"
```

### 6.2 Trigger Agent 输出
```json
{
  "status": "generated",
  "trigger_row_id": 3,
  "trigger_id_str": "T-20260419-ES-1",
  "news_consumed": 1,
  "headline": "发改委明确新型储能补贴细则，5月起执行",
  "priority": 10
}
```
- `triggers 3` 入队 `status='pending', priority=10, industry='新能源储能'`
- `news_items 943.consumed_by_trigger_id=3`（永不再分析）

### 6.3 消费
```bash
$ python main.py --consume 1
[consume] 处理 trigger id=3 priority=10 headline=发改委明确新型储能补贴细则，5月起执行
  → Done run_id=3. View: python scripts/show_run.py 3
Consumed: {'processed': 1, 'errors': 0}
```

### 6.4 DB 最终状态

```
triggers 3: status=completed, consumed_by_run_id=3, processed_at=...
runs 3:     status=completed, trigger_key='queue:T-20260419-ES-1'
news 943:   consumed_by_trigger_id=3（永久占位）
```

### 6.5 报告质量
`python scripts/show_run.py 3` 渲染：
- Headline: "发改委明确新型储能补贴细则，5月起执行"
- 推荐列表：宁德时代 0.615 观察 / 阳光电源 0.53 观察 / 比亚迪 0.28 跳过（**主股正确命中储能行业**）

---

## 七、CLI 全景

```bash
# Scheduler（生产守护，Ctrl+C 退出）
python scheduler/run.py                       # 所有任务（news 渠道 + Trigger Agent）

# Scheduler（调试）
python scheduler/run.py --once news_cctv      # 只跑一个渠道
python scheduler/run.py --once trigger        # 只跑 Trigger Agent
python scheduler/run.py --once agents         # 所有 Agent
python scheduler/run.py --once all            # 全部

# main 消费队列
python main.py                                # 默认消费 1 个 pending
python main.py --consume 3                    # 最多 3 个
python main.py --consume all                  # 全部

# main 非队列模式（直跑）
python main.py --live                         # 实时合成
python main.py default                        # fixture
python main.py --stock 300750                 # 个股分析

# 队列状态查询
sqlite3 data/stock_agent.db "SELECT status, COUNT(*) FROM triggers GROUP BY status;"
sqlite3 data/stock_agent.db "SELECT id, priority, headline FROM triggers WHERE status='pending' ORDER BY priority DESC;"
```

---

## 八、验收清单（10 项）

| # | 验收点 | 状态 |
|---|---|---|
| 1 | 7 个新闻渠道定时入库，SHA256 去重生效 | ✅ 实测 |
| 2 | Trigger Agent 从 news_items 读未消费数据 | ✅ |
| 3 | Trigger Agent 支持 skip（无强信号不硬凑） | ✅ 实测返回 skipped |
| 4 | Trigger Agent 生成 trigger 时标记 news 已消费 | ✅ 实测 consumed_by_trigger_id 写入 |
| 5 | 同一条 news 不会生成第二个 trigger | ✅ FK 一对一约束 |
| 6 | triggers 按 priority DESC 消费 | ✅ run_id=3 实测选 priority=10 而非 priority=5 |
| 7 | main.py --consume N 限量消费 | ✅ |
| 8 | Scheduler 同时调度 news + agents | ✅ |
| 9 | 所有 DB 枚举英文化 | ✅ 含 macd_signal 数据清洗 |
| 10 | `show_run.py` 兼容新老 trigger 关联语义 | ✅ 修 `consumed_by_run_id` OR `run_id` |

---

## 九、与 Phase 3/4/5 的关系

- **Phase 3 架构**被完整复用：`agent_outputs` 通用表直接容纳 Trigger Agent（`agent_name='trigger'`，虽本期未落盘到 agent_outputs，仅写 system_logs；未来可补）
- **Phase 4 个股分析**保持兼容：`--stock` 直跑不入队列，triggers 直接写 `status=completed`
- **Phase 5 scheduler**被扩展：加了 agents[] 配置 + AGENT_TASKS 映射表
- **架构铁律**全部守护：`graph/edges.py` 零改动；4 Agent prompt 零改动

---

## 十、已知局限（留给后续 Phase）

1. **Trigger Agent 本身未写 `agent_outputs`**：其 run 时 run_id=NULL，不进 agent_outputs；改进方向：给 Trigger Agent 自己建一个"虚拟 run"或允许 agent_outputs.run_id NULL
2. **Trigger Agent 只产出 1 个 trigger**：即使候选池里有 3 个不同主题也合并；未来可扩为"多 trigger 并行生成"
3. **没有 Agent 本身的重试机制**：LLM 调用失败直接 skip，没有 exponential backoff
4. **未支持个股专用新闻（`stock_news_em(code=...)`）**：该接口需要 per-stock 参数，Scheduler 框架当前只支持"无参批量"；要接入需要扩展"按 user_profile 关注股列表轮询"

这 4 点都是可选增强，不影响当前事件驱动架构的完整性。
