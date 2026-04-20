# Stock Agent v6

一个基于 **真实 A 股数据**（AkShare）和 **DeepSeek 大模型**的多 Agent 选股研究流水线：

```
真实新闻 → Supervisor(LLM 循环) → Research(真 ReAct + AkShare) → Screener(LLM) → Skeptic(LLM) → Markdown 报告
                                        ↑______________________|
                         每个子 Agent 完成后回到 Supervisor 再次决策
```

## 快速开始

```bash
# 1. 装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 配环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 LANGSMITH_API_KEY
#   DeepSeek  → https://platform.deepseek.com/api_keys
#   LangSmith → https://smith.langchain.com/settings → API Keys

# 3. 跑一次
python main.py                # 默认 live：实时拉 AkShare 新闻 + LLM 摘要为 trigger
python main.py --live         # 同上
python main.py default        # 用 data/triggers_fixtures.json 的 default 触发
python main.py strong_policy  # 用 strong_policy fixture
python main.py weak_noise     # 用 weak_noise fixture

# 4. 跑测试
pytest tests/ -v              # 14 个结构 + 行为测试（需 DEEPSEEK_API_KEY）
pytest tests/ -v -m real_data # 8 个真实数据集成测试（AkShare 网络）
```

产出：`outputs/runs/run_YYYYMMDD_HHMMSS.md`  
LangSmith trace：`LANGSMITH_PROJECT` 项目下可见每次 LLM 调用 + ReAct 工具调用

## 项目结构

```
stock-agent-v6/
├── main.py                          入口：load trigger → build graph → invoke → write md
├── config/
│   ├── user_profile.json            ★ 改这里即改选股逻辑（条件即数据）
│   ├── models.json                  每个 agent 的模型/温度
│   ├── prompts/{agent}.md           ★ 改这里即改 Agent 行为
│   └── tools/research_tools.json    ★ 改这里即改 Research 的工具清单
├── data/
│   ├── triggers_fixtures.json       预置触发 fixture（测试/演示用）
│   └── industry_leaders_map.json    行业→龙头股映射（AkShare 行业接口兜底）
├── agents/
│   ├── llm_factory.py               ChatOpenAI + DeepSeek base_url 统一构造
│   ├── supervisor.py                单次 LLM 决策（reasoner）
│   ├── research.py                  AgentExecutor 真 ReAct（chat + 工具）
│   ├── screener.py                  单次 LLM 打分（chat）
│   └── skeptic.py                   单次 LLM 对抗质疑（reasoner）
├── tools/
│   ├── real_research_tools.py       6 个 AkShare 真实工具
│   ├── trigger_fetcher.py           实时新闻 + LLM 摘要为 trigger
│   └── _cache.py                    TTL 缓存装饰器
├── schemas/*.py                     Pydantic 数据模型
├── graph/
│   ├── builder.py                   LangGraph 装配
│   └── edges.py                     ★ route_from_supervisor 只读 last_decision.action
├── render/markdown_report.py        state → Markdown
└── tests/
    ├── test_supervisor_is_real.py   T1-T4 Supervisor 真实性
    ├── test_research_is_react.py    R1/R3 真 ReAct
    ├── test_screener_behavior.py    S1/S2/S3 条件即数据
    ├── test_skeptic_behavior.py     K1/K2/K3 对抗质疑
    ├── test_smoke.py                结构 smoke + 真 LLM E2E
    └── test_real_data_integration.py  ★ AkShare/Trigger 直测（-m real_data）
```

## 工具数据源速查（Phase 2 真实化）

| 工具 | AkShare 接口 | 数据源 | 稳定性 |
|---|---|---|---|
| search_news_from_db | news_cctv + stock_info_cjzc_em + stock_info_global_em | 央视网 + 东财 | 稳 |
| akshare_industry_leaders | stock_board_industry_cons_em → 失败降级 industry_leaders_map.json | eastmoney push → 本地表 | 混合 |
| stock_financial_data | stock_financial_abstract | Sina 财务 | 稳 |
| stock_holder_structure | stock_main_stock_holder | eastmoney info | 稳 |
| stock_technical_indicators | stock_zh_a_daily + pandas MACD/MA | Sina 日K | 稳 |
| price_trend_data | futures_spot_price (30 日汇总) | AkShare 期货 | 仅大宗商品 |

所有工具**不 raise**：失败转为带 `error`/`data_gap` 字段的 JSON，下游 Screener 正常打分。

## 架构铁律

