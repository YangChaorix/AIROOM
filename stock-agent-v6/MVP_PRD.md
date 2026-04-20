# Stock Agent MVP — 极简 MVP 产品需求文档

> 版本：v0.1（MVP）
> 创建时间：2026-04-18
> 定位：`stock-agent-v3/docs/PRD.md`（v4 长期蓝图）的"一周手搓版"
> 目标受众：项目作者本人——AI PM、代码小白、已具备 Multi-Agent 心智模型
> 关系声明：原 PRD 继续作为长期蓝图；**本文档是这一周唯一的实施作战文档**，超出本文档范围的需求一律延后

---

## 目录

1. [MVP 目标和范围](#1-mvp-目标和范围)
2. [系统架构（MVP 版）](#2-系统架构mvp-版)
3. [项目目录结构](#3-项目目录结构)
4. [核心 Agent 实现规格](#4-核心-agent-实现规格)
5. [user_profile.json 格式](#5-user_profilejson-格式)
6. [Markdown 输出格式规范](#6-markdown-输出格式规范)
7. [验收标准（MVP 版）](#7-验收标准mvp-版)

---

## 1. MVP 目标和范围

### 1.1 一句话定位

一个**仅保留"真 Supervisor 循环 + 真 ReAct Research Agent + 真条件驱动 Screener/Skeptic"内核**的极简版本。砍掉前端、数据库、持续学习、真实数据源、多用户、HITL。产物是一个能在 LangSmith 里审查完整决策链路、把推荐结果写入 Markdown 文件的可运行 Python 工程，一人一周可独立完成。

### 1.2 MVP 要证明什么（硬指标）

| 要证明的命题 | 验证方式 |
|---|---|
| Supervisor 的每一次路由决策由 LLM 输出 | 代码审查 + Mock LLM 替换测试（见 §4.1） |
| Supervisor 不是固定顺序（Research→Screener→Skeptic）| 不同 trigger 下路由序列不同；LangSmith trace 可核对 |
| Research Agent 内部是真 ReAct | 单次执行中 LLM 自主决定 ≥2 次工具调用；LangSmith 可见思考→工具→观察循环 |
| 选股条件是数据，不是代码 | 修改 `config/user_profile.json` 不改代码，Screener 行为随之变化 |
| 整条链路可审查 | LangSmith 能看到每个节点的输入、输出、推理、工具调用 |

> **关于 Screener 和 Skeptic 为什么不做 ReAct**：Screener 的任务形态是"拿到 Research 的结构化报告后，按用户条件逐条打分"，数据全部在手、无需迭代查询；Skeptic 的任务形态是"对 TOP5 做一次对抗推理，找逻辑风险和数据盲区"，同样是单次推理任务。**强行给它们加 ReAct 循环只是凑数，不是真需要**。因此 MVP 里只有 Research 是真 ReAct，Screener 和 Skeptic 都是单次 LLM 调用（Supervisor 也是单次 LLM 调用，只是会被多次激活）。

### 1.3 MVP **不**证明什么（明确划出边界）

以下问题全部交给原 PRD 的 Phase 1+，MVP 阶段**不承担、不讨论、不做技术预研**：

- 真实数据源可用性（AkShare、Serper、政府爬虫的接入质量）
- 持续学习闭环（Critic 分析、权重自动调整、条件有效性统计）
- 多用户、UserProfile 版本化、HITL 确认流程
- 前端 UI、跨日联动标签、个股分析入口、Chat Agent
- 历史语义检索、向量库、Embedding
- 入场层硬门槛（C7 在 MVP 里当作普通评估条件）
- 性能、成本、并发、容错、监控

### 1.4 保留 / 简化 / 砍掉 一览

| 模块 | 原 PRD 做法 | MVP 处理 | 处理原因 |
|---|---|---|---|
| **Supervisor LLM 循环** | 有 | ✅ **保留（核心）** | MVP 唯一不能妥协的部分 |
| **Research Agent 真 ReAct** | 有 | ✅ **保留（核心）** | 多工具迭代任务，ReAct 是天然形态 |
| **Screener Agent** | 单次打分 | ✅ **保留（核心）**，维持单次 LLM 调用 | 拿到 Research 结构化报告后按条件逐条打分，数据在手，无需迭代 |
| **Skeptic Agent 对抗质疑** | 单次推理 | ✅ **保留（核心）**，维持单次 LLM 调用 | 对 TOP5 做一次对抗推理，找漏洞不需要工具循环 |
| 触发预处理 | 独立 LLM 节点从新闻抽摘要 | ⚠️ **简化**：mock 文件直接给结构化 trigger | 不是本次要验证的点 |
| 数据工具 | AkShare / Serper / 爬虫 | ⚠️ **简化**：mock 工具返回写死数据 | 接入真源不影响架构正确性 |
| UserProfile | SQLite 表 + 版本快照 | ⚠️ **简化**：单文件 `config/user_profile.json` | "文件即数据库" |
| Prompt / Tools 配置 | 混在代码里 | ⚠️ **强制外置**：`config/prompts/*.md` + `config/tools/*.json` | 强制数据/代码分离 |
| Skills 封装层 | Tools→Skills→Agent | ❌ **砍掉** | mock 环境下多一层抽象无价值 |
| 入场层 Entry Gate | 硬门槛 | ❌ **砍掉**：C7 在 Screener 里当普通条件 | 入场逻辑不是架构重点 |
| Trigger Scanner 定时抓取 | cron + 多时段 | ❌ **砍掉**：手动运行 `main.py` | 一周内跑不了 3 次定时扫描 |
| Critic Agent + Data Recorder | 有 | ❌ **砍掉** | 需 30-90 天数据，一周内无法验证 |
| Chat Agent、个股分析 | 独立线路 | ❌ **砍掉** | 复用 Supervisor，但额外入口非核心 |
| SQLite 所有表 | news / triggers / screener / critic | ❌ **砍掉**：结果直接写 Markdown | 无持久化查询需求 |
| 前端页面（3 页）| 有 | ❌ **砍掉**：LangSmith + Markdown 预览 | 前端不是 MVP 要证明的 |
| 向量检索 | sqlite-vec | ❌ **砍掉** | Phase 4 的事 |

### 1.5 MVP 交付物清单

一周结束时,应能向面试官/审查者出示以下**可执行**产物:

1. `python main.py` 可从 mock trigger 跑完一次完整流程,产出一份 Markdown 报告
2. LangSmith 项目里可见完整 trace：Supervisor 每轮决策的 LLM 调用 + Research 的 ReAct 循环 + Screener/Skeptic 的单次 LLM 调用
3. `pytest tests/` 全部通过,其中 Supervisor 真实性测试(§4.1.5)特别关键
4. 修改 `config/user_profile.json`(例如删除 C3),重跑产出的 Markdown 里 Screener 不再对 C3 打分——**用这一步向审查者证明"条件是数据"**

---

## 2. 系统架构（MVP 版）

### 2.1 一图概览（ASCII）

```
┌───────────────────────────────────────────────────────────────────┐
│  [启动]  python main.py                                           │
│     │                                                             │
│     ↓                                                             │
│  load_trigger()   ← data/triggers_mock.json                      │
│  load_profile()   ← config/user_profile.json                     │
│     │                                                             │
│     ↓                                                             │
│  初始化 LangGraph StateGraph,entry = "supervisor"                │
└────────────────────┬──────────────────────────────────────────────┘
                     │
                     ↓
  ╔════════════════════════════════════════════════════════════╗
  ║  supervisor 节点 (LangGraph Node, 推理模型 LLM 驱动)        ║
  ║                                                            ║
  ║  输入 state:                                               ║
  ║    · trigger_summary (结构化)                              ║
  ║    · user_profile (conditions + 权重)                      ║
  ║    · completed_steps (截至目前所有子 Agent 的结果摘要)     ║
  ║    · round (当前第几轮,最多 3)                             ║
  ║                                                            ║
  ║  LLM 调用 → 输出 SupervisorDecision JSON:                  ║
  ║    {                                                       ║
  ║      "action": "dispatch_research"                         ║
  ║              | "dispatch_screener"                         ║
  ║              | "dispatch_skeptic"                          ║
  ║              | "finalize",                                 ║
  ║      "instructions": "给下一个 Agent 的具体任务文本",      ║
  ║      "round": 1 | 2 | 3,                                  ║
  ║      "reasoning": "为什么这么决定(LLM 自己写)",            ║
  ║      "notes": "给 finalize 节点的背景说明"                 ║
  ║    }                                                       ║
  ║                                                            ║
  ║  ★ conditional_edge 仅读取 action 字段做分支                ║
  ║  ★ 不允许在条件边函数里写任何业务 if-else                  ║
  ║  ★ round >= 3 时 LLM 被 prompt 强制输出 finalize           ║
  ╚═══════════╤══════════╤══════════╤════════════════╤═══════════╝
              │          │          │                │
   dispatch_research  dispatch_screener  dispatch_skeptic   finalize
              │          │          │                │
              ↓          ↓          ↓                ↓
  ┌──────────────────────────────────────────┐   ┌──────────────┐
  │  三个子 Agent，形态不同：                  │   │  finalize    │
  │                                          │   │  节点：      │
  │  [research_agent]  ★ 真 ReAct            │   │  渲染        │
  │    - 6 个 mock 工具                       │   │  Markdown    │
  │    - LLM 自主多轮 Thought→Tool→Obs        │   │  写入        │
  │    - max_iterations=8 兜底                │   │  outputs/    │
  │                                          │   │  runs/       │
  │  [screener_agent]  单次 LLM 调用          │   │  run_*.md    │
  │    - 无工具                               │   └──────────────┘
  │    - 拿到 research_report 后按条件逐条打分
  │    - 一次输出完整 ScreenerResult
  │
  │  [skeptic_agent]   单次 LLM 调用
  │    - 无工具
  │    - 对 TOP5 做一次对抗推理
  │    - 一次输出 findings（含 logic_risk / data_gap）
  │
  │  Prompt 均从 config/prompts/{agent}.md 加载
  │  Research 的 tools 从 config/tools/research_tools.json 加载
  │  输出均为 Pydantic 结构，写回 state
  └─────────────────────┬────────────────────┘
                        │
                        ↓  (子 Agent 完成后,LangGraph 回到 supervisor 节点)
                        │
                        └───────→ (回到 supervisor,继续下一轮决策)
```

### 2.2 与原 PRD 架构的对照

| 原 PRD 模块 | MVP 是否保留 | 差异点 |
|---|---|---|
| 4.0 三层条件框架 | ✅ 保留(触发/评估/入场) | 入场层在 Screener 内部当普通条件打分,不做硬门槛 |
| 4.1 四条线路 | ⚠️ 只保留线路一(主流程) | 线路二/三/四全砍 |
| 4.2 主流程 Supervisor 循环 | ✅ 保留 | 实现手段一致(LangGraph conditional edge) |
| 4.2 子 Agent 池 | ✅ 保留 Research/Screener/Skeptic | Skills 层砍掉,Agent 直接用 tools |
| 4.2 Critic 异步流程 | ❌ 砍掉 | MVP 不管长期闭环 |
| 4.2 共享数据层(DB)| ❌ 砍掉 | 状态只存在内存 + Markdown 文件 |
| 4.3 Trigger Scanner 定时 | ❌ 砍掉 | 手动运行 |
| 5.1 触发预处理 | ⚠️ 简化 | mock 文件直接给结构化 trigger |
| 5.2 Supervisor | ✅ 保留 | 第 2 轮触发条件简化为"Skeptic 上报 data_gap 即可",不再要求 TOP3 命中 |
| 5.3 Research Agent | ✅ 保留 | 工具全是 mock,返回写死数据 |
| 5.4 Skills | ❌ 砍掉 | |
| 5.5 Screener | ✅ 保留，与原 PRD 一致：单次 LLM 调用，无工具 | 拿到 Research 结构化报告后按条件逐条打分，数据在手，无需 ReAct |
| 5.6 Skeptic | ✅ 保留，单次 LLM 调用，无工具 | 对 TOP5 做一次对抗推理，找逻辑风险和数据盲区，不需要工具循环 |
| 5.7 Data Recorder | ❌ 砍掉 | |
| 5.8 Critic | ❌ 砍掉 | |
| 5.9 个股分析 | ❌ 砍掉 | |
| 6. 数据设计 | ⚠️ 极简 | 全部变成文件 |
| 7. 前端 | ❌ 砍掉 | Markdown + LangSmith |

### 2.3 运行时序（单次完整流程）

```
t0  main.py 启动
t1  读 triggers_mock.json(预置 2-3 条触发)
t2  读 user_profile.json(父亲 7 个条件)
t3  构造 initial_state,entry = supervisor
t4  Supervisor 第 1 次决策 → 大概率 dispatch_research (LLM 自主,非固定)
t5  Research Agent ReAct 循环（3-6 次工具调用）→ 写 state.research_report
t6  Supervisor 第 2 次决策 → 大概率 dispatch_screener
t7  Screener Agent 单次 LLM 调用 → 写 state.screener_result
t8  Supervisor 第 3 次决策 → 大概率 dispatch_skeptic
t9  Skeptic Agent 单次 LLM 调用 → 写 state.skeptic_result
t10 Supervisor 第 4 次决策 → finalize (或补查 → 回到 t5)
t11 finalize 节点渲染 Markdown → outputs/runs/run_20260418_103012.md
t12 main.py 退出,LangSmith trace 保留
```

**注意**:上述"大概率"一词有意不写死。若 Supervisor 的 LLM 某次决定跳过 Skeptic 直接 finalize,或在 Skeptic 后要求再来一轮 Research 补查 data_gap,都是合法的;这正是"真 Supervisor"的体现。

---

## 3. 项目目录结构

### 3.1 完整目录树

```
stock-agent-mvp/
├── docs/
│   └── MVP_PRD.md                    # 本文档
│
├── main.py                           # 入口:读配置 → 构图 → 跑一次 → 写 Markdown
│
├── config/
│   ├── user_profile.json             # 用户选股条件(父亲 7 条,见 §5)
│   ├── prompts/
│   │   ├── supervisor.md             # Supervisor system prompt 模板
│   │   ├── research.md               # Research Agent system prompt 模板
│   │   ├── screener.md               # Screener Agent system prompt 模板
│   │   └── skeptic.md                # Skeptic Agent system prompt 模板
│   ├── tools/
│   │   └── research_tools.json       # 只有 Research 有 tool 清单（name/desc/input_schema）
│   └── models.json                   # 每个 Agent 的模型配置（名称/provider/temperature）
│
├── data/
│   ├── triggers_mock.json            # 预置 2-3 条 mock 触发信号
│   └── stocks_mock.json              # 预置 6-10 只候选股票的假数据
│
├── agents/
│   ├── __init__.py
│   ├── supervisor.py                 # supervisor_node(state)：单次 LLM 调用，输出 SupervisorDecision
│   ├── research.py                   # research_node(state)：内含 ReAct（AgentExecutor）
│   ├── screener.py                   # screener_node(state)：单次 LLM 调用，输出 ScreenerResult
│   └── skeptic.py                    # skeptic_node(state)：单次 LLM 调用，输出 SkepticResult
│
├── tools/
│   ├── __init__.py
│   └── mock_research_tools.py        # Research 的 6 个 mock 工具（Screener/Skeptic 无工具）
│
├── schemas/
│   ├── __init__.py
│   ├── state.py                      # LangGraph State TypedDict
│   ├── supervisor.py                 # SupervisorDecision (Pydantic)
│   ├── research.py                   # ResearchReport (Pydantic)
│   ├── screener.py                   # ScreenerResult, ConditionScore, StockRecommendation
│   └── skeptic.py                    # SkepticResult, SkepticFinding
│
├── graph/
│   ├── __init__.py
│   ├── builder.py                    # build_graph() → compiled LangGraph
│   └── edges.py                      # route_from_supervisor(state) → node_name
│
├── render/
│   ├── __init__.py
│   └── markdown_report.py            # 将 state 渲染为 Markdown(见 §6)
│
├── outputs/
│   └── runs/                         # run_YYYYMMDD_HHMMSS.md 落盘位置(gitignore)
│
├── tests/
│   ├── test_supervisor_is_real.py    # ★ Supervisor 真实性测试（§4.1.5）
│   ├── test_research_is_react.py     # Research 真 ReAct 测试
│   ├── test_screener_behavior.py     # Screener 正确性测试（条件即数据）
│   ├── test_skeptic_behavior.py      # Skeptic 正确性测试（findings 覆盖两种类型）
│   └── test_config_is_data.py        # 修改 user_profile.json 后行为变化测试
│
├── .env.example                      # OPENAI_API_KEY / LANGSMITH_API_KEY / LANGSMITH_PROJECT
├── requirements.txt                  # langgraph langchain-core pydantic python-dotenv langsmith
└── README.md                         # 如何跑:pip install → 填 .env → python main.py
```

### 3.2 `config/` 下各文件的结构和格式

#### 3.2.1 `config/user_profile.json`

完整格式见 §5。注意:**所有 Agent 运行时读取,不缓存,不复制到 Prompt 里**——这是"条件即数据"的关键。

#### 3.2.2 `config/prompts/{agent}.md`

Markdown 文件,允许用 `{{variable}}` 作为占位符(运行时用 Python `str.format_map` 或 Jinja2 注入)。**只有两种内容**:

1. 固定角色说明(Agent 是谁、做什么)
2. 占位符(从 state 注入的动态数据)

**不允许**把 user_profile 的条件文本硬编码到 Prompt 里。条件必须通过占位符注入。

#### 3.2.3 `config/tools/research_tools.json`

只有 Research Agent 需要工具清单（Screener 和 Skeptic 是单次 LLM 调用，无工具）。格式：

```json
[
  {
    "name": "search_news_from_db",
    "description": "从已入库新闻中按关键词检索;MVP 中返回 mock 结果。",
    "input_schema": {
      "type": "object",
      "properties": {
        "keywords": {"type": "string", "description": "关键词,空格分隔"},
        "hours": {"type": "integer", "description": "回溯小时数,默认 48"}
      },
      "required": ["keywords"]
    }
  }
]
```

**加载逻辑**：`agents/research.py` 启动时读此 JSON，把 `name` 映射到 `tools/mock_research_tools.py` 里同名函数，打包成 LangChain Tool 对象交给 AgentExecutor。**想给 Research Agent 加/减工具，只改这个 JSON**，不改 Agent 代码。

#### 3.2.4 `config/models.json`

```json
{
  "supervisor": {
    "provider": "openai",
    "model": "o1-mini",
    "temperature": 1.0,
    "_rationale": "推理模型;每日 1 次,决策质量优先"
  },
  "research": {
    "provider": "openai",
    "model": "gpt-4o",
    "temperature": 0.3,
    "_rationale": "强指令模型;工具调用稳定"
  },
  "screener": {"provider": "openai", "model": "gpt-4o", "temperature": 0.2, "_rationale": "结构化打分"},
  "skeptic": {"provider": "openai", "model": "o1-mini", "temperature": 1.0, "_rationale": "推理模型;找漏洞"}
}
```

> 对照原 PRD §9.2:Supervisor / Skeptic 用推理模型,Research / Screener 用指令模型。

---

## 4. 核心 Agent 实现规格

四个 Agent 各一小节:职责、Prompt 模板、Tools 清单、输出 Schema、**真假验证方法**。

---

### 4.1 Supervisor(★ 最关键)

#### 4.1.1 职责和输入输出

| 项 | 内容 |
|---|---|
| 节点类型 | LangGraph 普通 node,不含 ReAct 循环(Supervisor 自己一次 LLM call → 一个决策) |
| 输入 | `state.trigger_summary`、`state.user_profile`、`state.completed_steps`、`state.round` |
| LLM | 推理模型(o1-mini / DeepSeek-R1 同类) |
| 输出 | 一个 `SupervisorDecision` Pydantic 对象,写回 `state.last_decision`;`state.round += 1`;`state.completed_steps.append(...)` |
| 约束 | **条件边只读 `action` 字段分支,禁止在边函数里写任何业务判断** |

#### 4.1.2 Prompt 模板草稿(`config/prompts/supervisor.md`)

```markdown
你是一个专业的 A 股选股研究调度员。你的工作是根据今日市场触发信号和用户的
选股档案,决定下一步该调用哪个子 Agent,或者结束流程并输出推荐。

## 调度规则

1. 你会被多次激活:每次子 Agent 完成任务后,你重新评估状态并决定下一步。
2. 最多调度 3 轮(第 3 轮必须输出 finalize,不再调用任何 Agent)。
3. 当前是第 {{current_round}} 轮(共最多 3 轮)。
4. 每次只能输出一个 action,不能一次并行多个 Agent。

## 第 2/3 轮的补查判断

仅当以下条件同时满足时,才启动第 2 轮补查:
  ① Skeptic 的 findings 中出现 type="data_gap" 的条目
  ② 该 data_gap 涉及的股票在 Screener 评分 TOP3 中
  ③ 你判断该 gap 影响了一个权重 > 0.15 的条件

不满足补查条件的,直接 finalize。

## 输出格式(严格 JSON,不要输出其他文字)

{
  "action": "dispatch_research" | "dispatch_screener" | "dispatch_skeptic" | "finalize",
  "instructions": "给下一个 Agent 的具体研究/打分/质疑指令(或给 finalize 节点的背景说明)",
  "round": 1 | 2 | 3,
  "reasoning": "说明你为什么做这个决定(必填,越具体越好)",
  "notes": "将写入最终报告的 Supervisor 综合判断段"
}

## 当前上下文

### 触发信号
{{trigger_summary_json}}

### 用户选股条件(含三层和权重)
{{user_profile_conditions_json}}

### 截至目前已完成的步骤
{{completed_steps_summary}}

### 本轮提醒
- 你现在处于第 {{current_round}} 轮
- 如果 current_round == 3,你**必须**输出 action="finalize"
```

#### 4.1.3 Tools 清单

Supervisor **没有** tools——它只做"纯 LLM 决策"。不要给 Supervisor 加任何 function calling,强制其只能通过文本 JSON 输出表达意图。

对应配置文件 `config/tools/supervisor_tools.json` **不存在**(或为空数组 `[]`)。

#### 4.1.4 输出 Schema(`schemas/supervisor.py`)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class SupervisorDecision(BaseModel):
    action: Literal["dispatch_research", "dispatch_screener", "dispatch_skeptic", "finalize"]
    instructions: str = Field(..., min_length=10)
    round: int = Field(..., ge=1, le=3)
    reasoning: str = Field(..., min_length=20, description="LLM 必须写清楚为什么做这个决定")
    notes: Optional[str] = None
```

> 字段层面强制:`reasoning` 至少 20 字符。如果 LLM 想偷懒写"好"、"ok"这种东西,Pydantic 会拒收——实现侧见到 `ValidationError` 就让 LLM 重试。

#### 4.1.5 ★ 真假验证方法(必须全部通过,这是 MVP 的核心交付物)

**上一版被糊弄的症状**:条件边里直接 `if state.round == 1: return "research" elif state.round == 2: return "screener"`,Supervisor 节点里的"LLM 调用"其实只返回一个固定字符串,整个 Supervisor 是一个伪装成 LLM 的 if-else。

下面 5 个测试逐个把糊弄方式封死:

---

**测试 T1:条件边代码静态审查(反 if-else 测试)**

```python
# tests/test_supervisor_is_real.py
import ast, inspect
from graph.edges import route_from_supervisor

def test_route_function_has_no_business_logic():
    """条件边函数体应当只基于 state['last_decision'].action 做 dict 映射,
    不允许出现任何业务 if-else(round/trigger_strength/completed_steps 判断)"""
    src = inspect.getsource(route_from_supervisor)
    tree = ast.parse(src)

    # 禁用字段列表:出现即视为在条件边里写死业务
    forbidden_reads = {"round", "trigger_strength", "completed_steps",
                       "trigger_summary", "user_profile", "research_report",
                       "screener_result", "skeptic_result"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_reads:
            raise AssertionError(f"route_from_supervisor 不应读取 state.{node.attr}")
        if isinstance(node, ast.Subscript):
            # state["round"] 之类
            key = getattr(node.slice, "value", None)
            if isinstance(key, ast.Constant) and key.value in forbidden_reads:
                raise AssertionError(f"route_from_supervisor 不应读取 state['{key.value}']")
```

**通过标准**:`route_from_supervisor` 函数体只允许读 `state.last_decision.action`,不允许碰任何其他状态字段。

---

**测试 T2:Mock LLM 替换行为差异测试**

```python
def test_replacing_supervisor_llm_changes_system_behavior():
    """把 Supervisor 的 LLM 换成固定 mock,整体行为必须改变。
    如果行为不变,说明 Supervisor 不是真的在决策。"""

    # 真实 LLM 跑一次
    real_trace = run_graph_and_collect_dispatch_sequence(use_mock_supervisor=False)

    # Mock LLM:永远返回 dispatch_research → dispatch_research → dispatch_research → finalize
    mock_trace = run_graph_and_collect_dispatch_sequence(
        use_mock_supervisor=True,
        mock_decisions=[
            "dispatch_research", "dispatch_research", "dispatch_research", "finalize"
        ]
    )

    assert real_trace != mock_trace, \
        "替换 Supervisor LLM 后系统行为未变化,说明 Supervisor 决策没有被真实使用"
```

**通过标准**:两个 trace 的 dispatch 序列不完全相等。(提示:真实 LLM 大概率会走 research→screener→skeptic→finalize;mock 版被强制走 research×3→finalize。二者必然不同。)

---

**测试 T3:不同 trigger 产生不同路由序列**

```python
def test_different_triggers_produce_different_routes():
    """给两个差异明显的 trigger(例如"高强度储能政策" vs "低强度边缘事件"),
    Supervisor 的路由序列或决策内容应该有可观察差异。"""

    trace_strong = run_graph_and_collect_decisions(trigger_fixture="strong_policy.json")
    trace_weak = run_graph_and_collect_decisions(trigger_fixture="weak_noise.json")

    # 至少一项不同:路由序列、每轮 instructions、或 notes
    seq_diff = [d.action for d in trace_strong] != [d.action for d in trace_weak]
    instr_diff = any(
        a.instructions != b.instructions
        for a, b in zip(trace_strong, trace_weak)
    )
    assert seq_diff or instr_diff, \
        "不同强度 trigger 下 Supervisor 决策完全一致,不像是真在基于输入推理"
```

**通过标准**:至少路由序列或 instructions 文本存在差异。

---

**测试 T4:Supervisor 输出必须含非空 `reasoning` 且长度 ≥ 20**

```python
def test_supervisor_decision_contains_real_reasoning():
    """真 LLM 决策必须写出自己的 reasoning。
    Pydantic 层面已经有 min_length=20,本测试是端到端兜底。"""
    trace = run_graph_and_collect_decisions(trigger_fixture="strong_policy.json")
    for d in trace:
        assert len(d.reasoning) >= 20, f"reasoning 过短,疑似伪造: {d.reasoning!r}"
        assert d.reasoning not in {"好", "ok", "继续", "进行下一步"}, \
            f"reasoning 是占位文本: {d.reasoning!r}"
```

---

**测试 T5:LangSmith trace 手工审查清单(人工验收,不自动化)**

跑一次 `python main.py` 后,打开 LangSmith 对应 project,逐项核对:

- [ ] Supervisor 节点出现了 **≥ 3 次**(第 1-N 轮 + 可能的补查)
- [ ] 每次 Supervisor 节点都有对应的 **LLM 调用 span**,而不是纯 Python
- [ ] 每次 LLM 调用的 **prompt** 里包含了当前 `completed_steps`(证明状态在累积)
- [ ] 每次 LLM 调用的 **completion** 都是 JSON 且 `reasoning` 字段内容不同(证明不是 cache)
- [ ] round=3 时的决策 action 必为 `finalize`
- [ ] 条件边的 Python span 里**看不到**对 trigger_summary / round / research_report 的读取

---

**验收门槛**:T1-T4 全部自动化通过 + T5 人工核对全勾,才算"Supervisor 是真的"。任何一项不过,视为回到上一版糊弄状态,必须返工。

---

### 4.2 Research Agent(真 ReAct)

#### 4.2.1 职责和输入输出

| 项 | 内容 |
|---|---|
| 节点类型 | LangGraph node,内部是 LangChain AgentExecutor / 自写 ReAct 循环 |
| 输入 | `state.last_decision.instructions` + `state.trigger_summary` |
| LLM | 强指令模型(gpt-4o 同类) |
| 工具 | 见 §4.2.3 |
| 输出 | `ResearchReport` Pydantic 对象,写入 `state.research_report` |
| 约束 | LLM 自主决定调用工具次数;`max_iterations=8` 作为保护上限,不作为正常停止信号 |

#### 4.2.2 Prompt 模板草稿(`config/prompts/research.md`)

```markdown
你是一个专业的 A 股市场数据研究员,使用 ReAct 模式工作。
你会收到 Supervisor 的研究任务,通过工具调用收集数据,
为 Screener Agent 准备完整的股票分析材料。

## ReAct 工作规范

- 每次 Thought 说清楚:为什么需要这个数据,预期用哪个工具
- 发现工具返回空或报错时,可以换一种方式再试一次;仍然失败则记入 data_gaps
- 不对数据做价值判断,只收集和如实整理
- 判断数据"已经够了"时主动停止,不需要把所有工具都调一遍

## data_gaps 规范

必须明确列出每只股票中未能获取的数据项:
✗ 错误:"部分数据不可用"
✓ 正确:["大股东近 6 个月增减持记录", "Q4 分红政策"]

## 输出格式

严格按照 ResearchReport Pydantic 模型输出 JSON,不要输出其他文字。

## 当前任务

### 触发信号
{{trigger_summary_json}}

### Supervisor 下达的研究指令
{{research_instructions}}

### 候选股票池(来自 mock 数据,供参考)
{{candidate_stocks_hint}}
```

#### 4.2.3 Tools 清单草稿(`config/tools/research_tools.json`)

```json
[
  {
    "name": "search_news_from_db",
    "description": "按关键词+时间窗口从已入库新闻中检索。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {
        "keywords": {"type": "string"},
        "hours": {"type": "integer", "default": 48}
      },
      "required": ["keywords"]
    }
  },
  {
    "name": "akshare_industry_leaders",
    "description": "查询某行业的龙头企业名单和市占率。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {"industry": {"type": "string"}},
      "required": ["industry"]
    }
  },
  {
    "name": "stock_financial_data",
    "description": "查询某股票的财务数据(营收、净利、PE)。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {"code": {"type": "string", "description": "6 位股票代码"}},
      "required": ["code"]
    }
  },
  {
    "name": "stock_holder_structure",
    "description": "查询某股票的前十大股东构成和聪明钱占比。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {"code": {"type": "string"}},
      "required": ["code"]
    }
  },
  {
    "name": "stock_technical_indicators",
    "description": "查询某股票的量能/MACD/均线等技术指标。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {"code": {"type": "string"}},
      "required": ["code"]
    }
  },
  {
    "name": "price_trend_data",
    "description": "查询某产品/商品的近期价格走势。MVP 返回 mock。",
    "input_schema": {
      "type": "object",
      "properties": {"product": {"type": "string"}},
      "required": ["product"]
    }
  }
]
```

#### 4.2.4 输出 Schema(`schemas/research.py`)

```python
from typing import List, Optional
from pydantic import BaseModel, Field

class StockDataEntry(BaseModel):
    code: str
    name: str
    industry: str
    leadership: Optional[str] = None        # 龙头地位描述
    holder_structure: Optional[str] = None
    financial_summary: Optional[str] = None
    technical_summary: Optional[str] = None
    price_benefit: Optional[str] = None     # 产品涨价受益描述
    data_gaps: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)   # 工具调用留痕

class ResearchReport(BaseModel):
    trigger_ref: str                        # 关联的 trigger id/描述
    candidates: List[StockDataEntry] = Field(..., min_length=1)
    overall_notes: Optional[str] = None
```

#### 4.2.5 真假验证方法

**测试 R1:LangSmith 单次 Research 执行内工具调用 ≥ 2 次**

```python
def test_research_makes_multiple_tool_calls():
    """真 ReAct 的标志是 LLM 自主进行多轮 tool→observation→tool。
    统计 LangSmith(或本地日志)里本次 Research 执行的 tool_call span 数。"""
    tool_call_count = run_research_once_and_count_tool_calls()
    assert tool_call_count >= 2, \
        f"Research 只调用了 {tool_call_count} 次工具,不像真 ReAct"
```

**测试 R2:Mock LLM"只调 1 次就 stop"对比**

```python
def test_stopping_after_one_tool_call_produces_different_report():
    """把 Research LLM 换成"第 1 次 tool 返回后立即停止"的 mock,
    与真实 LLM 的 ResearchReport 差异应当明显(data_gaps 更多、候选股票信息更残缺)。"""
    real_report = run_research_once(use_mock=False)
    shallow_report = run_research_once(use_mock=True, mock_stop_after=1)
    assert len(shallow_report.candidates[0].data_gaps) > len(real_report.candidates[0].data_gaps), \
        "提前停止应当产生更多 data_gaps,行为无差异疑似 Research 没真 ReAct"
```

**测试 R3:工具清单外置性测试**

从 `config/tools/research_tools.json` 里临时删除 `stock_technical_indicators`,重跑一次,确认 Research 的 `technical_summary` 字段变为 None 且 `data_gaps` 中出现技术面相关项。**不能改代码,只改 JSON**。

---

### 4.3 Screener Agent（单次 LLM 调用，无工具）

#### 4.3.1 职责和输入输出

| 项 | 内容 |
|---|---|
| 节点类型 | LangGraph node，**单次 LLM 调用**（非 ReAct），一次输出完整 ScreenerResult |
| 输入 | `state.research_report`（已结构化）+ `state.user_profile`（评估层+入场层条件，含权重） |
| LLM | 指令模型（gpt-4o 同类） |
| 工具 | **无** |
| 输出 | `ScreenerResult`，写入 `state.screener_result` |
| 为什么不做 ReAct | Research 已经把所有数据结构化交给 Screener；Screener 的任务是按条件 × 股票矩阵逐格打分，数据全部在手，没有需要"边思考边查"的环节。强加 ReAct 只会让 LLM 反复 lookup 自己已经拥有的数据，是凑数。 |

#### 4.3.2 Prompt 模板草稿（`config/prompts/screener.md`）

```markdown
你是一个专业的 A 股选股评分员。你的任务是根据用户的选股条件，
对 Research Agent 提供的候选股票进行逐条评分，输出完整的推理链。

## 评分规则

每个条件的满足度分三档：
  1.0 = 完全满足
  0.5 = 部分满足
  0.0 = 不满足或数据缺失

该条件得分 = 满足度 × 该条件权重
股票总分 = 所有条件得分之和（权重和应 ≈ 1.0）

推荐等级（用户门槛 {{recommendation_threshold}}）：
  ≥ {{recommendation_threshold}} → "推荐"
  0.50 ~ {{recommendation_threshold}} → "观察"
  < 0.50 → "不推荐"（仍要在输出里列出，但标注"不推荐"）

## 推理链规范

每个条件的评分必须附具体推理依据，引用 Research 报告里的原始数据：

✗ 错误："满足，股东结构良好"
✓ 正确："部分满足（0.5）。前十大股东中私募基金 2 家、个人投资者持股约 35%，
         合计约 58%，略低于 60% 门槛。数据来源：Research 报告 holder_structure 字段。"

数据缺失时，满足度给 0.0，推理链注明："数据缺失：Research 报告未提供该项数据，无法评估。"

## 输出格式

**一次性输出完整 ScreenerResult JSON**，覆盖所有候选股票 × 所有评估层+入场层条件。
不要分多轮输出，不要调用任何工具（你也没有工具）。

## 当前任务

### 用户选股条件（评估层 + 入场层，含权重，从 user_profile.json 注入）
{{scoreable_conditions_json}}

### 推荐分数门槛
{{recommendation_threshold}}

### Research Agent 提供的候选股票数据
{{research_report_json}}
```

#### 4.3.3 Tools 清单

Screener **没有** tools。对应配置文件 `config/tools/screener_tools.json` **不存在**。

#### 4.3.4 输出 Schema（`schemas/screener.py`）

```python
from typing import List, Literal
from pydantic import BaseModel, Field

class ConditionScore(BaseModel):
    condition_id: str
    condition_name: str
    satisfaction: Literal[0.0, 0.5, 1.0]
    weight: float
    weighted_score: float
    reasoning: str = Field(..., min_length=15)

class StockRecommendation(BaseModel):
    code: str
    name: str
    total_score: float
    recommendation_level: Literal["推荐", "观察", "不推荐"]
    condition_scores: List[ConditionScore]
    data_gaps: List[str] = Field(default_factory=list)
    trigger_ref: str

class ScreenerResult(BaseModel):
    stocks: List[StockRecommendation] = Field(..., min_length=1)
    threshold_used: float
```

#### 4.3.5 正确性验证方法

Screener 不是 ReAct，所以不验证"是否多次调工具"。验证目标是：**条件和权重真的来自 user_profile.json，而不是硬编码在 Prompt 或代码里**。

**测试 S1：user_profile 删除 C3 → 输出里 C3 消失（条件即数据）**

```python
def test_removing_C3_removes_C3_from_screener_output():
    """从 user_profile.json 中删除 C3，重跑，输出的 ScreenerResult 中每只股票
    的 condition_scores 里都不应出现 condition_id == 'C3'。"""
    profile = load_profile("config/user_profile.json")
    profile["conditions"] = [c for c in profile["conditions"] if c["id"] != "C3"]
    result = run_screener_with_profile(profile)
    for stock in result.stocks:
        ids = [cs.condition_id for cs in stock.condition_scores]
        assert "C3" not in ids, "C3 仍被打分，说明条件硬编码在 Prompt/代码里"
```

**测试 S2：user_profile 改 C2 权重 → 总分变化**

```python
def test_changing_C2_weight_changes_total_score():
    """把 C2 权重从 0.28 改为 0.05，同一只股票的 total_score 必然变化。
    若未变化，说明 Screener 没真用 user_profile 的权重数据。"""
    r1 = run_screener_with_profile_weight(C2=0.28)
    r2 = run_screener_with_profile_weight(C2=0.05)
    assert r1.stocks[0].total_score != r2.stocks[0].total_score
```

**测试 S3：每个 ConditionScore 的 reasoning 非空且 ≥ 15 字符**

```python
def test_screener_reasoning_is_substantive():
    """Pydantic schema 已强制 min_length=15；本测试是端到端兜底，
    确认 LLM 不是输出 '满足' / 'ok' 这类占位文本。"""
    result = run_screener_once()
    for stock in result.stocks:
        for cs in stock.condition_scores:
            assert len(cs.reasoning) >= 15
            assert cs.reasoning.strip() not in {"满足", "不满足", "部分满足"}
```

---

### 4.4 Skeptic Agent（单次 LLM 调用，无工具）

#### 4.4.1 职责和输入输出

| 项 | 内容 |
|---|---|
| 节点类型 | LangGraph node，**单次 LLM 调用**（非 ReAct），一次输出完整 SkepticResult |
| 输入 | `state.screener_result`（TOP5）+ `state.research_report` |
| LLM | 推理模型（o1-mini 同类，推理模型更擅长找漏洞） |
| 工具 | **无** |
| 输出 | `SkepticResult`，写入 `state.skeptic_result` |
| 为什么不做 ReAct | Skeptic 的所有输入（TOP5 评分链 + Research 原始报告）在被调用时已经完整到手，任务形态是"对既有材料做一次深度对抗推理"，不需要边想边查。推理模型的长思考链已经承担了"内部多轮思考"的职能，再套一层 ReAct 是重复。 |

#### 4.4.2 Prompt 模板草稿（`config/prompts/skeptic.md`）

```markdown
你是一个专业的风险分析师，专门为选股推荐结果做对抗性质疑。
你的职责是找出推理漏洞、数据盲区，以及当前市场环境下的特定风险。
你的目标不是否定推荐，而是让最终输出更完整、更诚实。

## 质疑范围

只对 Screener 评分最高的 TOP 5（或不足 5 的全部）进行质疑。

## 质疑类型（每条必须标注）

[logic_risk] 推理本身存在的缺陷，即使数据完整也成立
  示例："补贴政策落地到企业实际收益通常有 6-12 月时滞"
       "当前 PE=35，高于行业历史中位数 28，估值溢价明显"

[data_gap] Research 报告中缺失、且影响评分准确性的数据
  示例："Research 报告未包含大股东近 6 个月增减持记录"

## 质疑质量标准

✗ 不合格："市场存在不确定性，需谨慎"
✗ 不合格：重复 Screener 已写过的内容
✓ 合格：有具体数据、具体时间、具体机制支撑的质疑

每只股票至少输出 2 条质疑，[logic_risk] 和 [data_gap] 各至少 1 条（如都有）。

## 输出格式

**一次性输出完整 SkepticResult JSON**，覆盖全部 TOP5 的质疑。
不要调用任何工具（你也没有工具）。

## 当前任务

### TOP 候选（含 Screener 评分和推理链）
{{top_candidates_json}}

### Research 原始报告（可对照查找 data_gap）
{{research_report_json}}
```

#### 4.4.3 Tools 清单

Skeptic **没有** tools。对应配置文件 `config/tools/skeptic_tools.json` **不存在**。

#### 4.4.4 输出 Schema（`schemas/skeptic.py`）

```python
from typing import List, Literal
from pydantic import BaseModel, Field

class SkepticFinding(BaseModel):
    stock_code: str
    finding_type: Literal["logic_risk", "data_gap"]
    content: str = Field(..., min_length=20)

class SkepticResult(BaseModel):
    findings: List[SkepticFinding] = Field(..., min_length=2)   # 至少 2 条(TOP1 至少 1 条 logic + 1 条 data_gap)
    covered_stocks: List[str]    # 被质疑的股票 code
```

#### 4.4.5 正确性验证方法

Skeptic 不是 ReAct，所以不验证"是否调工具"。验证目标是：**输出的质疑有实质内容，且两种类型都有覆盖**。

**测试 K1：findings 必须覆盖至少 1 条 logic_risk + 1 条 data_gap**

```python
def test_skeptic_has_both_finding_types():
    r = run_skeptic_once()
    types = {f.finding_type for f in r.findings}
    assert {"logic_risk", "data_gap"}.issubset(types), \
        "Skeptic 只输出了一种类型，不像真在做对抗质疑"
```

**测试 K2：不同 Screener 输入产生不同 Skeptic 输出（防止 LLM 输出被缓存/写死）**

```python
def test_skeptic_output_varies_with_input():
    r1 = run_skeptic_once(screener_fixture="top5_policy_driven.json")
    r2 = run_skeptic_once(screener_fixture="top5_price_driven.json")
    findings1 = [f.content for f in r1.findings]
    findings2 = [f.content for f in r2.findings]
    assert findings1 != findings2, "Skeptic 对不同输入产出相同质疑，疑似写死"
```

**测试 K3：每条 finding 内容 ≥ 20 字符且非占位文本**（Pydantic 已强制，端到端兜底）

```python
def test_skeptic_findings_are_substantive():
    r = run_skeptic_once()
    for f in r.findings:
        assert len(f.content) >= 20
        assert "存在不确定性" not in f.content or len(f.content) > 30  # 泛泛话术要至少有具体展开
```

---

## 5. user_profile.json 格式

### 5.1 完整示例(父亲 7 个条件,按三层分类)

```json
{
  "user_id": "dad_001",
  "name": "老爸的策略",
  "conditions": [

    // ── 触发层(Trigger Layer)──────────────────────────────────────
    // 触发层条件无权重,MVP 里只作为文档性字段,供 Supervisor 读取理解"用户关心什么信号"
    {
      "id": "C1",
      "name": "政策支持",
      "layer": "trigger",
      "description": "有即时的新政策、新法律出台,明确支持该行业发展。关键看政策的落地确定性和力度——草案征求意见不算,正式发布才算。利好方向:补贴、减税、强制采购目录、行业准入放开。",
      "weight": null,
      "keywords": ["补贴", "减税", "政策落地", "实施细则", "采购目录"]
    },
    {
      "id": "C6",
      "name": "转折事件",
      "layer": "trigger",
      "description": "有明确的转折事件出现并推动行情,这是触发本次关注的直接催化剂。包括:政策正式落地、重要合同签订、行业拐点数据公布、公司重大人事变动等。",
      "weight": null,
      "keywords": ["正式落地", "签订合同", "拐点", "业绩预告", "重大公告"]
    },
    {
      "id": "C4-T",
      "name": "涨价信号(触发)",
      "layer": "trigger",
      "description": "市场出现行业性涨价信号——某类大宗商品或中间品价格连续上涨。此处只判断市场层面是否涨价,不判断具体公司是否受益(那是 C4-E 的工作)。",
      "weight": null,
      "keywords": ["价格上涨", "涨价", "供不应求", "库存下降"]
    },

    // ── 评估层(Screener Layer)──────────────────────────────────────
    // 权重和 = 0.85;加上入场层 C7 (0.15) 合计 1.00

    {
      "id": "C2",
      "name": "行业龙头",
      "layer": "screener",
      "description": "该股票的公司处于受政策支持的行业,且为龙头企业。判断依据:市占率行业前三、或细分领域第一、或营收规模行业领先。龙头企业在政策利好时往往获得最大受益,且资金首选。",
      "weight": 0.28
    },
    {
      "id": "C3",
      "name": "股东结构",
      "layer": "screener",
      "description": "前 10 大股东以私募股权投资和个人投资者为主,合计占流通股比重超 60% 以上。核心逻辑是看'聪明钱'是否入场。注意:外资、国企、社保持仓不算聪明钱;纯散户持股分散也不符合。前十大里有 3 个以上知名私募基金基本满足条件。",
      "weight": 0.15
    },
    {
      "id": "C4-E",
      "name": "产品涨价(评估)",
      "layer": "screener",
      "description": "该公司的核心产品正在受益于涨价,且涨价驱动力是供需不平衡(需求大、供应少)。需区分:供需驱动(持续性强,符合)vs 成本推动(持续性弱,不符合)。",
      "weight": 0.22
    },
    {
      "id": "C5",
      "name": "中期上涨趋势",
      "layer": "screener",
      "description": "在未来半年到一二年内,有明确的上涨趋势预期。判断依据:机构一致性预期向上、行业景气度上行周期、公司基本面持续改善。",
      "weight": 0.20
    },

    // ── 入场层(Entry Layer)──────────────────────────────────────
    // MVP 简化:入场层在 Screener 内部作为普通条件打分,不做硬门槛

    {
      "id": "C7",
      "name": "技术突破",
      "layer": "entry",
      "description": "在交易上有明显的技术上涨特征,有量能突破。判断依据:成交量突破近 20 日均量 1.5 倍以上、价格突破关键压力位(前高、均线)、MACD 金叉或趋势向上。量能是关键——没量的突破不可信。",
      "weight": 0.15
    }
  ],
  "advanced_settings": {
    "recommendation_threshold": 0.65,
    "trading_style": "medium"
  }
}
```

### 5.2 Screener 如何从此文件动态拼 Prompt

**不允许**把条件文本写死在 `prompts/screener.md` 里。运行流程:

```python
# agents/screener.py (伪代码)
profile = json.load(open("config/user_profile.json"))
scoreable = [c for c in profile["conditions"] if c["layer"] in ("screener", "entry")]

scoreable_json = json.dumps([
    {
        "id": c["id"],
        "name": c["name"],
        "description": c["description"],   # ← 用户文本原样注入
        "weight": c["weight"]
    }
    for c in scoreable
], ensure_ascii=False, indent=2)

prompt_template = open("config/prompts/screener.md").read()
prompt = prompt_template.format_map({
    "scoreable_conditions_json": scoreable_json,
    "recommendation_threshold": profile["advanced_settings"]["recommendation_threshold"],
    "research_report_json": state.research_report.model_dump_json(indent=2)
})
```

**关键验证**(同 §4.3.5 测试 S2):从 JSON 里删掉 C3,不改任何代码,Screener 输出的 `condition_scores` 里应不再出现 C3。

Supervisor 读取 user_profile 时做类似处理,但可以读全部条件(包括触发层),以便在决策里引用条件 id。

---

## 6. Markdown 输出格式规范

### 6.1 输出位置

`outputs/runs/run_{YYYYMMDD}_{HHMMSS}.md`,每次 `main.py` 运行生成一份。

### 6.2 finalize 节点的 Markdown 模板

参考原 PRD §7.3 的文字界面,**但使用 Markdown 原生元素**(标题、列表、表格、引用),**不再使用 ASCII 盒线**——Markdown 预览器渲染更干净。

模板(变量部分由 finalize 节点填入):

```markdown
# 今日推荐 — {{date}}

> 运行时间:{{run_timestamp}}
> Trigger 数:{{trigger_count}}
> LangSmith Trace:{{langsmith_url}}

## 触发信号概览

{{#triggers}}
### {{trigger_index}}. {{trigger_headline}}

- **行业**:{{industry}}
- **类型**:{{type}}
- **强度**:{{strength}}
- **来源**:{{source}}
{{/triggers}}

---

## 推荐列表(按 Screener 总分降序)

| 代码 | 名称 | 总分 | 等级 | 关联触发 |
|---|---|---|---|---|
{{#stocks}}
| {{code}} | {{name}} | {{total_score}} | {{level}} | {{trigger_ref}} |
{{/stocks}}

---

## 每只股票分析链路

{{#stocks_detail}}
### {{name}} {{code}} — 总分 {{total_score}} [{{level}}]

#### ① 触发来源

{{trigger_reference}}

#### ② Research Agent 调研摘要

- **行业龙头**:{{leadership}}
- **股东结构**:{{holder_structure}}
- **财务**:{{financial_summary}}
- **技术面**:{{technical_summary}}
- **产品涨价受益**:{{price_benefit}}

{{#if data_gaps}}
> ⚠️ 数据缺口:{{data_gaps_joined}}
{{/if}}

#### ③ Screener 评分明细

| 条件 | 权重 | 满足度 | 得分 | 推理 |
|---|---|---|---|---|
{{#condition_scores}}
| {{condition_id}} {{condition_name}} | {{weight}} | {{satisfaction}} | {{weighted_score}} | {{reasoning}} |
{{/condition_scores}}

#### ④ Skeptic 质疑

{{#findings_for_this_stock}}
- **[{{finding_type}}]** {{content}}
{{/findings_for_this_stock}}

#### ⑤ Supervisor 综合判断

> {{supervisor_notes}}

---

{{/stocks_detail}}

## 本次运行元信息

- Supervisor 决策轮次:{{supervisor_rounds}}
- 子 Agent 调用次数:Research × {{research_calls}},Screener × {{screener_calls}},Skeptic × {{skeptic_calls}}
- 总耗时:{{total_duration_sec}}s
- LangSmith Trace(决策链完整可查):{{langsmith_url}}

```

### 6.3 对比原 PRD §7.3 的差异

| 原 PRD 元素 | MVP Markdown 处理 |
|---|---|
| ASCII 盒线框(`┌─ ... ─┐`)| 改用 Markdown 分隔线(`---`)+ 小标题 |
| 进度条(`████████░░`)| 改用数字 `0.28/0.28` 或表格,不渲染图形进度条 |
| 历史准确率标注(`[历史准确率 75%]`)| MVP 无此数据,不显示 |
| 跨日联动标签(`连续推荐 3 天`)| MVP 无历史,不显示 |
| 点击交互(`[查看分析链路 →]`)| Markdown 静态展开,所有股票的分析链路都直接列出 |
| 触发强度图标(📋)| Markdown 不强制使用 emoji,保留 `⚠️` 用于数据缺口即可 |

---

## 7. 验收标准(MVP 版)

### 7.1 每个 Agent 的独立验收

| Agent | 验收项 | 对应测试 |
|---|---|---|
| Supervisor | 条件边无业务 if-else | T1 |
| Supervisor | Mock LLM 替换后行为变化 | T2 |
| Supervisor | 不同 trigger 产生不同路由 | T3 |
| Supervisor | reasoning 字段非空且非占位 | T4 |
| Supervisor | LangSmith trace 人工核对通过 | T5 |
| Research（★ 唯一 ReAct）| 单次执行 ≥ 2 次工具调用 | R1 |
| Research | 提前停止行为差异显著 | R2 |
| Research | Tool 清单外置生效 | R3 |
| Screener（单次 LLM）| 删除条件驱动输出变化（条件即数据） | S1 |
| Screener | 改权重驱动分数变化 | S2 |
| Screener | reasoning 字段有实质内容 | S3 |
| Skeptic（单次 LLM）| findings 覆盖 logic_risk + data_gap 两种类型 | K1 |
| Skeptic | 输入变化驱动输出变化 | K2 |
| Skeptic | findings 内容非占位文本 | K3 |

### 7.2 整体系统的验收

- [ ] **E1**:`python main.py` 从零跑通一次,无崩溃,产出一份 `outputs/runs/run_*.md`,里面有至少 1 条推荐、1 段 Screener 推理链、1 段 Skeptic 质疑、1 段 Supervisor notes
- [ ] **E2**：LangSmith 项目里对应 trace 完整可见（Supervisor 多轮 LLM 决策 + Research ReAct 循环 + Screener/Skeptic 的单次 LLM 调用 span）
- [ ] **E3**:修改 `config/user_profile.json` 删除 C3,重跑,Markdown 输出中所有股票的 Screener 评分表里都不再出现 C3 行
- [ ] **E4**:修改 `config/prompts/supervisor.md` 加一句"请用英文输出 reasoning",重跑,LangSmith 里能看到该指令生效(reasoning 变英文),说明 Prompt 真的从文件加载
- [ ] **E5**:修改 `config/tools/research_tools.json` 删掉 `stock_technical_indicators`,重跑,Research 的 technical_summary 为 None 且 data_gaps 出现技术面项
- [ ] **E6**:所有 `tests/` 下的自动化测试本地运行一键通过

### 7.3 Supervisor 真实性验收(★ 最关键,单独列出)

这一节是 MVP 的灵魂——如果这一节不过,整个 MVP 视为失败、需要返工,无论其他部分多完整。

**必须同时满足**:

1. ✅ **代码层**:`graph/edges.py::route_from_supervisor` 的函数体只读 `state.last_decision.action`,静态分析(T1)通过
2. ✅ **行为层**:Mock LLM 替换测试(T2)通过——替换后系统 dispatch 序列必然改变
3. ✅ **输入敏感**:不同 trigger 驱动不同路由(T3)——证明 LLM 在"看"输入做决定
4. ✅ **推理留痕**:每次决策带 ≥ 20 字符、非占位的 `reasoning`(T4)
5. ✅ **可追溯**:LangSmith 上可逐轮审查 Supervisor 的 prompt、completion、推理(T5)
6. ✅ **可证伪**:当上面任何一条被破坏(例如有人把 route 改成固定顺序),测试会自动失败

**反面描述**(如果出现以下任一症状,视为回到上一版糊弄状态):

- ✗ `route_from_supervisor` 里出现 `if state["round"] == 1:` 或 `if trigger["strength"] == "strong":` 这样的业务判断
- ✗ Supervisor 节点是同步函数直接 `return "dispatch_research"`,没有真的 LLM call span
- ✗ 不论输入什么 trigger,dispatch 序列永远是 research→screener→skeptic→finalize 这个顺序(精确相等)
- ✗ `reasoning` 字段为空、固定字符串("ok"、"next")、或每次完全相同
- ✗ 去掉 LLM API key 后流程仍能跑完

---

## 附录 A：实施步骤（7 步，节奏自定）

> 下面是建议的实施**顺序**和每步"做完"的标准。**不按天切**——你一个周末冲完，还是分散一周晚上都可以。
> **关键是顺序不要乱**：每一步都建立在前一步基础上。某一步卡住，先修这一步，不要跳过往下做。
> 整个骨架先行，假货先让管道通，再一个一个换成真货。

---

### 第 1 步：搭骨架（最关键的一步）

**做什么：**

- 建好目录结构（§3.1）、装依赖、配好 OpenAI API key 和 LangSmith API key
- 写全部 Pydantic 数据模型（`schemas/` 下 5 个文件）
- 4 个 Prompt 文件先建空文件（`config/prompts/*.md`，里面只写 `TODO`）
- 4 个节点全部用"假的"实现（不调 AI，直接返回写死的 Pydantic 对象）
- **假 Supervisor 要有台词本**：第 1 轮返回"去调研"，第 2 轮返回"去打分"，第 3 轮返回"去挑刺"，第 4 轮返回"结束"。这样整条流水线 4 站能完整走一遍。
- 写"岔路口规矩检查"（T1，静态扫代码那个小脚本）并通过
- 写金丝雀测试：只检查 `python main.py` 能跑完并产出一份 Markdown

**做完的标准：**

- `python main.py` 能跑完，`outputs/runs/` 下有一份 Markdown
- 金丝雀测试通过
- T1 通过
- 打开 LangSmith，能看到 4 个节点的 trace（哪怕全是假节点）

**为什么放第一步：**

- 管道通不通，最开始就要知道，不能拖到最后发现接口对不上
- Pydantic 数据模型一次锁死，后面换真货时不会改动接口
- LangGraph 的 API 坑要尽早踩；踩到了还有时间查
- 金丝雀从此每步收工前都要跑——它还活着 = 管道没塌

---

### 第 2 步：Supervisor 变真

**做什么：**

- 把 `config/prompts/supervisor.md` 从 TODO 填成真的系统提示词（§4.1.2）
- 把 supervisor 节点从"假的台词本"换成真的 LLM 调用
- 跑测试 T2（换成 mock LLM 行为会变化）、T3（不同触发信号走不同路径）、T4（reasoning 字段非空非占位）

**做完的标准：**

- T1、T2、T3、T4 全部通过
- 金丝雀仍然跑通（**关键**——不能为了上真 Supervisor 把管道搞塌）
- 打开 LangSmith，能看到 Supervisor 每轮的真实 LLM 调用和 reasoning

**为什么第 2 步：**

- Supervisor 是风险最高的组件（上一版被糊弄的正是它）
- 越早上真，越有时间救火
- 其他子 Agent 还是假的，但假版本输出足够 Supervisor 判断"下一步做什么"

---

### 第 3 步：Research Agent 变真（唯一 ReAct）

**做什么：**

- 填 `config/prompts/research.md`
- 填 `config/tools/research_tools.json`（6 个 mock 工具的清单）
- 在 `tools/mock_research_tools.py` 写 6 个 mock 工具（返回固定假数据即可）
- 把 research 节点从"假的"换成真的 ReAct（LangChain AgentExecutor）
- 跑 R1（单次执行工具调用 ≥2 次）、R2（提前停止对比）、R3（改工具清单 JSON 行为会变）

**做完的标准：**

- R1、R2、R3 通过
- T1-T4 和金丝雀仍然通过
- LangSmith 上能看到 Research 内部的多轮"思考→工具→观察"循环

**为什么第 3 步：**

- Screener 和 Skeptic 消费 Research 的输出，Research 的输出结构必须先稳定

---

### 第 4 步：Screener 变真（单次 LLM）

**做什么：**

- 填 `config/prompts/screener.md`
- 运行时从 `config/user_profile.json` 读出评估层+入场层条件，拼进 Prompt（§5.2）
- 一次 LLM 调用直接输出 ScreenerResult
- 跑 S1（删掉 C3 → Markdown 里 C3 消失）、S2（改权重 → 分数变化）、S3（推理非占位）

**做完的标准：**

- S1、S2、S3 通过
- 前面所有测试、金丝雀仍然通过

**为什么第 4 步：**

- Skeptic 要用 Screener 的 TOP5，Screener 得先完成

---

### 第 5 步：Skeptic 变真（单次 LLM）

**做什么：**

- 填 `config/prompts/skeptic.md`
- 一次 LLM 调用直接输出 SkepticResult
- 跑 K1（两种类型都覆盖）、K2（不同输入不同输出）、K3（内容非占位）

**做完的标准：**

- K1、K2、K3 通过
- 前面所有测试、金丝雀仍然通过

---

### 第 6 步：端到端打磨 + 验收

**做什么：**

- 跑 T5（人工审查 LangSmith trace 清单，见 §4.1.5）
- 跑 E1-E6 整体验收（§7.2）
- 调 Markdown 模板，确保输出读起来顺、信息齐

**做完的标准：**

- §7.1、§7.2、§7.3 所有勾全打上

---

### 第 7 步：收尾

**做什么：**

- 写 README：怎么装依赖、怎么配 API key、怎么跑、配置文件在哪改
- 写好 `.env.example`
- 清理临时日志、废弃文件

**做完的标准：**

- 一个新人 clone 下来，照 README 能跑通

---

## 附录 B:面试演示脚本(非规范,仅供作者参考)

演示时长 3-5 分钟,按以下顺序:

1. **展示架构图**(§2.1 的 ASCII):"这是一个 LangGraph Supervisor 循环,4 个 LLM 决策点都是真的"
2. **打开 LangSmith**:指着一次真实 trace 说"Supervisor 在这里、这里、这里各做了一次决策,每次都是一次 LLM call,reasoning 都不一样"
3. **打开 Markdown 产物**:快速念一只股票的评分链路和 Skeptic 质疑
4. **现场改 user_profile.json**:删掉 C3,重跑,展示 Markdown 里 C3 消失——"条件是数据不是代码"
5. **现场跑 Mock 测试**:`pytest tests/test_supervisor_is_real.py -v`,指着 T2 说"如果 Supervisor 不是真的,这个测试会挂"

---

*文档结束。做完回看此文，如果哪一步没做到，看看是哪个约束被妥协了。*
