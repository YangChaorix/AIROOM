# Stock Agent v4 — 产品需求文档（PRD）

> ⚠️ **本文档是 v4 长期蓝图，不是 MVP 实施指南。**
> **如果你正在做周末 MVP，请以 `../../stock-agent-mvp/docs/MVP_PRD.md` 为唯一依据。**
> 本文中 Phase 1–5 的「替换 / 升级」语言仅对 v4 有意义，MVP 是全新项目，不复用 v3 代码，也不受本文档的 DB 表设计、前端页面、Critic 模块约束。

> 版本：v1.0
> 创建时间：2026-04-12
> 定位：AI 散户选股助理，支持用户自定义条件 + 持续学习

---

## 目录

1. [产品概述](#1-产品概述)
2. [用户与需求](#2-用户与需求)
3. [核心设计原则](#3-核心设计原则)
4. [系统架构](#4-系统架构)
5. [各模块详细设计](#5-各模块详细设计)
   - 5.1 触发预处理 / 5.2 Supervisor / 5.3 Research Agent / 5.4 Skills
   - 5.5 Screener Agent / 5.6 Skeptic Agent / 5.7 Data Recorder / 5.8 Critic Agent
   - 5.9 个股分析与股票追踪
6. [数据设计](#6-数据设计)
7. [前端页面详细设计](#7-前端页面详细设计)
   - 7.1 页面总览 / 7.2 今日信息 / 7.3 今日推荐 / 7.4 策略配置 / 7.5 个股分析与追踪
8. [技术选型](#8-技术选型)
9. [模型选型框架](#9-模型选型框架)
10. [版本规划](#10-版本规划)
11. [验收标准](#11-验收标准)

---

## 1. 产品概述

### 1.1 产品定位

一款面向有自己选股逻辑的散户投资者的 AI 助理工具。用户把自己的选股条件输入系统，系统每天自动扫描市场信息、按用户条件评估候选股票、输出带有完整推理链和风险提示的推荐结果，并在长期运行中持续学习、优化每个条件的权重。

### 1.2 核心价值主张

- **你的条件，不是我们的代码**：选股逻辑存在用户自己的档案里，可增删改，可配权重
- **每个推荐都能解释**：每只股票附完整推理链（为什么推荐）+ 质疑意见（可能为什么错）
- **系统会随你一起进化**：根据用户自己的历史准确率，自动优化各条件的参考权重

### 1.3 与现有产品的差异

市面上的金融 Agent 产品（TradingAgents、FinRobot、OpenBB AI）均存在以下局限：
- 选股逻辑是固定的通用框架，无法个性化
- 没有从"这个用户"的历史表现中持续学习的机制
- 面向机构或开发者，不适合散户直接使用

本产品同时满足三点：**领域专属**（A 股选股）× **用户条件可编辑**× **从用户自身历史学习**。

---

## 2. 用户与需求

### 2.1 核心用户画像

**主要用户：有经验的散户**
- 代表人物：15年+ A 股经验的个人投资者
- 有一套经过实战验证的选股逻辑，但执行靠人工，费时费力
- 能理解"条件满足度"这类概念，但不是技术用户，不会写代码
- 关心推荐的依据，不接受黑箱输出

**潜在扩展用户：其他风格的散户**
- 技术派（偏重量能、K线）
- 价值派（偏重估值、股东结构）
- 每类用户可以配置完全不同的条件集，系统用同一套框架运行

### 2.2 用户故事（核心场景）

**场景 A：每天早上看今日推荐**
> "今天储能政策出来了，系统推荐了三只，每只都告诉我为什么推荐，以及可能的风险。我对宁德时代有顾虑，看到 Skeptic 说估值偏高，正好和我的判断一致。"

**场景 B：当 AI 还不完善时，自己读新闻**
> "我就想看看今天财联社和政府网站发了什么，系统帮我把几十个来源聚合在一起，我自己读，比一个一个网站去找省事多了。"

**场景 C：调整自己的条件**
> "我发现我加的'股东结构'这个条件最近老是判断出错，我想降低它的权重，或者重新写一下判断标准。"

**场景 D：查历史（Phase 2）**
> "上次储能政策出来，我们推了什么？最后涨了吗？"

---

## 3. 核心设计原则

以下三条原则在所有设计决策中优先级最高，遇到冲突时不妥协。

**原则一：选股条件是用户的数据，不是系统的代码**
父亲的 7 个条件、另一个用户的 5 个条件，全部存在数据库里，可增删改，可独立配权重。条件不写死在 Prompt 里——Prompt 是读取条件数据的模板，不是条件本身。换一个用户 ID，导入他的条件集，系统照样跑，不需要改代码。

**原则二：改进是可解释的数字，不是新的文字**
Critic Agent 的输出是"C3 条件近期准确率 38%，建议将权重从 0.10 降至 0.07"，而不是"帮你生成了一段更好的提示词"。改进过程是数字，可以回溯、可以对比、可以质疑。

**原则三：用户随时可以介入，系统随时可以解释**
每个推荐必须附带推理链和质疑意见。用户可以拒绝 Critic 的权重建议。写操作（修改条件、调整权重）需要用户明确确认（Human-in-the-Loop）。

---

## 4. 系统架构

### 4.0 核心框架：三层固定结构

系统预设三个固定的分析层，不可增减。这是工具的基础解决方案，用户只能在层内自定义条件，不能新增第四层。

| 层 | 回答的问题 | 系统预设行为 | 用户可自定义 |
|---|---|---|---|
| **触发层（Trigger Layer）** | 今天有没有值得关注的市场信号？ | Trigger Scanner 每日扫描，二元判断（有/无触发），无权重 | 添加/删除触发条件，设置关键词和数据源 |
| **评估层（Screener Layer）** | 在这个信号下，哪只股票最值得关注？ | Screener Agent 加权打分，决定推荐等级 | 添加/删除评估条件，设置权重和判断标准 |
| **入场层（Entry Layer）** | 现在是合适的入场时机吗？ | Entry Gate 在推荐输出前做最终检查 | 添加/删除入场条件，设置是否为硬性门槛 |

**父亲7个条件的层归属**：

| 条件 | 归属层 | 说明 |
|------|------|------|
| C1 政策支持 | 触发层 | 政策落地是"今天分析"的触发信号 |
| C6 转折事件 | 触发层 | 催化剂出现是"今天分析"的触发信号 |
| C4 涨价信号 | **拆分为两条** | C4-T（触发层）：市场出现涨价；C4-E（评估层）：该公司受益于涨价 |
| C2 行业龙头 | 评估层 | 筛选候选股票时评估 |
| C3 股东结构 | 评估层 | 筛选候选股票时评估 |
| C5 中期趋势 | 评估层 | 筛选候选股票时评估 |
| C7 技术突破 | 入场层 | 最后确认入场时机 |

> C4 拆分的原因：市场涨价（触发层）和该公司产品受益于涨价（评估层）是两个不同粒度的判断——前者是行业信号，后者是个股验证。拆分后，两者各司其职，逻辑更清晰。

### 4.1 四条独立运行线路

```
线路一：每天早上自动运行（主流程）
  08:00 Trigger Scanner 晨扫
  08:30 Supervisor 启动 → Research → Screener → Skeptic → 推送结果

线路二：每天收盘后自动运行（学习流程）
  16:00 Trigger Scanner 盘后扫（技术面数据）
  18:00 Critic Agent → 记录当日推荐结果 → 积累到阈值后生成分析报告

线路三：用户随时发起（个股分析流程）
  用户指定一只股票 → 同一个 Supervisor 以"分析特定股票"为目标启动
  → Research Agent 按用户条件全量调研该股票
  → Screener 评分 + Skeptic 质疑
  → 输出完整分析报告（不受 Trigger 限制，随时可发起）

线路四：用户随时发起（交互流程，Phase 2）
  Chat Agent → 查历史 / 问分析 / 调整条件
```

**个股分析与主流程的区别**：
- 主流程由 Trigger 信号驱动，Supervisor 的起点是"哪些行业今天有触发信号"
- 个股分析由用户指定股票，Supervisor 的起点是"用我的条件分析这只股票"
- 两者使用相同的 Supervisor 循环 + 相同的子 Agent 池，复用所有基础设施；差异只在初始指令

四条线路共享同一个数据基础：**User Strategy Profile**（用户策略档案）。Critic 更新它，Supervisor 读取它，用户通过策略配置页修改它。

### 4.2 架构全图

系统由三条独立流程构成，共享同一个数据层。

```
╔══════════════════════════════════════════════════════════════════╗
║  【主流程】每日 08:30 定时触发，目标 09:15 前完成                 ║
║                                                                  ║
║  [Trigger Scanner] ──写入──→ news_items(DB)                     ║
║         ↓                                                        ║
║  [Pre-processor]  轻量模型，从 DB 新闻里提炼结构化触发摘要         ║
║         ↓  trigger_summary（行业/类型/强度/标题）                 ║
║                                                                  ║
║  ┌───────────────────────────────────────────────────────────┐  ║
║  │                   Supervisor LLM                          │  ║
║  │                                                           │  ║
║  │  读取：trigger_summary + UserProfile（条件权重/准确率）    │  ║
║  │  决策：dispatch_research / dispatch_screener /            │  ║
║  │         dispatch_skeptic / finalize                       │  ║
║  │                                                           │  ║
║  │  ★ 每次子 Agent 完成后，结果返回此处，Supervisor 重新决策  │  ║
║  │  ★ 不存在固定的 Agent 执行顺序，完全由 Supervisor 控制    │  ║
║  │  ★ 最多循环 3 次（第3次强制 finalize）                    │  ║
║  └──────────────────┬────────────────────────────────────────┘  ║
║                     │ 每次只调用一个 Agent，拿到结果后返回        ║
║                     ↓                                            ║
║         ┌───────────────────────────────┐                       ║
║         │       子 Agent 池（按需调用）   │                       ║
║         │                               │                       ║
║         │  [Research Agent]  ReAct 模式 │                       ║
║         │   DB优先查已有新闻             │                       ║
║         │   + AkShare金融结构化数据      │                       ║
║         │   → 返回 research_report      │                       ║
║         │                               │                       ║
║         │  [Screener Agent]  条件评分   │                       ║
║         │   读 UserProfile 当前版本条件  │                       ║
║         │   → 返回 scored_stocks        │                       ║
║         │                               │                       ║
║         │  [Skeptic Agent]   对抗验证   │                       ║
║         │   TOP5 逻辑风险直接标注        │                       ║
║         │   数据盲区上报 Supervisor 决策 │                       ║
║         │   → 返回 skeptic_findings     │                       ║
║         └───────────────────────────────┘                       ║
║                     ↓  Supervisor 输出 finalize                  ║
║  [推荐输出] ──写入──→ screener_stocks(DB) ──→ 推送用户            ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║  【Critic 异步流程】独立运行，不阻塞主流程                        ║
║                                                                  ║
║  [Data Recorder]  每日 16:30，纯脚本，无 LLM                    ║
║   · 记录当日推荐 + 推荐时收盘价 + 沪深300点位                    ║
║   · 检查历史推荐是否到达短期/长期评估节点                         ║
║   · 到期则计算超额收益 → 写入 critic_evaluations(DB)             ║
║         ↓                                                        ║
║         ↓  触发条件（满足任一即可）：                             ║
║         ↓  A. 里程碑：累积 N 条评估完成（可配置，默认10条）       ║
║         ↓  B. 用户手动点击"立即分析"                             ║
║         ↓                                                        ║
║  [Critic Agent]  LLM 分析，输出两份报告：                        ║
║   · 股票报告：推荐整体胜率、已评估推荐的超额收益分布               ║
║   · 条件报告：各条件有效性（按 last_modified_date 分段计算）       ║
║   · 权重调整建议（不自动执行）                                    ║
║         ↓                                                        ║
║  [HITL 确认]  用户在策略配置页接受/忽略建议                       ║
║         ↓ 确认后                                                  ║
║  更新 UserProfile（条件权重 + last_updated）                     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║  【共享数据层】                                                   ║
║                                                                  ║
║  UserProfile(DB)                                                 ║
║    ← Critic Agent 更新权重                                       ║
║    ← Supervisor 读取条件准确率                                    ║
║    ← Screener 读取当前版本条件集                                  ║
║    ← 用户在策略配置页修改（每次修改生成新版本快照）                ║
║                                                                  ║
║  SQLite(DB)：news_items / screener_stocks /                      ║
║              critic_evaluations / triggers / user_profiles 等    ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║  【Chat Agent】Phase 2                                           ║
║  用户 ←→ Chat Agent ←→ DB + UserProfile                        ║
║          只读查询直接返回；写操作触发 HITL 确认流程               ║
╚══════════════════════════════════════════════════════════════════╝
```

**架构关键说明**（供技术实现参考）：
- Supervisor 使用 LangGraph 的循环 StateGraph 实现，每次子 Agent 完成后通过条件边（conditional edge）回到 Supervisor 节点，由 Supervisor 决定下一步路由
- 子 Agent 池不是并行执行，而是 Supervisor 每次只 dispatch 一个，等待返回后再决策
- Data Recorder 和 Critic Agent 是两个独立节点，不在主流程 StateGraph 内，通过定时任务或手动触发独立运行
- Chat Agent（Phase 2）是另一个完全独立的 StateGraph，不与主流程共享状态

### 4.3 Trigger Scanner 定时策略

**定时扫描计划**：

| 时间 | 回溯窗口 | 扫描内容 | 触发行为 |
|------|---------|---------|---------|
| 08:00 | 过去 24 小时 | 隔夜政策/新闻（政府官网、财联社、东方财富） | 发现新触发信号 → 08:30 启动主流程 |
| 12:00 | 过去 4 小时（增量） | 上午新增新闻 | 补充入库；若出现颠覆性新信息则追加提醒 |
| 16:00 | 过去 4 小时（增量） | 下午新闻 + 技术面数据（需完整收盘数据） | 补充当日技术面；供 Critic 盘后使用 |

**回溯窗口说明**：
- 08:00 扫描使用 24 小时窗口（涵盖前一天收盘后到今天开盘前的所有内容）
- 12:00 / 16:00 扫描使用 4 小时增量窗口（只取上次扫描后新增的内容，避免重复入库）
- 每条新闻按 `(source, url)` 或 `(source, title_hash)` 做唯一性校验，不重复写入 DB
- 特殊情况：如需手动触发补扫，支持指定任意时间窗口（12h / 24h / 48h），对应原 v3 的配置参数

**主推荐时序**：每日只产出一次主推荐（09:15 前完成），不随后续扫描滚动更新。后续 12:00 / 16:00 扫描仅补充数据，不重新启动完整主流程。

---

## 5. 各模块详细设计

### 5.1 触发预处理（轻量）

**职责**：从原始新闻里提取结构化摘要，供 Supervisor 使用。

**两个组件**：

**① Trigger Scanner（纯脚本）**：负责抓取原始数据并写入 DB，不做理解。每条新闻按 `(source, url_hash)` 去重，避免重复入库。

**② 触发预处理模型（轻量 LLM）**：每次扫描完成后，对本次新增的新闻条目做结构化提取，输出触发摘要列表。

**触发预处理 Prompt**：

```
你是一个金融新闻分类助手。请分析以下新闻标题列表，
提取其中与股市选股相关的触发信号。

对每条有效触发信号，输出以下结构化字段：
- industry（受影响的行业/板块）
- type（信号类型：政策 / 价格 / 公司事件 / 宏观数据）
- strength（触发强度：高 / 中 / 低）
  高：政策明确落地、重大价格突破、龙头公司关键事件
  中：政策草案征求意见、价格持续上涨但未突破前高
  低：行业提及但无实质内容、泛泛利好
- headline（保留原始标题）
- news_id（对应数据库ID）

忽略：财经八卦、宏观政治、与A股无直接关联的国际新闻。

新闻列表：{news_titles_with_ids}

以 JSON 数组格式输出，不需要解释。
```

**Supervisor 收到的触发摘要示例**：
```json
[
  {"industry": "储能", "type": "政策", "strength": "高",
   "headline": "国家能源局下发储能补贴细则", "news_id": 1042},
  {"industry": "光伏", "type": "价格", "strength": "中",
   "headline": "硅料价格连续3周上涨", "news_id": 1043}
]
```

Supervisor 读摘要做调度决策；需要深挖时，通过 `get_news_detail(news_id)` 工具按需读原文。

### 5.2 Supervisor LLM

**职责**：循环调度决策节点，根据触发摘要 + 用户档案制定研究计划，并在每轮子 Agent 完成后判断是继续、补查还是结束。

**"最多3轮"的精确定义**：

```
第1轮（全量研究轮）：
  Supervisor 制定研究计划
  → Research Agent 全面调研候选股票
  → Screener Agent 对所有候选股票评分
  → Skeptic Agent 对 TOP5 进行质疑
  → Supervisor 评估 Skeptic 结果

第2轮（补查轮，条件触发）：
  触发条件：Skeptic 发现了"数据盲区"类问题，
            且该股票是 TOP3 候选，且 Supervisor 判断该盲区影响关键条件
  → Research Agent 针对性补查（只查盲区数据，不重跑全量）
  → Screener Agent 仅更新受影响的股票得分
  → Supervisor 做最终判断

第3轮（强制结束）：
  无论是否还有盲区，强制输出当前结果
  在推荐里对仍有数据盲区的股票标注"数据不完整，建议自行核查"
  不再调用任何子 Agent
```

**注意**：Skeptic 的"逻辑风险"类质疑（如"估值偏高"、"政策落地有时滞"）**不触发第2轮**，直接写入风险注释输出。只有"数据盲区"类才可能触发补查。

**Supervisor 系统提示词**：

```
你是一个专业的选股研究调度员。你的工作是根据今日市场触发信号和用户的
选股档案，制定研究计划，调度 Research Agent 和 Screener Agent 完成分析，
并最终输出高质量的选股推荐。

【调度规则】
1. 你会被多次激活：每次子 Agent 完成任务后，你重新评估状态并决定下一步。
2. 最多调度3轮（见轮次定义），第3轮强制输出，不再调用任何 Agent。
3. 当前是第 {current_round} 轮（共最多3轮）。

【研究计划制定规则】
- 根据触发强度决定研究深度：强触发→全量调研；中触发→重点调研；弱触发→仅基础信息
- 根据各条件近期准确率调整研究重点：
  准确率 < 40% 的条件，可在研究计划里降低该条件的调研优先级，
  但不能完全忽略（需在结果里标注"低准确率条件"）
- 如历史上有同类触发（历史胜率有数据时），将其作为参考背景提供给 Research Agent

【第2轮触发判断标准】
仅当以下三个条件同时满足时，才启动第2轮补查：
  ① Skeptic 发现了"数据盲区"（不是"逻辑风险"）
  ② 涉及的股票在当前 TOP3 推荐中
  ③ 该盲区直接影响某个高权重条件（权重 > 0.15）的评分

【输出格式】
每次激活时，输出 JSON 格式的调度指令：
{
  "action": "dispatch_research" | "dispatch_screener" | "dispatch_skeptic" | "finalize",
  "instructions": "...",  // 给下一个 Agent 的具体研究指令
  "round": 1 | 2 | 3,
  "notes": "..."          // 给最终输出的背景说明
}

【当前上下文】
触发信号：{trigger_summary}
用户条件与近期准确率：{conditions_with_accuracy}
历史同类触发胜率：{historical_win_rate}（样本数：{sample_count}，不足5条时忽略）
当前已完成的步骤：{completed_steps_summary}
```

### 5.3 Research Agent（ReAct 模式）

**职责**：按 Supervisor 的研究计划，通过 ReAct 循环（思考→调工具→观察→再思考）收集数据，输出结构化研究报告。

**数据来源优先级（"DB优先"策略）**：

Research Agent 的工具箱包含两类工具：

| 类型 | 说明 | 何时使用 |
|------|------|---------|
| **DB 查询工具**（复用已有数据） | 查 Trigger Scanner 已存入的新闻（`search_news_from_db`） | 优先使用，避免重复抓取 |
| **外部数据工具**（实时获取） | AkShare、Serper、政府网站爬虫等 | DB 里没有的数据（股价、技术指标、财务数据）或需要最新实时数据时 |

**重要**：新闻类内容优先从 DB 读（Trigger Scanner 已经抓了），不重复调外部 API；股价、量能等结构化金融数据直接调 AkShare（DB里没存）。

**完整工具列表**：

| 工具 | 类型 | 数据内容 |
|------|------|---------|
| `search_news_from_db(keywords, hours=48)` | DB查询 | 从已入库新闻里检索，支持关键词+时间窗口 |
| `get_news_detail(news_id)` | DB查询 | 获取某条新闻原文 |
| `akshare_industry_leaders(industry)` | 外部 | 行业龙头企业名单 |
| `stock_financial_data(code)` | 外部 | 营收、净利润、PE估值 |
| `stock_holder_structure(code)` | 外部 | 前十大股东占比、类型 |
| `stock_technical_indicators(code)` | 外部 | 量能、MACD、均线、成交额 |
| `northbound_capital_flow(code)` | 外部 | 北向资金近期净流入 |
| `price_trend_data(product)` | 外部 | 行业/产品近期价格走势 |
| `serper_news_search(query)` | 外部 | 实时新闻搜索（DB没有时补充） |
| `govt_policy_detail(url)` | 外部 | 政府官网政策原文 |
| `search_similar_history(text)` | 本地向量库 | 语义相似的历史触发事件（Phase 4 加入，需 sqlite-vec） |

**Research Agent 系统提示词**：

```
你是一个专业的 A 股市场数据研究员，使用 ReAct 模式工作。
你会收到 Supervisor 的研究任务，需要通过工具调用收集数据，
为 Screener Agent 准备完整的股票分析材料。

【数据收集优先级】
1. 新闻/政策类数据：优先调用 search_news_from_db 从已有库里查，
   找到了就不再重复调外部接口。DB 查不到再用 serper_news_search 补充。
2. 金融结构化数据（股价、财务、技术面）：直接调 AkShare 工具，
   这类数据 DB 里没有存储。
3. 政策原文：先搜 DB，没有则爬政府官网。

【ReAct 工作规范】
- 每次 Thought 说清楚：为什么需要这个数据，预期用哪个工具
- 发现某个数据工具返回空或报错时，换一种方式尝试一次，
  仍然失败则记录到 data_gaps，不要用估计值替代
- 不对数据做价值判断，只收集和如实整理数据
- 发现 Supervisor 未提到但明显重要的数据点，可以主动补充

【data_gaps 规范】
data_gaps 字段必须明确列出每只股票中未能获取的数据项：
✗ 错误写法："部分数据不可用"
✓ 正确写法：["大股东近6个月增减持记录", "Q4分红政策"]

【输出格式】
严格按照 ResearchReport Pydantic 模型输出，不要输出额外文字。

研究任务：{research_instructions}
```

**ReAct 执行示例**：
```
Thought: 需要了解储能行业相关新闻，先查 DB 里有没有
Action: search_news_from_db(keywords="储能 补贴", hours=24)
Observation: [找到3条，含补贴细则原文链接]

Thought: DB 里有新闻了，不需要再搜外部。接下来找行业龙头
Action: akshare_industry_leaders(industry="储能")
Observation: [宁德时代(002459), 阳光电源(300274), 比亚迪储能(002594)...]

Thought: 需要确认龙头企业的股东结构
Action: stock_holder_structure("002459")
Observation: {私募+个人: 58%, 低于60%门槛}
...
```

### 5.4 Skills 设计（条件调研专项封装）

**Skills 的定位**：

```
Tools（原子函数） → Skills（条件级知识包） → Research Agent（ReAct循环） → Supervisor（调度）
```

Skills 是开发者预先封装的"条件专项调研包"——每个 Skill 知道怎么查某类条件、调哪些工具、以什么顺序整理结果。Research Agent 在 ReAct 循环中调用 Skills，而不是直接裸调原始 Tools。

**为什么需要 Skills 而不是直接给 Agent 所有 Tools**：
- 工具箱有 10+ 工具，LLM 容易选错工具或遗漏步骤
- Skills 把"查龙头地位需要调哪3个工具、如何整理成可用于打分的结论"打包进去，Agent 只需说"调用 LeadershipResearchSkill"
- 降低每次调研的推理步骤和 token 消耗
- Skills 是开发者写的（不是 AI 自动生成的），质量可控

**三层 Skills 全览**：

#### 触发层 Skills（Trigger Skills）

职责：判断"今天是否出现触发信号"。由 Trigger Scanner + Pre-processor 使用，不由 Research Agent 调用。

| Skill 名称 | 监控对象 | 调用的 Tools | 输出 |
|------------|---------|------------|------|
| `PolicyMonitorSkill` | 政策落地信号 | `serper_news_search` + `govt_policy_detail` | 是否触发（true/false）+ 政策摘要 |
| `EventMonitorSkill` | 转折催化事件 | `serper_news_search` + `get_news_detail` | 是否触发 + 事件描述 |
| `PriceSignalSkill` | 行业/产品涨价 | `price_trend_data` + `serper_news_search` | 是否触发 + 近期涨幅数据 |

#### 评估层 Skills（Screener Skills）

职责：为每只候选股票收集各评估条件所需的结构化数据。由 Research Agent 在 ReAct 循环中调用。

| Skill 名称 | 对应条件 | 调用的 Tools | 输出 |
|------------|---------|------------|------|
| `LeadershipResearchSkill` | C2 行业龙头 | `akshare_industry_leaders` + `stock_financial_data` | 行业排名、市占率、营收规模 |
| `HolderStructureSkill` | C3 股东结构 | `stock_holder_structure` | 前十大股东构成、私募+个人合计占比 |
| `PriceBenefitSkill` | C4-E 产品涨价（评估） | `price_trend_data` + `stock_financial_data` | 产品涨价数据、公司受益程度、供需数据 |
| `MidTermTrendSkill` | C5 中期趋势 | `stock_financial_data` + `northbound_capital_flow` + `serper_news_search` | 机构一致预期、资金流向、行业景气度 |

#### 入场层 Skills（Entry Skills）

职责：收集入场层条件所需的技术面数据。**由 Research Agent 在 ReAct 循环中调用**（与评估层 Skills 相同），Research Agent 统一收集所有非触发层条件的数据，再由下游的 Screener Agent 和 Entry Gate 分别使用。

| Skill 名称 | 对应条件 | 调用的 Tools | 输出 |
|------------|---------|------------|------|
| `TechnicalBreakoutSkill` | C7 技术突破 | `stock_technical_indicators` | 量能突破确认、MACD状态、关键压力位突破情况 |

#### 通用调研 Fallback

当用户自定义的条件在上表中没有对应 Skill 时，Research Agent 使用 `GenericResearchSkill`：接收条件描述文本，自动选择最相关的工具进行调研。通用调研可能质量不如专项 Skill，但确保系统对任意自定义条件都能运行。

**各 Agent 与 Skills 的对应关系**（一览）：

| 调用方 | 使用的 Skills | 时机 |
|--------|-------------|------|
| Trigger Scanner / Pre-processor | Trigger Skills（PolicyMonitorSkill / EventMonitorSkill / PriceSignalSkill） | 每日晨扫，判断是否有触发信号 |
| Research Agent（ReAct 循环） | Screener Skills + Entry Skills + GenericResearchSkill（fallback） | Supervisor dispatch 后，为每只候选股票收集数据 |
| Screener Agent | 不调用 Skills，只消费 Research Agent 的输出 | 按 Research 数据对评估层条件逐条打分 |
| Entry Gate（Screener 内） | 不调用 Skills，只消费 Research Agent 的输出 | 对入场层条件做最终门槛判断 |

**Research Agent 的 Skills 调用示例**（ReAct 循环，含入场层 Skill）：

```
Thought: Supervisor 要我研究储能龙头宁德时代，先查龙头地位条件(C2)
Action: call_skill("LeadershipResearchSkill", stock_code="002459", industry="储能")
Observation: {"rank": 1, "market_share": "28%", "revenue_rank": "行业第一"}

Thought: 继续查股东结构条件(C3)
Action: call_skill("HolderStructureSkill", stock_code="002459")
Observation: {"private_equity_ratio": 0.55, "individual_ratio": 0.03, "total": 0.58}

Thought: 查产品涨价受益情况(C4-E)
Action: call_skill("PriceBenefitSkill", stock_code="002459", product="电池级碳酸锂")
Observation: {"price_trend": "+12%/近3周", "company_benefit": "主要原材料受益，产品定价能力强"}

Thought: 查中期趋势(C5)
Action: call_skill("MidTermTrendSkill", stock_code="002459")
Observation: {"analyst_consensus": "增持", "northbound_net_inflow_30d": "+3.2亿"}

Thought: 查技术面入场信号(C7，入场层条件，同样在此收集数据)
Action: call_skill("TechnicalBreakoutSkill", stock_code="002459")
Observation: {"volume_ratio": 1.8, "breakout": true, "macd": "金叉", "price_above_ma60": true}

Thought: 用户还有一个自定义条件"管理层稳定性"，没有对应 Skill
Action: call_skill("GenericResearchSkill", condition_desc="管理层是否有重要人事变动", stock_code="002459")
Observation: {"result": "近6个月无重要管理层变动记录", "source": "公司公告"}

// 所有条件数据收集完毕，Research Agent 输出完整 ResearchReport
// → Screener Agent 使用 C2/C3/C4-E/C5 数据打分
// → Entry Gate 使用 C7 数据做入场判断
```

**Skills 与 UserProfile 的关联**：

每个评估层/入场层条件在 UserProfile 中有 `research_skill` 字段，Research Agent 按此字段依次调用对应 Skill，完成所有条件的数据收集后再统一输出。若 `research_skill` 为 `null`（用户自定义条件未匹配），则使用 `GenericResearchSkill`。

---

### 5.5 Screener Agent

**职责**：按用户的条件集 + 当前权重，对每只候选股票逐条打分，输出带完整推理链的评分结果。

**评分算法**：

```
每个条件得分 = 满足度（0 / 0.5 / 1.0）× 该条件权重

满足度判断：
  1.0 = 完全满足
  0.5 = 部分满足（有依据，但未达到明确门槛）
  0.0 = 不满足 / 数据缺失（在推理链里标注）

总分 = Σ（各条件得分）= 满分为所有条件权重之和（应等于1.0）
```

**推荐等级**：

| 总分范围 | 等级 | 说明 |
|---------|------|------|
| ≥ 0.70 | 推荐 | 主要条件充分满足 |
| 0.50–0.69 | 观察 | 部分条件满足，可持续跟踪 |
| < 0.50 | 不推荐 | 本次条件不符，不进入输出 |

**Screener Agent 系统提示词**：

```
你是一个专业的 A 股选股评分员。你的任务是根据用户的选股条件，
对 Research Agent 提供的每只候选股票进行逐条评分，输出完整的推理链。

【评分规则】
每个条件的满足度分三档：
  1.0 = 完全满足：数据明确支持，超过用户设定的门槛
  0.5 = 部分满足：有正面数据支持，但未完全达到门槛，或存在不确定性
  0.0 = 不满足或数据缺失：数据明确不支持，或 Research 报告中没有该数据

得分计算：
  该条件得分 = 满足度 × 该条件权重
  股票总分 = 所有条件得分之和

推荐等级（使用用户设定的推荐门槛，默认0.65）：
  总分 ≥ 推荐门槛 → "推荐"
  总分 0.50 ~ 推荐门槛 → "观察"
  总分 < 0.50 → "不推荐"（不纳入输出，只记录日志）

【推理链规范】
每个条件的评分必须附带具体依据，不能只写结论：
✗ 错误："满足，股东结构良好"
✓ 正确："部分满足（0.5）。前十大股东中私募基金2家，个人投资者持股约35%，
         合计约58%，略低于60%门槛。数据来源：AkShare 2026-04-12。"

数据缺失时，满足度统一给 0.0，推理链注明：
"数据缺失：Research 报告未提供该项数据，无法评估。"

【输出格式】
严格按照 ScreenerResult Pydantic 模型输出，JSON 格式，不要输出其他文字。

用户选股条件（含权重和评估说明）：
{conditions_json}

推荐分数门槛：{recommendation_threshold}

Research Agent 提供的股票数据：
{research_results_json}
```

**输出格式（Pydantic BaseModel 强类型）**：
```python
class ConditionScore(BaseModel):
    condition_id: str
    condition_name: str
    satisfaction: float        # 0 / 0.5 / 1.0
    weighted_score: float      # satisfaction × weight
    reasoning: str             # 推理依据，必须引用具体数据

class StockRecommendation(BaseModel):
    code: str
    name: str
    total_score: float
    recommendation_level: Literal["推荐", "观察", "不推荐"]
    condition_scores: List[ConditionScore]
    data_gaps: List[str]       # 影响评分的缺失数据
    trigger_ref: str           # 关联的触发事件ID
```

### 5.6 Skeptic Agent

**职责**：对 Screener 评分最高的 TOP 5 只股票进行对抗性质疑，专门找推理漏洞和数据盲区。

**运行范围**：只对 TOP 5 运行，不是每只股票——控制 LLM 调用成本。

**两类质疑**：

| 质疑类型 | 处理方式 |
|---------|---------|
| **逻辑风险**：推理本身存在漏洞（如"补贴政策落地有时滞"） | 直接写入风险注释，不触发新一轮调研 |
| **数据盲区**：某个关键数据点缺失影响判断 | 报告给 Supervisor，由 Supervisor 决定是否补查 |

**Skeptic Agent 系统提示词**：

```
你是一个专业的风险分析师，专门为选股推荐结果做对抗性质疑。
你的职责是找出推理中的漏洞、数据盲区，以及当前市场环境下的特定风险。
你的目标不是否定推荐，而是让最终输出更完整、更诚实。

【质疑范围】
只针对 Screener 评分最高的 TOP5 只股票进行质疑，不覆盖全部候选。

【质疑类型定义】
每条质疑必须明确标注类型：

[逻辑风险]：推理本身存在的缺陷，即使数据完整也成立
  示例：
  · "补贴政策落地到企业实际收益通常有6-12个月时滞，
     短期股价可能已透支预期"
  · "当前 PE=35，高于该行业历史中位数28，估值溢价明显"
  · "行业竞争格局近期有变化，龙头地位未必稳固"

[数据盲区]：Research 报告中缺失的、且影响评分准确性的数据
  示例：
  · "Research 报告未包含大股东近6个月增减持记录，
     无法判断内部人是否在减仓"
  · "产品涨价数据只覆盖国内，海外市场价格趋势未知"

【质疑质量标准】
✗ 不合格（泛泛而谈）："市场存在不确定性，需谨慎"
✗ 不合格（重复Screener已说的）：Screener已注明"私募占比58%略低门槛"，
  Skeptic不要再重复这个点
✓ 合格：有具体数据、具体时间或具体机制支撑的质疑

每只股票至少输出2条质疑，[逻辑风险]和[数据盲区]各至少1条（如果都有的话）。

【输出格式】
严格按照 SkepticResult Pydantic 模型输出，JSON 格式。

要质疑的股票（TOP5，含 Screener 评分和推理链）：
{top5_recommendations_json}
```

**输出示例**：
```
宁德时代 Skeptic 质疑：
  · [逻辑风险] 补贴细则落地到企业实际收益有6-12月滞后，
    短期股价可能已透支政策预期
  · [逻辑风险] 当前PE=35，高于行业历史中位数（28），
    估值溢价需要业绩加速兑现来支撑
  · [数据盲区] Research 报告未包含大股东近6个月增减持记录，
    无法判断内部人态度
```

### 5.7 Data Recorder（独立节点，无 LLM）

**职责**：每日收盘后自动运行，机械性地记录推荐数据并在评估节点到期时计算超额收益。与 Critic Agent 完全分离，不涉及分析或判断。

**为什么单独拆出来**：数据收集是基础设施，每天必跑，不需要 LLM，成本接近零。将其混入 Critic Agent 会增加不必要的触发复杂度。

**每日工作流程**（纯 Python 脚本）：
```python
def run_data_recorder(date: str, user_id: str):
    # Step 1：记录今日推荐（如有）
    recommendations = db.get_today_recommendations(date, user_id)
    for rec in recommendations:
        close_price = akshare.get_close_price(rec.code, date)
        benchmark_close = akshare.get_index_close("000300", date)  # 沪深300
        db.save_evaluation_record(
            stock_code=rec.code,
            recommendation_date=date,
            strategy_version=rec.strategy_version,   # 关联策略版本
            recommendation_score=rec.total_score,
            condition_satisfactions=rec.condition_scores,
            price_at_rec=close_price,
            benchmark_at_rec=benchmark_close,
            eval_short_date=None,   # 待填：推荐日 + short_window 天
            eval_long_date=None     # 待填：推荐日 + long_window 天
        )

    # Step 2：检查哪些历史推荐今天到达评估节点（short_days/long_days，可配置）
    pending = db.get_pending_evaluations(date, user_id)
    for record in pending:
        current_price = akshare.get_close_price(record.stock_code, date)
        current_benchmark = akshare.get_index_close("000300", date)
        stock_return = (current_price - record.price_at_rec) / record.price_at_rec
        bench_return = (current_benchmark - record.benchmark_at_rec) / record.benchmark_at_rec
        alpha = stock_return - bench_return
        db.update_evaluation_result(record.id, alpha=alpha, eval_date=date)

    # Step 3：为追踪列表中的股票记录当日收盘价（用于前端展示走势，不进入Critic分析）
    watchlist = db.get_watchlist(user_id)
    for stock in watchlist:
        price = akshare.get_close_price(stock.code, date)
        db.update_watchlist_daily(stock.code, user_id, date, price=price)

    # Step 4：生成每日轻量统计摘要（纯SQL，无LLM）
    stats = {
        "date": date,
        "new_evaluations_today": db.count_new_evaluations(date, user_id),
        "pending_total": db.count_pending_evaluations(user_id),
        "oldest_pending_days": db.get_oldest_pending_age(user_id),
        "evaluated_total": db.count_evaluated(user_id),
        "recent_avg_alpha": db.calc_recent_avg_alpha(user_id, n=30),
        "recent_win_rate": db.calc_recent_win_rate(user_id, n=30),
        "milestone_progress": f"{db.count_evaluated(user_id) % threshold}/{threshold}"
    }
    db.save_daily_stats(user_id, stats)
```

**每日价格记录 vs Critic 评估样本的关系**：

Data Recorder 每天记录追踪股票的收盘价，但这份数据**只用于前端展示**（追踪页的走势图、"追踪以来收益"），**不进入 Critic 的分析样本**。原因：

```
示例：Day 0 推荐宁德时代，评分 0.81
  Day 1：  跌 2%
  Day 15： 跌 8%（市场整体回调）
  Day 30： 反弹，超额收益 +5%

→ Critic 的结论：这次推荐有效，C2/C4-E 条件预测准确
→ 若把 Day1~Day29 的每日涨跌也纳入，结论会被中途噪声污染
```

正确的数据流向：

```
每日收盘价（Data Recorder 每天记录）
        │
        ├─→ 追踪页：显示每日走势、"追踪以来收益"    ← 仅用于展示
        │
        └─→ 仅评估节点当天（第30/90天）的价格
                    │
                    └─→ 计算 alpha → 写入 critic_evaluations → Critic 分析用
```

简单说：**每天都记，但只有评估节点那天的数据才参与 Critic 分析**。

### 5.8 Critic Agent（LLM 分析节点）

**职责**：读取 Data Recorder 积累的评估数据，生成两份可读报告（股票维度 + 条件维度），提出权重调整建议。

**触发方式**（满足任一即可）：
- **里程碑自动触发**：累积 N 条完成评估的记录后自动触发（默认 N=10，可配置）
- **用户手动触发**：策略配置页点击"立即分析"，使用当前全部已评估数据

**评估时间窗口（与交易风格挂钩，可配置）**：

不同交易风格的用户，条件类型不同，合理的评估窗口也不同。系统通过 `trading_style` 预设控制默认值，用户也可直接修改具体天数：

| `trading_style` | 适用场景 | `eval_short_days` | `eval_long_days` |
|----------------|---------|-------------------|-----------------|
| `short`（短线） | 技术面、事件驱动 | 7 天 | 30 天 |
| `medium`（中线，默认） | 政策、行业轮动 | 30 天 | 90 天 |
| `long`（长线） | 基本面、长期趋势 | 90 天 | 180 天 |

| 参数 | 说明 | 默认值（medium） |
|------|------|--------|
| `trading_style` | 交易风格预设，影响评估窗口默认值 | `"medium"` |
| `eval_short_days` | 短期评估窗口 | 30天 |
| `eval_long_days` | 长期评估窗口 | 90天 |
| `milestone_threshold` | 触发报告的最少评估样本数 | 10条 |

**条件版本化处理**：
每个条件有独立的 `last_modified_date`。Critic 在分析某个条件时，只使用该条件**最后修改日期之后**的推荐数据，确保条件描述变动不污染历史数据：

```
C3 于 2026-03-15 修改描述
→ Critic 分析 C3 时只用 03-15 之后的推荐
→ 旧版本数据仍保留，在报告里标注为"历史参考（旧版本标准）"

C1 从未修改
→ Critic 分析 C1 时使用全部历史数据
```

**样本量分级规则**（Critic 在分析前先判断，决定能输出哪级别的结论）：

| 有效评估记录数 | 可做的分析 | 输出说明 |
|-------------|---------|---------|
| < 30 条 | 仅整体胜率 + 平均超额收益 | 不做条件分析，提示"需至少30条评估记录" |
| 30–100 条 | 整体报告 + 单条件三档分层分析 | 每条条件结论标注"（n=X，初步参考）" |
| > 100 条 | 完整报告 + 条件有效性 + 条件组合分析 | 结论置信度提升，不再标注"初步参考" |

**单条件有效性：三档分层分析（Quintile 简化版）**：

将历史推荐按某条件的满足度分三档，检验各档收益是否单调递减：

```
C3 股东结构有效性分析（有效样本 n=42，窗口：2026-03-15之后）

  满足度 1.0（完全满足，n=18）：平均超额收益 +5.8%，胜率 72%
  满足度 0.5（部分满足，n=16）：平均超额收益 +1.2%，胜率 56%
  满足度 0.0（不满足，   n=8） ：平均超额收益 -2.1%，胜率 38%

  单调性检验：✓ 三档收益单调递减，条件有预测力
  相关性：满足度与超额收益 Spearman 相关系数 = 0.31（>0.10，有效）

  建议：权重维持（当前 0.15）或小幅提升
```

若三档不单调（如满足度 0.5 的收益反而高于 1.0），Critic 需解释可能原因，**不直接给权重建议**。

**条件组合分析（仅100条以上执行）**：

```
条件组合效果（Top 组合，n=23 条有评估记录）：

  C1✓ + C2✓ 同时完全满足（n=23）：平均超额 +8.3%，胜率 78%
  C2✓ + C7✓ 同时完全满足（n=19）：平均超额 +6.9%，胜率 74%
  仅 C1✓（C2 不满足，n=11）：   平均超额 +2.1%，胜率 55%

  洞察：C1+C2 组合效果显著优于单独满足 C1，
        说明政策利好时龙头企业才是最优选，泛行业个股效果有限
```

**Critic Agent 系统提示词**：

```
你是一个量化策略分析师，负责评估用户选股条件的历史有效性，
为用户提供有依据的策略改进建议。

【分析前置检查】
首先判断有效评估记录数量：
- < 30 条：只输出报告一（整体表现），跳过报告二（条件分析）
- 30-100 条：输出报告一 + 报告二（标注"初步参考"）
- > 100 条：输出完整报告一 + 报告二 + 条件组合分析

【报告一：股票推荐表现回顾】
  - 本期新增评估完成的推荐记录：X条
  - 整体胜率（跑赢沪深300的比例）+ 平均超额收益（两个指标都要给）
  - 表现最好 / 最差的2-3个案例，说明原因
  - 与上期报告相比的趋势

【报告二：条件有效性分析（三档分层）】
  对每个条件，基于有效数据窗口（last_modified_date之后）：
  - 分别统计满足度 1.0 / 0.5 / 0.0 三档的平均超额收益和胜率
  - 判断三档是否单调递减（单调=有预测力，不单调=需解释原因）
  - 不单调时，不给权重建议，只描述现象

  权重调整建议规则（仅单调时才给）：
  - 三档收益差异明显且持续N期（默认4期）：建议调整方向
  - 调整幅度上限：单次不超过当前权重的30%，且不低于0.05
  - 每条建议必须附理由

【报告格式要求】
- 所有数据标注样本量
- 区分"统计结论"（事实）和"建议"（判断）
- 条件版本切换时，旧版本数据单独列出，标注"旧版本标准下的参考数据"

评估数据：{evaluation_records_json}
当前条件配置（含各条件last_modified_date）：{conditions_json}
评估窗口：短期{short_days}天 / 长期{long_days}天
有效记录数：{evaluated_count}条（用于判断分析级别）
```

**运行频率小结**：

| 层次 | 节点 | 频率 | LLM |
|------|------|------|-----|
| 数据收集 | Data Recorder | 每日 16:30 定时 | 无 |
| 周报摘要 | Data Recorder 输出 | 每周五，自动 | 无（纯统计） |
| 分析报告 | Critic Agent | 里程碑或手动触发 | 有 |

**HITL 保护**：Critic 的权重调整建议需用户在策略配置页确认后才写入 UserProfile。

**Critic 数据如何融入各页面**：

Critic 每次输出报告后，将结论数据写入 `critic_reports` 表（`condition_analysis_json`、`overall_win_rate`、`suggestions_json` 字段），前端各页面按需读取**最新一期**报告数据展示。具体融入点如下：

| 页面 | 展示的 Critic 数据 | 展示位置 |
|------|-----------------|---------|
| **今日推荐** | 当前策略整体历史胜率（如"历史策略胜率 61%"） | 页面顶部，推荐列表上方 |
| **今日推荐 > 分析链路 > 评分明细** | 每条条件得分旁显示该条件历史有效性（灰色小字，如"C3 历史准确率38% ⚠️"） | 评分明细每行 |
| **策略配置 > 条件卡片** | 条件近期胜率 + 有效性状态标签 + 权重建议 | 每张条件卡片右侧 |
| **策略配置 > Critic 健康报告区** | 完整条件有效性条形图 + 整体胜率趋势 | 页面下半区 |
| **个股分析报告 > 评分明细** | 同"分析链路"，每条条件评分旁显示历史有效性 | 评分明细每行 |
| **追踪列表 > 股票卡片** | 若该股票曾被推荐且已过评估期，显示该次推荐的实际超额收益 | 股票卡片底部 |
| **历史推荐记录** | 到期推荐的实际超额收益（Data Recorder 计算）+ 收益颜色（绿/红） | 每条历史记录 |

**注意**：Critic 数据是"读取展示"，不实时计算——只在 Critic 报告生成后更新，未生成报告时显示"暂无分析数据"或上次报告的数据（标注报告日期）。

### 5.9 个股分析与股票追踪

#### 5.9.1 个股分析

**触发方式**（三个入口）：
- 今日推荐页某只股票卡片 → 点击"深入分析"
- 追踪列表某只股票 → 点击"立即分析"
- 个股分析与追踪页顶部搜索栏 → 直接输入股票代码/名称

**运行流程**（复用主流程全部基础设施）：

```
用户指定股票代码
       ↓
Supervisor（起始指令变为："用我的条件对 [代码] 做完整分析"）
       ↓  与主流程相同的调度逻辑，读取相同 UserProfile
Research Agent（ReAct）
  → 依次调用所有评估层 + 入场层 Skills，收集该股票数据
       ↓
Screener Agent → 逐条打分（评估层条件）
       ↓
Entry Gate → 判断入场层条件
       ↓
Skeptic Agent → 质疑（不受 TOP5 限制，对该股票必然运行）
       ↓
Supervisor → finalize → 输出完整分析报告
       ↓
写入 DB（analysis_type="individual"，关联 user_id + stock_code + date）
```

**与主流程推荐的差别**：

| 维度 | 主流程推荐 | 个股分析 |
|------|----------|---------|
| 起点 | Trigger 信号驱动，自动发现候选股票池 | 用户指定具体股票 |
| 触发条件 | 必须有触发信号 | 随时可发起，不受触发限制 |
| Skeptic 范围 | 只对 TOP5 运行 | 对该股票必然运行 |
| 输出格式 | 与其他推荐同格式（按触发事件分组） | 独立分析报告，无"触发来源"，替换为"用户主动分析" |
| 数据复用 | 是（当日已有新闻入库） | 是（DB优先，最新当日数据） |

**输出报告格式**（与今日推荐的分析链路相同结构）：

```
宁德时代 002459  个股分析报告          2026-04-12 14:30

━━━ ① 分析背景 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用户主动分析  ·  未关联当日触发事件

━━━ ② Research 调研摘要 ━━━━━━━━━━━━━━━━━━━━
· 储能出货量全球第一，2025年市占率28%
· 近30日北向资金净流入3.2亿元
...

━━━ ③ Screener 评分明细 ━━━━━━━━━━━━━━━━━━━━
C2 行业龙头    0.28/0.28  完全满足    [历史准确率 75%]
C3 股东结构    0.08/0.15  部分满足  ⚠️[历史准确率 38%]
...

━━━ ④ Skeptic 质疑 ━━━━━━━━━━━━━━━━━━━━━━━━
[逻辑风险] ...
[数据盲区] ...

━━━ ⑤ Supervisor 综合判断 ━━━━━━━━━━━━━━━━━━
"..."

                          综合评分 0.81  [推荐]  [加入追踪]
```

---

#### 5.9.2 股票追踪

**添加到追踪列表的三种方式**：
1. 今日推荐页 → 股票卡片 → "加入追踪"
2. 个股分析报告底部 → "加入追踪"
3. 追踪页顶部 → 直接输入代码手动添加（不触发分析）

**每日追踪机制**（Data Recorder 盘后一并处理，无 LLM）：

```python
def run_watchlist_tracking(date: str, user_id: str):
    watchlist = db.get_watchlist(user_id)
    for stock in watchlist:
        # 记录当日价格和技术数据（轻量，用于追踪页展示）
        price = akshare.get_close_price(stock.code, date)
        tech = akshare.get_technical_basics(stock.code, date)
        db.update_watchlist_daily(stock.code, user_id, date, price=price, tech=tech)

        # 检查是否出现在今日推荐中
        today_rec = db.get_recommendation(stock.code, date, user_id)
        if today_rec:
            db.update_watchlist_flag(stock.code, user_id, "in_recommendation", score=today_rec.total_score)

        # 检查技术面突破（C7 条件对应的轻量检测）
        if tech.volume_ratio > 1.5 and tech.price_breakout:
            db.set_watchlist_alert(stock.code, user_id, "technical_signal")

        # 检查是否建议重新分析（距上次分析超过 N 天，默认 7 天）
        last_analysis = db.get_last_analysis_date(stock.code, user_id)
        if (date - last_analysis).days >= 7:
            db.set_watchlist_flag(stock.code, user_id, "suggest_reanalysis")
```

**追踪提醒标签规则**：

| 标签 | 触发条件 | 含义 |
|------|---------|------|
| 📈 今日入推荐 | 当日出现在主流程推荐列表 | 信号与追踪重合 |
| 🔔 技术信号 | 量比 > 1.5 且价格突破关键压力位 | 技术面值得关注 |
| ⚠️ 建议重新分析 | 距上次分析 ≥ 7 天 | 数据可能已过期 |
| ↓ 信号减弱 | 连续 3 个交易日未出现在推荐列表（且之前曾连续出现过） | 信号可能消退 |

**追踪与评估的联动**：
- 每只被追踪且曾被推荐的股票，Data Recorder 会自动记录其超额收益（与主流程推荐记录共用同一评估机制）
- 超额收益到期后在追踪卡片上展示，无需用户手动查找

---

## 6. 数据设计

### 6.1 User Strategy Profile

> ⚠️ 注意：以下为 dad_001 用户的私有策略档案，仅供内部开发使用。
> 产品开源或公开发布时，替换为通用的默认模板条件，不暴露此档案。

```json
{
  "user_id": "dad_001",
  "name": "老爸的策略",
  "conditions": [

    // ── 触发层（Trigger Layer）──────────────────────────────────────
    // 触发层条件无权重，用于每日扫描时的二元判断（有/无触发）

    {
      "id": "C1",
      "name": "政策支持",
      "layer": "trigger",
      "research_skill": null,
      "description": "有即时的新政策、新法律出台，明确支持该行业发展。关键看政策的落地确定性和力度——草案征求意见不算，正式发布才算。利好方向：补贴、减税、强制采购目录、行业准入放开。",
      "weight": null,
      "initial_weight": null,
      "trigger_config": {
        "skill": "PolicyMonitorSkill",
        "keywords": ["补贴", "减税", "政策落地", "实施细则", "采购目录"],
        "sources": ["ndrc", "mofcom", "cailian", "eastmoney"]
      },
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },
    {
      "id": "C6",
      "name": "转折事件",
      "layer": "trigger",
      "research_skill": null,
      "description": "有明确的转折事件出现并推动行情，这是触发本次关注的直接催化剂。转折事件包括：政策正式落地、重要合同签订、行业拐点数据公布、公司重大人事变动等。转折事件越具体、越可量化，越符合条件。",
      "weight": null,
      "initial_weight": null,
      "trigger_config": {
        "skill": "EventMonitorSkill",
        "keywords": ["正式落地", "签订合同", "拐点", "业绩预告", "重大公告"],
        "sources": ["cailian", "eastmoney", "sse", "szse"]
      },
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },
    {
      "id": "C4-T",
      "name": "涨价信号（触发）",
      "layer": "trigger",
      "research_skill": null,
      "description": "市场上出现行业性涨价信号——某类大宗商品或中间品价格连续上涨，可能预示产业链上的公司受益。此处只判断市场层面是否出现涨价事实，不判断具体公司是否受益（那是C4-E的工作）。",
      "weight": null,
      "initial_weight": null,
      "trigger_config": {
        "skill": "PriceSignalSkill",
        "keywords": ["价格上涨", "涨价", "供不应求", "库存下降"],
        "sources": ["smm", "mysteel", "cailian"]
      },
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },

    // ── 评估层（Screener Layer）──────────────────────────────────────
    // 评估层条件有权重，weights 之和 = 0.85
    // 加上入场层 C7 权重 0.15，全部条件权重合计 = 1.00

    {
      "id": "C2",
      "name": "行业龙头",
      "layer": "screener",
      "research_skill": "LeadershipResearchSkill",
      "description": "该股票的公司处于受政策支持的行业，且为龙头企业。判断依据：市占率行业前三、或细分领域第一、或营收规模行业领先。龙头企业在政策利好时往往获得最大受益，且资金首选。",
      "weight": 0.28,
      "initial_weight": 0.28,
      "trigger_config": null,
      "entry_config": null,
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },
    {
      "id": "C3",
      "name": "股东结构",
      "layer": "screener",
      "research_skill": "HolderStructureSkill",
      "description": "前10大股东以私募股权投资和个人投资者为主，合计占流通股比重超60%以上。核心逻辑是看'聪明钱'是否入场——国内私募重仓说明专业机构看好。注意：外资、国企、社保持仓不算聪明钱；纯散户持股分散也不符合。前十大里有3个以上知名私募基金基本满足条件。",
      "weight": 0.15,
      "initial_weight": 0.15,
      "trigger_config": null,
      "entry_config": null,
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },
    {
      "id": "C4-E",
      "name": "产品涨价（评估）",
      "layer": "screener",
      "research_skill": "PriceBenefitSkill",
      "description": "该公司的核心产品正在受益于涨价，且涨价驱动力是供需不平衡（需求大、供应少）。需区分：供需驱动的涨价（持续性强，符合条件）vs 成本推动的涨价（持续性弱，不符合）。可从近3个月价格走势、行业供需数据，以及该公司的产品定价能力判断。",
      "weight": 0.22,
      "initial_weight": 0.22,
      "trigger_config": null,
      "entry_config": null,
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },
    {
      "id": "C5",
      "name": "中期上涨趋势",
      "layer": "screener",
      "research_skill": "MidTermTrendSkill",
      "description": "在未来半年到一二年内，有明确的上涨趋势预期。判断依据：机构一致性预期向上、行业景气度上行周期、公司基本面持续改善。注意：这是中期趋势判断，不是看短期涨跌，要结合行业周期和政策持续性综合判断。",
      "weight": 0.20,
      "initial_weight": 0.20,
      "trigger_config": null,
      "entry_config": null,
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    },

    // ── 入场层（Entry Layer）──────────────────────────────────────────
    // 入场层条件在 Screener 评分完成后执行最终检查
    // is_hard_gate=true 时：不满足则股票不进入推荐，不论 Screener 得分多高
    // is_hard_gate=false 时：仍参与加权计分，但单独显示入场信号状态

    {
      "id": "C7",
      "name": "技术突破",
      "layer": "entry",
      "research_skill": "TechnicalBreakoutSkill",
      "description": "在交易上有明显的技术上涨特征，有量能突破。判断依据：成交量突破近20日均量1.5倍以上、价格突破关键压力位（前高、均线）、MACD金叉或趋势向上。量能是关键——没有量的突破不可信，有量的突破信号才强。",
      "weight": 0.15,
      "initial_weight": 0.15,
      "trigger_config": null,
      "entry_config": {
        "skill": "TechnicalBreakoutSkill",
        "is_hard_gate": false,
        "hard_gate_threshold": 0.5
      },
      "learned_accuracy": null,
      "accuracy_history": [],
      "consecutive_low_periods": 0,
      "last_modified_date": "2026-04-12",
      "last_updated": "2026-04-12"
    }

  ],
  "advanced_settings": {
    "trading_style": "long",
    "eval_short_days": 90,
    "eval_long_days": 180,
    "milestone_threshold": 10,
    "risk_preference": "moderate",
    "recommendation_threshold": 0.65,
    "industry_focus": "all",
    "data_source_preferences": ["eastmoney", "cailian", "ndrc", "smm"]
  },
  "stats": {
    "total_recommendations": 0,
    "overall_win_rate": null,
    "benchmark_alpha": null
  }
}
```

**字段说明**：

| 字段 | 适用层 | 说明 |
|------|--------|------|
| `layer` | 所有条件 | `"trigger"` / `"screener"` / `"entry"`，决定条件参与哪个分析环节 |
| `research_skill` | screener / entry | Research Agent 调用的 Skill 名称；`null` 时使用 `GenericResearchSkill` |
| `weight` | screener / entry | 评分权重，触发层为 `null`；所有 screener+entry 条件权重之和 = 1.0 |
| `trigger_config` | trigger | 触发层专属配置：`skill`（使用的 Skill）、`keywords`（扫描关键词）、`sources`（数据源） |
| `entry_config` | entry | 入场层专属配置：`is_hard_gate`（是否为硬性门槛）、`hard_gate_threshold`（最低满足度，低于此值则过滤） |
| `description` | 所有条件 | 用户自由文本，可以举例；直接注入 Screener/Entry Prompt |
| `initial_weight` | screener / entry | 原始权重，用于回溯对比 |
| `learned_accuracy` | screener / entry | 最近一期 Critic 报告中该条件的有效性 |
| `consecutive_low_periods` | screener / entry | 连续有效性低于 40% 的分析周期数，≥4 触发预警 |
| `last_modified_date` | 所有条件 | 条件描述最后修改日期；Critic 分析时只使用此日期之后的数据 |
| `advanced_settings` | 用户级 | 高级配置，有默认值，Phase 2 逐步开放用户修改 |

**权重分布说明（C4 拆分后）**：

| 条件 | 层 | 权重 |
|------|----|------|
| C1 政策支持 | 触发层 | — |
| C6 转折事件 | 触发层 | — |
| C4-T 涨价信号 | 触发层 | — |
| C2 行业龙头 | 评估层 | 0.28 |
| C3 股东结构 | 评估层 | 0.15 |
| C4-E 产品涨价（评估） | 评估层 | 0.22 |
| C5 中期趋势 | 评估层 | 0.20 |
| C7 技术突破 | 入场层 | 0.15 |
| **合计** | | **1.00** |

### 6.2 关键数据表

在现有 SQLite 表基础上新增/扩展：

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `user_profiles` | 用户策略档案 | user_id, profile_json |
| `triggers`（扩展）| 触发事件记录 | industry, type, strength, trigger_summary_json |
| `screener_stocks`（扩展）| 每次推荐记录 | condition_scores_json, data_gaps_json, trigger_id |
| `critic_evaluations` | 每条推荐的评估记录 | stock_code, recommendation_date, eval_date, return_90d, alpha_90d |
| `critic_reports` | 批量分析报告 | report_date, sample_size, condition_analysis_json, suggestions_json |
| `news_items`（扩展）| 新闻记录（Phase 1末加embedding列）| title, content, industry, source, embedding |

---

## 7. 前端页面详细设计

### 7.1 页面总览

| 页面 | 核心功能 | 主要用户场景 |
|------|---------|------------|
| 今日信息 | 多源新闻聚合，可筛选浏览 | AI 推荐不完善时自己读新闻；了解触发背景 |
| 今日推荐 | 按触发事件分组的 AI 推荐，含分析链路 | 每天开盘前看推荐决策 |
| 策略配置 | 条件管理 + Critic 健康报告 | 调整选股逻辑；查看系统学到了什么 |

### 7.2 今日信息页

**布局**：
```
今日信息                                       2026-04-12

[全部] [政策] [价格] [公司公告]    行业筛选: [全部 ▼]

──────────────────────────────────────────────────────
📋 国家能源局                                   08:15
   储能补贴细则正式下发，2026年补贴上限提升40%
   标签：#储能 #政策                           [查看原文]

📋 SMM金属网                                   09:02
   电池级碳酸锂现货价连续3周上涨，涨幅累计12%
   标签：#锂电池 #价格                         [查看原文]

📋 财联社                                      09:30
   阳光电源发布业绩预告，Q1净利润同比增长35%
   标签：#储能 #公司                           [查看原文]
──────────────────────────────────────────────────────
```

**交互**：
- 点击标签筛选对应信息
- 点击"查看原文"打开原始链接或展开全文
- 信息按时间降序排列，最新在上

### 7.3 今日推荐页

**布局（按触发事件分组）**：

```
今日推荐                                       2026-04-12
基于 2 个触发事件 · 主流程完成于 09:12
历史策略胜率 61%（基于87条推荐）  ⓘ 查看详情

┌─ 触发① ─────────────────────────────────────────────┐
│ 📋 储能补贴细则正式下发                               │
│ 触发强度：强 · 08:15 · 国家能源局            [原文 ↗] │
├──────────────────────────────────────────────────────┤
│                                                      │
│  宁德时代  002459         0.81  [推荐]                │
│  ● 连续推荐 3天  评分趋势 ↑ (+0.05)                   │
│                              [查看分析链路 →]         │
│                                                      │
│  阳光电源  300274         0.74  [推荐]                │
│  ● 今日首次出现                                       │
│                              [查看分析链路 →]         │
│                                                      │
│  比亚迪储能  002594       0.52  [观察]                │
│  ● 昨日 0.61 → 今日 0.52  评分 ↓                     │
│                              [查看分析链路 →]         │
└──────────────────────────────────────────────────────┘

┌─ 触发② ─────────────────────────────────────────────┐
│ 📋 电池级碳酸锂连续3周涨价                            │
│ 触发强度：中 · 09:02 · SMM金属网            [原文 ↗] │
├──────────────────────────────────────────────────────┤
│  天齐锂业  002466         0.68  [推荐]                │
│  ● 今日首次出现                                       │
│                              [查看分析链路 →]         │
└──────────────────────────────────────────────────────┘

                              [查看历史推荐记录 →]
```

**跨日联动标签说明**：

| 标签 | 触发条件 | 含义 |
|------|---------|------|
| 连续推荐 N 天 | 连续 N 个交易日出现 | 信号持续稳定 |
| 今日首次出现 | 之前从未推荐过 | 新出现的机会 |
| 评分趋势 ↑/↓ | 今日得分 vs 昨日得分差值 | 信号在增强还是减弱 |
| 昨日有今日无 | 昨日推荐，今日未出现 | 信号消失，如已持仓需注意 |

**分析链路展开页**（点击"查看分析链路"）：

```
宁德时代 002459                         综合评分 0.81 [推荐]

━━━ ① 触发来源 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
储能补贴细则正式下发（2026-04-12 08:15，国家能源局）
                                               [查看原文 ↗]

━━━ ② Research Agent 调研摘要 ━━━━━━━━━━━━━━━━━━
· 储能出货量全球第一，2025年市占率28%         [AkShare]
· 近30日北向资金净流入3.2亿元               [东方财富]
· 连续3日放量，突破60日前高                 [技术指标]
· 机构一致预测2026年净利润增长22%           [财联社]
⚠️ 数据缺口：Q4分红政策尚未公告，大股东近期增减持未查到

━━━ ③ Screener 评分明细 ━━━━━━━━━━━━━━━━━━━━━━
C2  行业龙头        ████████░░  0.28/0.28  完全满足    [历史准确率 75%]
                   "出货量第一，市占率28%"
C3  股东结构        ████░░░░░░  0.08/0.15  部分满足  ⚠️[历史准确率 38%]
                   "私募占比58%，略低于60%门槛"
C4-E 产品涨价（评估）██████████  0.22/0.22  完全满足    [历史准确率 72%]
                   "碳酸锂涨价，宁德时代产品定价能力强"
C5  中期趋势        ██████░░░░  0.10/0.20  部分满足    [历史准确率 68%]
                   "机构预期向好，但趋势未完全确认"
C7  技术突破（入场）███████░░░  0.15/0.15  完全满足    [历史准确率 71%]
                   "放量突破，成交量超20日均量180%"

━━━ ④ Skeptic 质疑 ━━━━━━━━━━━━━━━━━━━━━━━━━━
· 补贴细则落地到企业实际收益有6-12个月时滞
· PE=35，高于行业历史中位数（28），估值偏贵
· 大股东增减持数据缺失，存在信息盲区

━━━ ⑤ Supervisor 综合判断 ━━━━━━━━━━━━━━━━━━━━
"触发强度高，龙头地位明确；股东结构略弱、估值偏高为主要
 风险点，且存在数据缺口。综合判断推荐，建议注意仓位控制。"
```

**历史推荐记录页**（从推荐页入口进入）：
```
历史推荐记录

[日期范围 ▼]  [行业 ▼]  [推荐等级 ▼]  [结果 ▼]

04-11  储能政策触发    推荐3只  观察2只  已解锁结果（30天）：2涨1跌
04-10  光伏关税触发    推荐2只            待观察（持仓中，24天）
04-08  锂矿价格触发    推荐4只  观察1只  已解锁结果（34天）：3涨1平
...
```
点击某行展开当日完整推荐详情。90 天后自动计算超额收益，标注结果颜色。

### 7.4 策略配置页

**上区：我的选股条件**

```
我的选股条件                              [+ 新增条件]

── 触发层 ──────────────────────────────────────────────
C1  政策支持        [触发层]                ● 活跃
    有即时新政策利好该行业，例如补贴、减税...
                                      [编辑]  [删除]
C6  转折事件        [触发层]                ● 活跃
    有明确的催化剂出现并推动行情...
                                      [编辑]  [删除]
C4-T 涨价信号       [触发层]                ● 活跃
    市场上出现行业性涨价信号...
                                      [编辑]  [删除]

── 评估层 ──────────────────────────────────────────────
C2  行业龙头        权重 0.28    ● 有效（近期胜率75%）
    该公司为行业龙头，市占率前三...
                                      [编辑]  [删除]

C3  股东结构        权重 0.15    ▲ Critic 建议关注
    前10大股东私募+个人60%+...
    💡 近期胜率38%，已连续4期偏低
    [接受权重建议 0.15→0.11]  [稍后处理]  [忽略此建议]
                                      [编辑]  [删除]

C4-E 产品涨价（评估）权重 0.22   ● 有效（近期胜率72%）
    该公司核心产品正受益于涨价...
                                      [编辑]  [删除]

C5  中期趋势        权重 0.20    ● 有效（近期胜率68%）
    未来半年到一二年内，有明确上涨趋势预期...
                                      [编辑]  [删除]

── 入场层 ──────────────────────────────────────────────
C7  技术突破        权重 0.15    ● 有效（近期胜率71%）
    技术面放量突破，量能明显放大...  [非硬性门槛]
                                      [编辑]  [删除]
```

**条件编辑弹窗**（以"股东结构"为例）：

```
编辑条件：股东结构

条件名称：[股东结构              ]

所属层：  ○ 触发层   ● 评估层   ○ 入场层
          ─────────────────────────────────────────────────
          触发层：扫描时用于判断今天是否有值得关注的信号，
                  二元结果（有/无），无权重
          评估层：对候选股票进行加权打分
          入场层：最终入场时机判断（可设为硬性门槛）

权重：    [0.15]（0.05~0.35，仅评估层和入场层需填写）

入场层配置（入场层才显示此区域）：
  □ 设为硬性门槛（不满足此条件则股票不进入推荐）
  最低满足度门槛：[0.50]（0到1之间，低于此值时硬性过滤生效）

条件说明（自由填写，可以举例）：
┌────────────────────────────────────────────┐
│前10大股东以私募和个人投资者为主，占流通盘    │
│60%以上。关键是国内聪明钱是否入场——外资持有  │
│不算，要看国内私募是否重仓。                 │
│                                            │
│例如：前十大里有3个以上的私募基金基本满足；  │
│以国企、社保为主则不算满足，即使比例超60%。  │
└────────────────────────────────────────────┘
                              [取消]  [保存]
```

**新增条件弹窗与编辑弹窗相同，点击"+ 新增条件"时所属层默认选中"评估层"**。

用户在此编辑的内容（条件说明 + 权重 + 层归属）保存后，下次 Screener 运行时自动生效。后台将条件按层分类注入对应 Agent 的 Prompt 模板，用户不接触 Prompt 结构。

**触发层条件的特殊交互**：触发层条件的编辑弹窗没有权重字段，取而代之的是"触发关键词"和"数据源"配置区，供用户指定扫描时使用的关键词和信息源。

**下区：Critic 策略健康报告**

```
策略数据看板                                        [立即分析]

待评估中：12条推荐（最早一条距今 61天，29天后首批到期）
已评估：  8条（本月新增 2条）
近期表现：已评估的8条 · 平均超额收益 +2.3% · 胜率 62.5%
Critic 进度：已积累 8/10 条，还需 2 条达到触发阈值

──────────────────────────────────────────────────

策略健康报告                    [查看完整报告与历史 →]

最新报告：2026-04-01（基于87条推荐，其中61条达90天观察期）
整体胜率：61%  超额沪深300：+3.2%

条件有效性（三档单调性检验）：
  C2 行业龙头   █████████░  单调✓  胜率 75%  →
  C3 股东结构   ████░░░░░░  单调✓  胜率 38%  ↓↓  ⚠️
  C4-E 产品涨价  ████████░░  单调✓  胜率 72%  →
  C5 中期趋势   ███████░░░  单调？ 胜率 68%  需关注（0.5档收益异常）
  C7 技术突破   ████████░░  单调✓  胜率 71%  →
```

**Critic 完整报告 + 历史页**（点击"查看完整报告与历史"）：
- 时间线：列出所有历史报告，点击查看详情
- 每份报告：完整条件有效性分析 + 条件组合效果 + 建议
- 趋势图：可看到某个条件的有效性随时间变化曲线

**高级配置区**（折叠，有默认值）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 持仓周期 | Critic 的评判时间窗口 | 90天 |
| 风险偏好 | 影响 Skeptic 严格程度和推荐门槛 | 中等 |
| 推荐分数门槛 | 高于此值显示为"推荐"，低于显示"观察" | 0.65 |
| 关注行业范围 | 全市场或指定行业 | 全市场 |
| 数据源偏好 | 各信息源开关 | 全部开启 |

高级配置在 Phase 1 只展示前两项，Phase 2 逐步开放全部配置，降低初次使用的认知负担。

---

### 7.5 个股分析与追踪页

**页面布局**：

```
个股分析与追踪                              2026-04-12

[搜索股票代码或名称...         🔍]  [分析]

──────────────────────────────────────────────────────
我的追踪列表                           共 3 只  [管理]
──────────────────────────────────────────────────────

┌─ 宁德时代  002459 ─────────────────────────────────┐
│ 上次分析：04-12  综合评分 0.81  [推荐]              │
│ 📈 今日出现在推荐列表  评分 0.81（↑ vs 上次 0.78）  │
│                                                    │
│ 追踪以来：+3.2%  vs 沪深300 +1.8%  超额 +1.4%     │
│ [查看今日分析 →]                    [移出追踪]      │
└────────────────────────────────────────────────────┘

┌─ 阳光电源  300274 ─────────────────────────────────┐
│ 上次分析：04-08  综合评分 0.68  [推荐]              │
│ 🔔 技术信号出现  今日量比 1.83，突破60日前高          │
│ ⚠️ 距上次分析已 4 天，建议重新分析                  │
│                                                    │
│ 追踪以来：+1.1%  vs 沪深300 +2.0%  超额 -0.9%     │
│ [立即分析 →]                        [移出追踪]      │
└────────────────────────────────────────────────────┘

┌─ 天齐锂业  002466 ─────────────────────────────────┐
│ 上次分析：04-12  综合评分 0.52  [观察]              │
│ ↓ 信号减弱  连续3日未出现在推荐列表                  │
│ ⚠️ C3 历史准确率 38%，评分中含低效条件               │
│                                                    │
│ 追踪以来：-0.5%  vs 沪深300 +1.8%  超额 -2.3%     │
│ [查看上次分析 →]                    [移出追踪]      │
└────────────────────────────────────────────────────┘
```

**个股分析结果展示**（点击"查看分析"或分析完成后展示，格式与今日推荐分析链路相同）：

```
宁德时代 002459  个股分析                2026-04-12 14:30

━━━ ① 分析背景 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用户主动分析  ·  未关联当日触发事件
（关联近期触发：04-12 储能补贴细则下发）

━━━ ② Research 调研摘要 ━━━━━━━━━━━━━━━━━━━━━━
· 储能出货量全球第一，市占率28%
· 近30日北向资金净流入3.2亿元
⚠️ 数据缺口：大股东近6个月增减持未查到

━━━ ③ Screener 评分明细 ━━━━━━━━━━━━━━━━━━━━━━
C2  行业龙头     ████████░░  0.28/0.28  完全满足    [历史准确率 75%]
C3  股东结构     ████░░░░░░  0.08/0.15  部分满足  ⚠️[历史准确率 38%]
C4-E 产品涨价   ██████████  0.22/0.22  完全满足    [历史准确率 72%]
C5  中期趋势     ██████░░░░  0.10/0.20  部分满足    [历史准确率 68%]
C7  技术突破（入场）███████░░  0.15/0.15  完全满足  [历史准确率 71%]

━━━ ④ Skeptic 质疑 ━━━━━━━━━━━━━━━━━━━━━━━━━━
· [逻辑风险] PE=35，高于行业历史中位数（28），估值偏贵
· [数据盲区] 大股东增减持数据缺失，内部人态度未知

━━━ ⑤ Supervisor 综合判断 ━━━━━━━━━━━━━━━━━━━━
"..."

                          综合评分 0.81  [推荐]

                [加入追踪 ★]         [分享]
```

**"分析背景"区的关联触发逻辑**：
- 个股分析时，系统自动检查今日是否有关联该股票行业的触发事件（从 `triggers` 表查，当日且 industry 匹配）
- 有则在"分析背景"区标注"关联近期触发：[事件标题]"，方便用户理解分析的市场背景
- 没有则只显示"用户主动分析，未关联当日触发事件"

**交互流程**：
1. 用户输入股票代码 → 点击"分析" → 显示"分析中…"（等待后台 Supervisor 运行，预计 1-3 分钟）
2. 分析完成 → 报告展开显示在搜索框下方
3. 用户可选择"加入追踪"，报告自动保存到追踪列表
4. 追踪列表卡片点击"查看上次分析"可随时复看历史报告

**Critic 数据在追踪列表中的展示**：
- 每张追踪卡片底部显示"追踪以来"的价格表现（Data Recorder 每日记录）
- 若该股票曾被系统推荐且已过评估期（30天/90天），自动展示超额收益结果（绿/红色）
- 若某条件历史准确率偏低（< 50%），在对应股票卡片上显示"⚠️ 含低效条件"提醒

---

## 8. 技术选型

### 8.1 核心技术栈

| 模块 | 技术方案 | 选型理由 |
|------|---------|---------|
| 工作流框架 | LangGraph StateGraph | 原生支持 Supervisor 循环模式；节点间状态传递清晰；支持条件边（决定下一步调谁） |
| Agent 间 handoff | Pydantic BaseModel | 所有 Agent 输出强类型，防止上下文信息丢失 |
| LLM 接入 | 沿用 models.json，每 Agent 独立配置 | 各 Agent 可独立切换模型，不耦合 |
| 结构化存储 | SQLite（现有扩展）+ UserProfile JSON | 现有 DB 结构基本保留，改动最小 |
| 向量检索层 | Phase 1末：sqlite-vec；Phase 2评估：Chroma | 见8.2节 |
| Embedding 模型 | paraphrase-multilingual-MiniLM-L12-v2（本地运行） | 中文支持好，轻量，不依赖外部 API |
| 数据工具层 | AkShare + 政府网站爬虫 + Serper | 现有实现已覆盖，10+工具 |
| 可观测性 | LangSmith | 追踪 ReAct 循环、token 消耗、工具调用链路 |
| 前端框架 | 保持现有框架 | 只重构页面内容，不换技术栈 |

### 8.2 向量检索规划

**Phase 1 不加向量库的原因**：Research Agent 的工作方式是每天实时调 API 拿新数据，不查历史语义库。SQLite + SQL 对 Phase 1 的所有场景够用。

**Phase 1 末期加 sqlite-vec（最小改动）**：
- 新闻入库时同步生成 embedding，存入 `news_items.embedding` 列
- 解锁：Research Agent 可以找"历史上语义相似的触发事件"
- 不引入任何新基础设施，仍是一个 .db 文件

```python
# 新闻入库时同步 embed（改动点：news_collector.py）
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

def save_news_with_embedding(news_item):
    text = news_item['title'] + ' ' + news_item['content'][:200]
    embedding = model.encode(text).tolist()
    db.save_news(news_item, embedding=embedding)
```

**Phase 2 评估 Chroma**：
- 如果数据量增大（万条以上），sqlite-vec 性能下降时迁移
- Chroma 有更完善的索引和过滤功能，与 LangChain 集成无缝

**Obsidian 的定位**（不作为系统向量库）：
Obsidian + Smart Connections 插件确实支持语义向量检索（Block 级别分块 embedding），技术上可以写入（Local REST API 插件支持），但选择 sqlite-vec 的原因是工程定位：系统自动产生的高频数据（新闻、推荐记录）需要写入时立即可查，而 Smart Connections 是后台异步扫描。Obsidian 的正确定位是：通过 MCP 让 Chat Agent 读取用户手写的主观投资洞察，作为系统数据之外的个人知识补充。

---

## 9. 模型选型框架

### 9.1 两类模型的核心区别

**指令模型（Instruction Model）**：给它一个任务，直接执行，输出一次性生成。速度快、成本低。适合工具调用、结构化输出、信息摘要。

**推理模型（Reasoning Model）**：回答前先产生内部"思考链"（Chain of Thought），把问题拆解权衡后再给出结论。速度慢、成本高，但适合需要复杂判断和逻辑推导的场景。

```
选型决策规则：
  需要"权衡、判断、找逻辑漏洞"？ → 推理模型
  需要"执行、调工具、格式化输出"？ → 指令模型
  轻量预处理任务？ → 最便宜的小模型
```

### 9.2 各 Agent 选型逻辑

| Agent | 任务性质 | 推荐模型类型 | 推荐示例（可替换） | 关键理由 |
|-------|---------|-----------|----------------|---------|
| 触发预处理 | 结构化信息提取，无需推理 | 小型指令模型 | Qwen-Turbo 同类 | 高频调用，成本优先 |
| Supervisor | 多轮调度决策，需权衡 | **推理模型** | DeepSeek-R1 / o1 同类 | 每日1次，成本可接受；决策质量影响全局 |
| Research Agent | 工具调用 + 中文内容理解 | 强指令模型 | DeepSeek-V3 / GPT-4o 同类 | 工具调用能力和中文表现是核心指标 |
| Screener Agent | 按格式打分，强类型输出 | 指令模型 | DeepSeek-V3 同类 | 结构化任务，不需要复杂推理 |
| Skeptic Agent | 对抗性推理，找逻辑漏洞 | **推理模型** | DeepSeek-R1 / o1 同类 | 每日1次；找漏洞需要多角度推导 |
| Critic Agent | 统计报告生成 | 指令模型 | DeepSeek-V3 同类 | 统计结论明确，不需要推理 |
| Chat Agent（二期）| 对话 + 意图理解 | 强指令模型 | DeepSeek-V3 / Claude Sonnet 同类 | 中文对话质量 + 工具调用 |

### 9.3 中文场景的模型选型考量

A 股选股系统的特殊性：数据来源主要是中文，政策文件、公司公告、财经新闻均为中文，需要优先考虑中文理解能力。

主要选型维度：
1. **中文理解能力**：中文金融语境的准确性
2. **工具调用能力**：function calling 的稳定性
3. **成本/性能比**：多 Agent 系统每次运行 10-30 次 LLM 调用，成本快速积累
4. **延迟**：推理模型比指令模型慢 2-5 倍，只在合适的节点使用
5. **上下文窗口**：Supervisor 的多轮调度需要足够的上下文长度

---

## 10. 版本规划

### Phase 1：核心改造（数据层 + Screener 升级）

**目标**：让 Screener 从用户档案读条件，而不是硬编码；Critic 开始记录数据。

**交付内容**：
- [ ] 新建 `user_profiles` 表，迁移父亲7个条件
- [ ] Screener Agent 从 DB 读条件，自动拼接 Prompt
- [ ] 策略配置页：条件增删改 + 权重调整
- [ ] 前端重构为三页（信息 / 推荐 / 策略配置）
- [ ] 今日推荐页：按触发事件分组 + 分析链路展开
- [ ] Critic 开始记录推荐数据（不做分析，只记录）

**验收标准**：换一个用户 ID，导入不同条件，系统能用该用户条件跑通一次完整流程。

---

### Phase 2：Supervisor 升级 + 触发预处理优化

**目标**：将 if-else Router 替换为 Supervisor LLM，实现动态调度。

**交付内容**：
- [ ] 触发预处理轻量模型：从新闻到结构化摘要
- [ ] Supervisor LLM 节点替换 route_after_trigger
- [ ] Supervisor 读取 UserProfile 准确率历史，输出研究计划
- [ ] Skeptic Agent：对 TOP5 进行对抗验证
- [ ] 跨日联动标签（连续推荐 N 天 / 今日首次 / 评分趋势）
- [ ] Supervisor 循环保护（最大轮次上限 + 上下文压缩）

**验收标准**：C3 准确率低时，Supervisor 的研究计划里明确降低了 C3 的调研优先级；Skeptic 找到数据盲区后能触发 Research Agent 补查一次。

---

### Phase 3：Critic 分析 + 权重建议

**目标**：Critic 从"只记录"升级为"能分析、能建议"。

**交付内容**：
- [ ] 实现按条件统计有效性（满足时 vs 不满足时的超额收益对比）
- [ ] 批量触发机制（累积20条可评估推荐后生成报告）
- [ ] 连续失效预警（4期以上<40%触发提示）
- [ ] 策略配置页：Critic 健康报告区块 + 权重建议 HITL 确认
- [ ] Critic 完整报告页 + 历史记录

**验收标准**：运行90天+后，Critic 能输出可读的条件有效性分析；用户点击接受权重建议后，下次 Screener 运行使用更新后的权重。

---

### Phase 4：向量检索 + 历史语义分析

**目标**：让系统能做历史语义检索，Research Agent 具备"找相似历史触发"的能力。

**交付内容**：
- [ ] sqlite-vec 接入：新闻入库时同步生成 embedding
- [ ] Research Agent 新工具：`search_similar_history`（找语义相近的历史触发）
- [ ] Supervisor 读取历史触发胜率（基于语义相似度匹配，而非精确日期）
- [ ] 历史推荐记录页：30天/90天后自动解锁超额收益结果

**验收标准**：今天储能政策触发，Supervisor 能找到并参考2024年最相近的一次储能政策触发的结果。

---

### Phase 5：Chat Agent（用户交互层）

**目标**：用户可以通过自然语言查询历史、调整偏好。

**交付内容**：
- [ ] Chat Agent 只读功能：查历史推荐、解释某只股票的推荐理由
- [ ] Chat Agent 写操作 + HITL 确认：调整权重、新增/修改条件
- [ ] 高级配置全部开放（持仓周期、风险偏好、数据源偏好等）
- [ ] 条件有效性异常时 Chat Agent 可主动提示

**验收标准**：用户通过对话完成"我想把股东结构这个条件的权重降低"，系统确认后更新，下次运行体现。

---

### 后续规划

- **多用户支持完善**：完整的用户注册/切换流程（当前架构天然支持，只需加前端）
- **策略模板市场**：提供不同风格的预设条件集（技术派、价值派、趋势派），用户选一个开始
- **Chroma 迁移评估**：数据量超过1万条后评估是否从 sqlite-vec 迁移
- **Obsidian 个人洞察接入**：通过 MCP 让 Chat Agent 读取用户在 Obsidian 里的投资笔记，作为补充信息层

---

## 11. 验收标准汇总

| 阶段 | 核心验收标准 |
|------|------------|
| Phase 1 | 条件改为数据驱动：导入不同用户档案，系统用对应条件跑通 |
| Phase 2 | 动态调度生效：条件准确率影响 Supervisor 的研究优先级 |
| Phase 3 | 学习闭环完成：90天后 Critic 输出可解释的条件有效性数据 |
| Phase 4 | 历史语义检索：今日触发能找到语义相近的历史案例 |
| Phase 5 | 对话交互：通过自然语言完成一次权重调整并在下次运行中体现 |

**每只推荐的质量标准**（Phase 2+ 起）：
- 每只股票的推理链中，每条依据都有明确的数据来源标注
- Skeptic 至少提出2条具体质疑（不是泛泛而谈）
- `data_gaps` 字段非空时，推荐等级不超过"观察"

---

*文档维护：每个 Phase 完成后更新验收状态*