1. **路由层零业务**：`graph/edges.py::route_from_supervisor` 只读 `state.last_decision.action`，禁止任何 if-else 业务判断（T1 守护）
2. **条件即数据**：Screener 的条件与权重只从 `user_profile.json` 注入 Prompt（S1/S2 守护）
3. **工具即配置**：Research 的工具清单只从 `research_tools.json` 加载（R3 守护）
4. **Prompt 外置**：4 个 Agent 的 system prompt 全部从 `config/prompts/*.md` 加载
5. **Supervisor 真 LLM**：路由决策必须来自真实 LLM 调用（T2 守护）
6. **工具层不 raise**：AkShare 失败转 `data_gap`，管道永不崩（real_data 测试守护）

## 测试速查

```bash
# 默认（不含真实数据）：14 个行为/结构测试
pytest tests/ -v

# 单独跑真实数据集成（需网络）
pytest tests/ -v -m real_data
# → 覆盖 6 个工具 + 2 个 trigger_fetcher 函数

# 全部
pytest tests/ -v -m ""   # 或移除 pytest.ini 里的 marker 定义
```

## 面试演示路径

1. `cat outputs/runs/run_*.md | tail -n 100` 展示当日真实数据推荐
2. 打开 LangSmith trace → 指着每一轮 Supervisor 的 reasoning + Research 的 AkShare 工具调用 span
3. 改 `config/user_profile.json` 的 C3 → 重跑 → md 里无 C3
4. 改 `data/industry_leaders_map.json` 加一个新行业 → 现场打一个 trigger fixture → 用新龙头跑
5. 跑 `pytest tests/test_supervisor_is_real.py -v` → 指出 T2 证明 Supervisor 非固定顺序

## 切换模型

只需改 `config/models.json` 和 `.env`。`agents/llm_factory.py` 按 `provider` 分派（`deepseek` / `openai`）。

## 数据库（Phase 3）

```bash
# 首次初始化
alembic upgrade head                     # 建 14 张表 + 2 SQL 视图
python scripts/seed_from_json.py         # config/user_profile.json → users + conditions

# 跑流程（数据自动入库）
python main.py                           # live 模式
python main.py --stock 300750            # 个股分析模式（Phase 4）

# 查报告
python scripts/show_run.py               # 最新一条
python scripts/show_run.py 42            # 指定 run_id

# 直接 SQL
sqlite3 data/stock_agent.db
sqlite> SELECT * FROM v_recommendation_trace ORDER BY rec_created_at DESC LIMIT 1;
sqlite> SELECT * FROM v_stock_analysis_history WHERE code='300750' AND role='primary';
```

详见 [`docs/DB_SCHEMA.md`](docs/DB_SCHEMA.md)。

## 个股分析（Phase 4）

```bash
python main.py --stock 300750            # 代码输入，自动拉 2 只行业对标做横向对比
python main.py --stock 宁德时代           # 名称输入（AkShare 做名→代码映射）
python main.py --stock 300750 --no-peers # 只分析主股，不拉对标
```

实现要点：
- 合成 Trigger（`type=individual_stock_analysis`）复用现有 LangGraph，零图结构改动
- `focus_codes` 和 `focus_primary` 进 `triggers.metadata_json`
- Research 看到 `focus_codes` 非空时只分析指定股票，不扩大候选范围

详见 [`docs/PHASE4_SINGLE_STOCK_PLAN.md`](docs/PHASE4_SINGLE_STOCK_PLAN.md)。

## 新闻自动抓取（Phase 5）

APScheduler 按 `config/news_channels.json` 配置的 cron 定时抓取多个新闻源，自动入 `news_items` 表（SHA256 去重）。失败/异常自动写 `system_logs` 表。

```bash
# 立即跑一次（调试/补抓）
python scheduler/run.py --once news_cctv       # 只跑某渠道
python scheduler/run.py --once all             # 全部渠道跑一次

# 守护进程（前台，Ctrl+C 退出）
python scheduler/run.py

# 查看新闻
sqlite3 data/stock_agent.db "SELECT source, COUNT(*) FROM news_items GROUP BY source;"

# 查看日志
sqlite3 data/stock_agent.db "SELECT level, source, substr(message,1,80) FROM system_logs ORDER BY id DESC LIMIT 20;"
```

**默认渠道配置**（改 `config/news_channels.json` 即改频率，无需改代码）：

