# Stock Agent v3

基于 LangGraph + LLM 的 A 股智能分析系统，包含自动新闻采集、宏观事件触发、精选股票评分、收盘复盘，以及按需对任意股票进行多维度深度分析，并提供 Web Dashboard 可视化管理。

---

## 目录

- [系统架构](#系统架构)
- [功能特性](#功能特性)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [运行方式](#运行方式)
- [Web Dashboard](#web-dashboard)
- [个股分析](#个股分析)
- [系统配置项](#系统配置项)
- [数据库说明](#数据库说明)
- [模型切换](#模型切换)
- [Docker 部署](#docker-部署)
- [日志说明](#日志说明)

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                       新闻采集层                              │
│  财联社 / 东方财富 / 同花顺 (HIGH, 30min)                     │
│  新浪财经 / 财联社电报 / 财新 (MEDIUM, 60min)                 │
│  国家发改委 (LOW, 120min)                                     │
└──────────────────────┬───────────────────────────────────────┘
                       │ 按时段 + 优先级定时采集 / 手动触发
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                     SQLite 数据库                             │
│  news_items · event_history · run_logs · system_config       │
│  screener_stocks · review_reports · prompts · stock_analysis │
└───────┬──────────────────────────────────┬───────────────────┘
        │  定时/手动触发                    │  按需调用
        ▼                                  ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────────────┐
│ Trigger Agent│─▶│Screener Agent │─▶│   Review Agent        │
│  触发检测    │  │  精选股票      │  │   收盘复盘            │
│  09:15 触发  │  │  6维评分Top N  │  │   15:35 触发          │
└──────────────┘  └───────────────┘  └──────────────────────┘

                                     ┌──────────────────────┐
                                     │ Stock Analyst Agent   │
                                     │  个股多维度深度分析   │
                                     │  按需手动触发         │
                                     └──────────────────────┘
                                               │
                                               ▼
                                     ┌──────────────────────┐
                                     │   Web Dashboard       │
                                     │   http://localhost:8888│
                                     └──────────────────────┘
```

**Agent 说明**

| Agent | 触发方式 | 职责 |
|---|---|---|
| Trigger Agent | 09:15 定时 / 手动 | 读取新闻缓存，识别政策/涨价/转折事件，判断是否触发选股 |
| Screener Agent | Trigger 后自动 | 对候选股票从 6 维度评分（满分 18 分），输出 Top N |
| Review Agent | 15:35 定时 / 手动 | 结合收盘行情进行复盘，生成 Markdown 报告 |
| Stock Analyst Agent | 手动按需 | 对指定股票进行 6 维独立评分 + LLM 深度报告 |

---

## 功能特性

### 新闻采集
- **分级采集**：HIGH / MEDIUM / LOW 三优先级，各自配置采集时段和间隔
- **跨日去重**：相同新闻跨日出现时自动标记为重复事件并记录历史
- **事件新鲜度**：超过 14 天的事件标记为低新鲜度（市场可能已 price in）
- **手动采集**：Web Dashboard 支持一键触发新闻采集，实时查看进度

### 精选股票
- **六维评分体系**（D1–D6，每维 0–3 分，满分 18 分）：
  - D1 行业龙头地位 · D2 受益程度 · D3 股东结构
  - D4 上涨趋势 · D5 技术突破 · D6 估值合理
- **动态 Top N**：根据提示词中的 Top N 自动分批处理，不限于固定条数
- **初筛新闻配置**：可在系统配置中选择参与初筛的渠道和时间范围（当天 / 回溯 N 小时）

### 个股分析
- **按需输入股票代码**，最多同时分析 5 只
- **5 类原始数据自动采集**：基本信息、均线趋势、量价信号、股东结构、财务指标
- **消息面支持**：
  - 优先从本地 DB 按关键词检索近期新闻
  - 本地不足 3 条时自动调用东方财富个股新闻接口（`stock_news_em`）补充，并回写 DB
- **个股分析新闻配置**：可独立配置参与分析的渠道和时间范围
- **LLM 综合评分 + Markdown 报告**：六维打分 + 推荐理由 + 风险提示 + 详细分析
- **历史记录**：支持日期筛选和分页查看历史分析结果

### Web Dashboard
- **移动端适配**：汉堡菜单 + 抽屉式导航，支持手机访问
- **Prompt 版本管理**：在线编辑提示词、保存版本、一键回滚
- **多模型支持**：`config/models.json` 配置，各 Agent 独立指定 provider 和模型
- **系统配置**：精选股票和个股分析的新闻渠道、时间范围均可在 Web UI 中配置

---

## 目录结构

```
stock-agent-v3/
├── main.py                    # 主入口（命令行 / 定时任务）
├── web_server.py              # Web Dashboard（FastAPI）
├── requirements.txt
├── .env                       # 环境变量（API Keys，需自行创建）
├── .env.example
│
├── agents/
│   ├── trigger_agent.py       # Agent 1：触发事件检测
│   ├── screener_agent.py      # Agent 2：精选股票评分
│   ├── review_agent.py        # Agent 3：收盘复盘
│   └── stock_analyst_agent.py # Agent 4：个股多维度分析（新）
│
├── config/
│   ├── models.json            # LLM 模型配置（provider/model-id）
│   └── settings.py            # 全局配置（读取 .env）
│
├── graph/
│   └── workflow.py            # LangGraph 工作流编排
│
├── tools/
│   ├── db.py                  # SQLite 统一存储管理
│   ├── news_collector.py      # 新闻采集 + 缓存管理
│   ├── news_tools.py          # 各来源新闻接口
│   ├── stock_data.py          # 股票行情 + 财务 + 个股新闻（stock_news_em）
│   ├── technical_tools.py     # 技术指标（K线双源：EM + 腾讯备用）
│   ├── shareholder_tools.py   # 股东结构分析
│   ├── market_screener.py     # 市场行情筛选
│   ├── price_monitor.py       # 期货涨价监控
│   ├── event_tracker.py       # 事件新鲜度追踪
│   └── proxy_patch.py         # Clash TUN 模式代理兼容补丁
│
├── web/
│   └── index.html             # Dashboard 前端（单文件 SPA，移动端适配）
│
├── data/db/
│   └── stock_agent.db         # SQLite 数据库（运行时自动创建）
│
├── logs/                      # 日志文件（YYYY-MM-DD.log）
│
└── docker/
    ├── Dockerfile
    └── docker-compose.yaml
```

---

## 快速开始

### 环境要求

- Python 3.10+

### 本地运行

```bash
# 1. 克隆代码
git clone <repo-url>
cd stock-agent-v3

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM API Key

# 4. 初始化数据库
python main.py --init-db

# 5. 启动 Web Dashboard
python web_server.py
# 访问 http://localhost:8888

# 6. 启动定时任务（另开终端）
python main.py --schedule
```

---

## 配置说明

### .env — 环境变量

```bash
# ── LLM API Keys（key 名称与 config/models.json 对应）──
DEEPSEEK_API_KEY=sk-xxxx
# ANTHROPIC_API_KEY=sk-ant-api03-xxxx
# GOOGLE_API_KEY=AIzaxxxx

# ── 数据库路径（默认无需修改）──
AGENT_DB_PATH=data/db/stock_agent.db

# ── 新闻采集：各优先级采集间隔（分钟）──
COLLECT_INTERVAL_HIGH=30       # 财联社 / 东方财富 / 同花顺
COLLECT_INTERVAL_MEDIUM=60     # 新浪财经 / 财联社电报
COLLECT_INTERVAL_LOW=120       # 国家发改委 / 财新

# ── 新闻采集：各优先级活跃时段（支持多段，如 "6-9,15-18"）──
COLLECT_HIGH_HOURS=6-15
COLLECT_MEDIUM_HOURS=6-18
COLLECT_LOW_HOURS=6-9,15-18

# ── APScheduler 定时配置 ──
COLLECT_SCHEDULE_HOURS=6-17    # 调度器触发时段
COLLECT_SCHEDULE_INTERVAL=30   # 调度器触发间隔（分钟）

# ── 日志 ──
LOG_LEVEL=INFO                 # DEBUG / INFO / WARNING
LOG_FILE_ENABLED=true          # 是否写文件日志（logs/YYYY-MM-DD.log）
```

### config/models.json — 模型配置

每个 Agent 可独立配置模型，格式为 `provider/model-id`：

```json
{
  "providers": {
    "deepseek":  { "base_url": "https://api.deepseek.com/v1",                           "api_key_env": "DEEPSEEK_API_KEY" },
    "anthropic": { "base_url": "https://api.anthropic.com/v1",                          "api_key_env": "ANTHROPIC_API_KEY" },
    "google":    { "base_url": "https://generativelanguage.googleapis.com/v1beta/openai","api_key_env": "GOOGLE_API_KEY" }
  },
  "defaults": { "temperature": 0.1, "max_tokens": 16000 },
  "agents": {
    "trigger":  { "model": "deepseek/deepseek-chat" },
    "screener": { "model": "deepseek/deepseek-chat" },
    "review":   { "model": "deepseek/deepseek-chat" }
  }
}
```

| Provider | 示例 model-id |
|---|---|
| DeepSeek | `deepseek/deepseek-chat` |
| Anthropic | `anthropic/claude-sonnet-4-6` |
| Google | `google/gemini-2.0-flash` |

> 修改 `models.json` 后无需重启，下次运行时自动生效。

---

## 运行方式

### 命令行

```bash
python main.py --init-db        # 初始化数据库（首次使用）
python main.py --collect        # 手动触发一次新闻采集
python main.py --trigger-only   # 仅触发事件检测
python main.py --event          # 触发检测 + 精选股票（完整选股）
python main.py --review         # 仅收盘复盘
python main.py --schedule       # 启动定时任务（生产模式）
```

### Web Dashboard

```bash
python web_server.py
# 访问 http://localhost:8888
```

---

## Web Dashboard

访问 `http://localhost:8888`，各页面功能：

| 页面 | 功能 |
|---|---|
| 控制台 | 今日数据概览（触发事件数、精选数、新闻数、复盘状态） |
| 精选股票 | 按日期/批次查看 Top N 精选结果及 D1–D6 评分详情；内置「▶ 触发分析」按钮 |
| 触发事件 | 查看每日触发的宏观事件列表（含新鲜度判断） |
| 新闻动态 | 按日期/来源/时段查看采集的新闻；内置「📥 采集新闻」按钮实时触发采集 |
| 市场复盘 | 收盘复盘 Markdown 报告 |
| 个股分析 | 输入股票代码按需分析，查看多维评分 + AI 报告；历史记录支持日期筛选和分页 |
| 事件去重 | 跨日重复新闻历史、出现次数、来源统计 |
| 提示词管理 | 在线编辑 Agent 提示词，保存版本，一键回滚 |
| 运行日志 | 每次运行的状态、耗时、使用模型 |
| 系统配置 | 初筛新闻配置、个股分析新闻配置、控制台显示条数等 |

> **移动端**：宽度 < 768px 时自动切换为汉堡菜单 + 抽屉导航。

---

## 个股分析

在 Web Dashboard「个股分析」页面输入 1–5 个股票代码（逗号分隔），点击「开始分析」即可。

### 数据采集维度

| 维度 | 数据来源 | 说明 |
|---|---|---|
| D1 行业龙头地位 | `get_stock_basic_info()` | 市值、行业、换手率等 |
| D2 近期业务催化 | 新闻 + 财务趋势 | LLM 综合判断 |
| D3 股东结构稳定 | `get_top_shareholders()` | 前10大流通股东、持仓变化，程序预计算得分 |
| D4 中长期趋势 | `calc_long_term_trend()` | MA60/MA120/MA250 均线排列，腾讯 K 线备源 |
| D5 技术突破信号 | `calc_volume_breakthrough()` | 近3日量比、换手率放大，程序预计算得分 |
| D6 估值合理性 | `get_financial_indicators()` | ROE、净利率、毛利率、资产负债率近4期 |

### 新闻消息面（D2 核心依据）

采用两阶段策略：

1. **本地 DB 优先**：按配置的渠道和时间范围，用股票名称 + 代码关键词检索本地新闻库
2. **EM 接口补充**：本地新闻 < 3 条时，自动调用东方财富 `stock_news_em` 接口拉取该股票专属新闻，并回写 DB 供后续复用

### K 线数据双源

| 优先级 | 接口 | 备注 |
|---|---|---|
| 优先 | `ak.stock_zh_a_hist`（东方财富） | 字段完整，含换手率；部分网络环境可能受代理影响 |
| 备用 | `ak.stock_zh_a_hist_tx`（腾讯） | 稳定可用；无成交量字段，以成交额/收盘价近似推算 |

### API

```bash
# 触发分析（同步，约 10–30 秒/只）
POST /api/analyze-stocks
{"codes": ["000001", "600036"]}

# 查看历史列表（支持日期筛选和分页）
GET /api/analyses?date=2026-03-21&limit=20&offset=0

# 查看某次分析详情
GET /api/analyses/{id}
```

---

## 系统配置项

以下配置可在 Web Dashboard「系统配置」页面直接修改，无需重启：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `dashboard_picks_limit` | 10 | 控制台「今日精选」最多显示几条 |
| `screener_news_sources` | 空（全部） | 触发初筛时参与分析的新闻渠道，逗号分隔 |
| `screener_news_lookback_hours` | 0 | 初筛新闻时间范围：0=当天0点起；24=过去24小时 |
| `analyst_news_sources` | 空（全部） | 个股分析时检索新闻的渠道，逗号分隔 |
| `analyst_news_lookback_hours` | 72 | 个股分析新闻回溯小时数，默认近3天 |

**可选渠道**：财联社、东方财富、同花顺、新浪财经、财联社电报、国家发改委、财新

---

## 数据库说明

数据库位于 `data/db/stock_agent.db`（SQLite），自动建表，主要表：

| 表名 | 说明 |
|---|---|
| `news_items` | 采集的新闻，按 `news_hash + collect_date` 去重 |
| `news_source_timestamps` | 各来源最后采集时间，用于间隔控制 |
| `event_history` | 事件去重历史，记录首次/最近出现时间和出现次数 |
| `run_logs` | 每次 Agent 运行记录（状态、耗时、使用模型） |
| `screener_stocks` | 精选股票结果，含 D1–D6 评分详情 |
| `review_reports` | 收盘复盘报告（Markdown） |
| `prompts` | Agent 提示词版本库，支持多版本管理 |
| `stock_analysis` | 个股分析结果（含原始数据 + 评分 + 报告 JSON） |
| `system_config` | 系统参数配置（可通过 Web UI 修改） |

---

## 模型切换

无需改代码，只需编辑 `config/models.json`：

```bash
# 切换到 Anthropic Claude
# 1. .env 中设置 ANTHROPIC_API_KEY=sk-ant-api03-xxxx
# 2. models.json 修改：
#    "screener": { "model": "anthropic/claude-sonnet-4-6" }

# 切换到 Google Gemini
# 1. .env 中设置 GOOGLE_API_KEY=AIzaxxxx
# 2. models.json 修改：
#    "trigger": { "model": "google/gemini-2.0-flash" }
```

系统根据 provider 自动选择 SDK：
- `anthropic` → `ChatAnthropic`
- 其他 → `ChatOpenAI`（OpenAI 兼容接口）

---

## Docker 部署

### 启动服务

```bash
cd docker/
docker compose up -d --build

# 查看状态
docker compose ps

# 实时日志
docker compose logs -f
```

### 服务说明

| 服务 | 职责 | 重启策略 |
|---|---|---|
| `web` | Web Dashboard（:8888） | unless-stopped |
| `agent` | 定时任务（采集 + 触发 + 复盘） | unless-stopped，依赖 web 健康后启动 |

两个服务共享同一 SQLite 数据库（挂载 `./data` 卷）。

### 常用命令

```bash
docker compose down                              # 停止所有服务
docker compose restart web                       # 重启 Dashboard
docker compose up -d --build                     # 更新代码后重建
docker compose exec agent python main.py --collect   # 手动采集新闻
docker compose exec agent python main.py --event     # 手动触发选股
docker compose exec web bash                     # 进入容器调试
```

### 挂载卷

| 宿主机路径 | 容器路径 | 说明 |
|---|---|---|
| `../.env` | `/app/.env` | API Keys（只读） |
| `../config/models.json` | `/app/config/models.json` | 模型配置（只读） |
| `../data/` | `/app/data/` | SQLite DB 持久化 |
| `../logs/` | `/app/logs/` | 日志持久化 |

---

## 日志说明

日志文件路径：`logs/YYYY-MM-DD.log`（每天一个文件）

通过 `.env` 控制：

```bash
LOG_LEVEL=INFO          # 控制台级别：DEBUG / INFO / WARNING
LOG_FILE_ENABLED=true   # 文件日志开关（文件固定写入 DEBUG 级别）
```

**个股分析日志级别**

| 级别 | 内容 |
|---|---|
| INFO | 每维度采集摘要（MA值、量比、D3得分）、新闻条数来源、LLM 评分结果、推荐/风险 |
| DEBUG | 各维度完整 JSON 数据、LLM 完整输入、LLM 原始输出、完整 Markdown 报告 |

```bash
# 查看今日个股分析日志
grep "stock_analyst_agent" logs/$(date +%Y-%m-%d).log

# 查看 DEBUG 详情（需先设置 LOG_LEVEL=DEBUG）
tail -f logs/$(date +%Y-%m-%d).log | grep -A5 "分析完成"
```

cp data/db/stock_agent.db data/db/stock_agent.db.bak_$(date +%Y%m%d)