| 渠道 | 接口 | 抓取频率 |
|---|---|---|
| 央视网 | `news_cctv` | 每天 08:00 |
| 东财-财经早餐 | `stock_info_cjzc_em` | 每天 07:00 |
| 东财-全球资讯 | `stock_info_global_em` | 盘中 9-16 点每小时 |
| 东财-全球资讯（盘后） | `stock_info_global_em` | 每 3 小时兜底（0/3/6/17/20/23 点） |

## 事件驱动架构（Phase 6）

架构升级：从"user run-driven"转向"event-driven"，引入 **Trigger Agent** 作为 Supervisor 之上的"事件筛选层"。

```
Scheduler (新闻抓取, cron) ──→ news_items (去重入库)
                                   │
            Scheduler (Trigger Agent, 每 30 分钟 cron) ──→
                                   ↓
                     读未消费 news → LLM 筛选 → 生成 trigger
                                   ↓
                     triggers 表 (status='pending', priority 1-10)
                                   ↓
                     news_items.consumed_by_trigger_id 标记  ← ★ 去重防重复分析
                                   ↓
                  ←── python main.py --consume N ──→
                     按 priority DESC 取出 pending → Supervisor → Research → ...
                                   ↓
                     triggers.status='completed', consumed_by_run_id=run
```

### 消费模式 CLI

```bash
# 从队列消费
python main.py                    # 消费最早 1 个 pending
python main.py --consume 3        # 最多 3 个
python main.py --consume all      # 全部

# 非队列模式（旧的直接跑）
python main.py --live             # 实时合成 trigger（不入队列）
python main.py default            # fixture
python main.py --stock 300750     # 个股分析
```

### 新闻渠道扩展到 7 个

| 渠道 | 接口 | 频率 |
|---|---|---|
| 央视网 | `news_cctv` | 每天 08:00 |
| 东财-财经早餐 | `stock_info_cjzc_em` | 每天 07:00 |
| 东财-全球资讯（盘中） | `stock_info_global_em` | 9-16 点每小时 |
| 东财-全球资讯（盘后） | `stock_info_global_em` | 盘后每 3 小时 |
| 百度-经济日历 | `news_economic_baidu` | 每天 08:15 |
| 百度-停牌公告 | `news_trade_notify_suspend_baidu` | 9/12/15 点 |
| 东财-券商研报 | `stock_research_report_em` | 每天 09:30 |

改 `config/news_channels.json` 即改频率，改 `config/agent_schedule.json` 即调 Trigger Agent cron，**不改代码**。

### Trigger Agent 快速触发

```bash
# 生产守护
python scheduler/run.py                            # 所有任务（渠道 + agents）

# 调试
python scheduler/run.py --once news_cctv           # 只跑某渠道
python scheduler/run.py --once trigger             # 只跑 Trigger Agent
python scheduler/run.py --once agents              # 只跑所有 agents
python scheduler/run.py --once all                 # 全部

# 手动模拟
python -c "from agents.trigger import run_trigger; print(run_trigger(hours=48, dry_run=True))"
```

### 队列状态查询

```bash
# Pending 队列大小
sqlite3 data/stock_agent.db "SELECT status, COUNT(*) FROM triggers GROUP BY status;"

# 看最新生成的 pending（优先级倒序）
sqlite3 data/stock_agent.db "SELECT id, priority, headline FROM triggers WHERE status='pending' ORDER BY priority DESC, created_at ASC;"

# 某条 news 被哪个 trigger 消费
sqlite3 data/stock_agent.db "SELECT ni.title, t.trigger_id, t.status FROM news_items ni LEFT JOIN triggers t ON ni.consumed_by_trigger_id=t.id WHERE ni.id=943;"
```

## 实施历史

- **Phase 1**（MVP）：骨架先行 → 4 个 Agent 全真 LLM → 14/14 测试通过
- **Phase 2**（真实数据）：AkShare 替换 6 个 mock 工具 + live 新闻摘要为 trigger + 8 个真数据集成测试
- **Phase 3**（数据库）：SQLite + SQLAlchemy + Alembic，14 张表 + 2 视图；agent_outputs 通用表加新 agent 零 migration；删除 Markdown 文件输出，改为 `scripts/show_run.py` 按需渲染
- **Phase 4**（个股分析）：`python main.py --stock <code_or_name>`，合成 Trigger 复用现有管道
- **Phase 5**（新闻调度器）：APScheduler + 渠道级差异化 cron 配置 + `system_logs` 表统一错误/审计日志
- **Phase 6**（事件驱动架构）：Trigger Agent（news_items 队列 → LLM 筛选 → triggers pending 队列）+ `main.py --consume N` 消费模式 + news 一对一消费去重 + 3 个新 AkShare 渠道
