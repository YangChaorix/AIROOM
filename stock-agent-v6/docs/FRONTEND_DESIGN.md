# Stock Agent v6 — 前端设计方案 v3（定版）

> 版本：2026-04-19（v3 定版，替代 v1/v2）
> 基调：**时间线为主视觉语言** + Agent 头像全局可编辑 prompt + 无 Chat 对话
> 技术栈：React 19 + Vite + 纯内联 CSS + FastAPI + SSE + **Docker 部署**
> 参考：`test/agent team/agent-team_1.jsx` 的色系/动画/气泡 CSS

---

## 〇、v3 最终决策（10 项全部定版）

| # | 决策 | 最终选择 |
|---|---|---|
| 1 | 4 视图划分 | 主页 / 推荐 / 个股 / 配置 ✅ |
| 2 | 视觉语言 | 时间线 + 结果卡片（不是工位）✅ |
| 3 | Chat 对话 | 不要 ✅ |
| 4 | Prompt 编辑 | 点 Agent 头像全局浮层触发 ✅ |
| 5 | 启动方式 | `uvicorn api.main:app` + `npm run dev` 两进程（开发），**Docker 部署（生产）** ✅ |
| 6 | 部署场景 | **Docker 镜像**（前后端 + SQLite 一镜像打包） ✅ |
| 7 | Prompt 版本化 | **DB 存版本（`prompt_versions` 表）**，每次保存生成 `YYYYMMDDXXXX` 版本号；不碰 git ✅ |
| 8 | 主页"今日概览" | **保留** ✅ |
| 9 | "问 AI" 全局入口 | **不做** ✅ |
| 10 | Cron 自然语言转换 | **不做**；用户编辑 `config/news_channels.json` 写标准 cron 即可 ✅ |

---

## 一、原 v1 → v2 差异（保留作历史参考）

| # | 决策 | 对应改动 |
|---|---|---|
| 1 | 4 视图划分合理（主页 / 推荐 / 个股 / 配置） | 保持 |
| 2 | **"时间线"比喻**（不是工位） | 主页删除"Agent 工位"布局；改为时间线为核心，Agent 状态嵌在时间线节点上 |
| 3 | 不要 Chat 对话框 | 删除所有聊天输入框 / @mention / 频道；气泡 CSS 只作为"Agent 输出展示"样式 |
| 4 | 点 Agent 头像/logo 在线编辑 prompt | 顶栏放 5 个 Agent 头像 **全局可见**；点击→浮层编辑 prompt；**配置视图删掉 Prompt tab** |

---

## 二、核心视觉语言：时间线

整个前端只有**两种**主视觉元素：

### 2.1 时间线节点（Timeline Node）

左侧一条垂直色条 + 节点圆点 + 右侧气泡。每个节点 = 一次 Agent 激活 或 一次工具调用。

```
┃  ●  Supervisor R1                10:32:14   [2.3s]
┃  │  🟦 dispatch_research
┃  │  "第 1 轮默认调 Research 收集数据，当前 trigger 强度 high..."
┃  │
┃  ●  Research                     10:32:16   [3:42s]
┃  │  🟨 6 次工具调用 / 3 只候选股
┃  │    ├ akshare_industry_leaders(新能源储能)        ✓ 820ms
┃  │    ├ stock_financial_data(300750)               ✓ 1.2s
┃  │    ├ stock_holder_structure(300750)             ✓ 0.9s
┃  │    ├ stock_technical_indicators(300750)         ✓ 0.7s
┃  │    ├ stock_financial_data(300274)               ✓ 1.1s
┃  │    └ stock_holder_structure(300274)             ✗ 超时
┃  │
┃  ●  Supervisor R2                10:36:00   [2.1s]
┃  ●  Screener                     10:36:02   [48s]
┃  ●  Supervisor R3                10:36:50   [1.9s]
┃  ●  Skeptic                      10:36:52   [31s]
┃  ●  Supervisor R4 → finalize     10:37:23   [2.2s]
```

**状态可视化**：
- 运行中的节点：圆点**呼吸脉冲**（`ringPulse` 动画）+ Dots 三点跳动
- 已完成：实心圆点 + 绿勾 ✓
- 失败：红色圆点 + ✗
- 排队中（pending 的 trigger）：空心圆点 + 灰色

### 2.2 结果卡片（Result Card）

推荐股卡片、触发信号卡片、系统日志卡片都用同一套卡片基础样式：

```
┌─────────────────────────────────┐
│ 🎯 <标题>            <次要元信息> │
├─────────────────────────────────┤
│ <主要内容>                        │
│                                  │
│ [折叠区 1 ⌄] [折叠区 2 ⌄]         │
└─────────────────────────────────┘
```

- 14px 圆角、1px 米边框 `#D8D1C4`、白底 95% 透明
- 折叠区默认收起，点击展开不刷新页面

**只有时间线和卡片两种**——视觉极简，便于 AI PM 理解 + 修改。

---

## 三、全局布局（所有视图共享）

```
┌──────────────────────────────────────────────────────────────────┐
│  Stock Agent v6   🟦Supervis  🟨Research  🟢Screener  🟥Skeptic  🟦Trig  │ ← 顶栏
│                     点击任一头像 → 浮层编辑该 Agent 的 prompt            │
├───────────────┬──────────────────────────────────────────────────┤
│ 🏠 主页       │                                                  │
│ 📋 推荐        │              <视图内容>                            │
│ 📊 个股        │                                                  │
│ ⚙️ 配置       │                                                  │
│               │                                                  │
│ ──            │                                                  │
│ 🔴 Pending 3  │                                                  │
│ 🟡 Process 1  │                                                  │
│ ✅ Done 42    │                                                  │
│ [▶ 消费]      │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```

### 3.1 顶栏：5 个 Agent 头像（全局常驻）

**视觉**：

```
🟦Supervisor  🟨Research  🟢Screener  🟥Skeptic  🟦TriggerAgent
  │            │           │           │           │
  └─ 工作中：边框呼吸脉冲 ──────────────────────────┘
  └─ 空闲：灰度 + 微浮动
```

**交互**：
- 悬停：显示 tooltip（该 Agent 最近 1 次调用的 run_id 和耗时）
- 点击：弹出**浮层 `<PromptEditor agent="supervisor" />`**
  - 内容：`config/prompts/supervisor.md` 的 monaco editor
  - 底部：`[保存]`（PUT `/api/prompts/supervisor`）/ `[保存并试跑]`（保存 + 触发 `main.py default` 一次看效果）/ `[取消]`
  - 警告条："保存后立即影响下次 run 的 LLM 行为"
- 实时状态：SSE 推送时更新头像脉冲动画

### 3.2 左侧栏：导航 + 队列条

- 4 个视图入口
- 分隔线下方**队列实时计数**（红/黄/绿数字）+ "消费下一个"按钮（POST `/api/queue/consume?n=1`）

---

## 四、4 视图详设

### 4.1 🏠 主页 —— 时间线中心化

**取代 v1 的"Agent 工位"**。主页就是**最近 5 个 runs 的叠加时间线**，让你一眼看到"系统在忙什么/忙完了什么"。

```
┌─────────────────────────────────────────────────────────┐
│ 今日概览                                                 │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 📋 新闻入库: 612  ↑ 35 (vs 昨日)                      │ │
│ │ 🎯 Trigger 生成: 4 (skip 7)                           │ │
│ │ 🎉 完成分析: 3   ❌ 失败: 0                            │ │
│ │ 📰 推荐 recommend 级: 2  观察 watch: 4  跳过 skip: 3   │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ 最近 5 个 runs                                           │
│ ┃ ● Run 46  10:37  Trigger: 发改委储能补贴...             │
│ ┃   └ 🟦●🟨●🟢●🟥●🟦  5 nodes, 7m 9s  [推荐 1 只]  ↗      │
│ ┃ ● Run 45  10:05  Trigger: 电网公司发布xx...             │
│ ┃   └ 🟦●🟨●🟢●🟥●🟦  [观察 2 只]  ↗                     │
│ ┃ ● Run 44  09:30  [skipped by trigger agent]           │
│ ┃ ● Run 43  (processing) ⚡ 已运行 2:14                   │
│ ┃   └ 🟦✓ 🟨⏵ — 当前 Research 中                          │
│ ┃ ● Run 42  08:15  ...                                   │
│                                                         │
│ [点击任一 run → 进入 📋 推荐详情]                         │
│                                                         │
│ 实时事件流（SSE）                                         │
│ ▼ 10:37:45  agents.trigger  生成 trigger 5 priority=8     │
│   10:37:30  main.consume    run 46 completed              │
│   10:35:10  scheduler.news  news_cctv  +12 新闻          │
│   10:33:22  tool_call       stock_financial_data(300750)  │
│   10:32:14  run started     trigger 4 dispatched          │
└─────────────────────────────────────────────────────────┘
```

**AI 原生细节**：
- 事件流从顶部**渐入新增**（300ms 从 opacity 0 → 1）
- Run 行如果正在 processing，整行**左侧色条脉冲**
- "今日概览"的数字**从 0 roll up**（第一次加载时动画）

### 4.2 📋 推荐详情 —— 时间线主场

**路径**：`/runs/:run_id`。核心视觉是 §二 的完整时间线。

**结构**：

```
┌─────────────────────────────────────────────────────────┐
│ ← Run #46 · 2026-04-19 10:37 · completed · 7m 9s         │
├─────────────────────────────────────────────────────────┤
│ 🎯 触发信号卡片                                          │
│   [policy_landing · high · priority 10]                  │
│   "发改委明确新型储能补贴细则，5月起执行"                  │
│   引用新闻 1 条 [⌄]                                       │
├─────────────────────────────────────────────────────────┤
│ ━━━━━ Agent 时间线 ━━━━━                                  │
│ <§2.1 所示完整时间线>                                      │
├─────────────────────────────────────────────────────────┤
│ ━━━━━ 推荐结果 ━━━━━                                      │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ ⭐ 宁德时代 300750                   0.68 [推荐]    │ │
│ │ 💡 推荐理由: ...                                     │ │
│ │ 👍 核心优势 3 条    ⚠️ 核心风险 2 条                 │ │
│ │ [5 条件打分 ⌄] [Skeptic 2 条质疑 ⌄]                 │ │
│ │ [🔗 LangSmith Trace]                                │ │
│ └─────────────────────────────────────────────────────┘ │
│ [阳光电源 0.53 观察] [比亚迪 0.28 跳过]                    │
├─────────────────────────────────────────────────────────┤
│ ━━━━━ Supervisor 综合判断 ━━━━━                          │
│ "储能补贴落地强度高..."                                    │
├─────────────────────────────────────────────────────────┤
│ ━━━━━ 横向对比摘要（Screener）━━━━━                       │
│ "本批三只候选股均属新能源储能板块..."                      │
└─────────────────────────────────────────────────────────┘
```

**AI 原生细节**：
- 时间线节点点击 → **右侧抽屉**展开该 Agent 的完整输出（iMessage 气泡样式）
- Research 节点展开后，**6 次工具调用逐个渐入**（0.1s 间隔），重现当时的"Agent 在思考"过程
- 推荐股卡片首次可见时**依次弹入**（而非瞬间全出）

### 4.3 📊 个股视图 —— 启动→观察→回溯

```
┌─────────────────────────────────────────────────────────┐
│ 分析哪只股票？                                            │
│ [ 300750 或 宁德时代 ___________ ]  [🚀 分析]            │
│ ☑ 拉行业对标股做横向对比                                  │
└─────────────────────────────────────────────────────────┘

点击 🚀 后：
┌─────────────────────────────────────────────────────────┐
│ 🔄 Run 47 正在分析宁德时代（对标 阳光电源、比亚迪）        │
│                                                         │
│ <§2.1 时间线实时填充>                                      │
│ ┃ ● Supervisor R1  ✓ dispatch_research                    │
│ ┃ ● Research       ⏵ 工具调用中 3/8 ...                   │
│ ┃ ○ Screener       (等待中)                               │
│ ┃ ○ Skeptic                                              │
│                                                         │
│ 预计 3-5 分钟 · [🔗 LangSmith 实时 trace]                 │
└─────────────────────────────────────────────────────────┘

分析完成 / 页面下方：
┌─────────────────────────────────────────────────────────┐
│ 📜 宁德时代历史分析                                        │
│ ┌──────────────────────────────────────┐                │
│ │ 2026-04-19  primary  0.28 skip      │ ← Run 47        │
│ │ 2026-04-19  candidate 0.68 recommend│   Run 46        │
│ │ 2026-04-18  peer     0.50 watch      │   Run 45        │
│ └──────────────────────────────────────┘                │
│                                                         │
│ [点击某行 → 进入 📋 推荐详情]                              │
└─────────────────────────────────────────────────────────┘
```

**AI 原生细节**：
- Agent 时间线节点**实时 SSE 填充**（不是等待 5 分钟才整体刷出）
- 完成后本视图**自动跳转**到该 run 的推荐详情

### 4.4 ⚙️ 配置视图 —— 只有 2 tab（删除 Prompt tab）

Prompt 编辑改为顶栏 Agent 头像浮层触发（§3.1），这里只管**数据驱动业务行为**的两项配置：

**Tab A：用户条件**

表格视图，支持编辑权重 / 软删 / 新增条件：

```
| ID   | 名称          | 层      | 权重 | active | 关键词         |
|------|---------------|---------|------|--------|----------------|
| C1   | 政策支持      | trigger | -    | ✓     | 补贴,减税,... |
| C2   | 行业龙头      | screener| 0.28 | ✓     |                |
| C3   | 股东结构      | screener| 0.15 | ✓     |                |
| ...  | ...           | ...     | ...  |       |                |
| [+ 新增条件]                                              |
```

改动 → PUT `/api/conditions/:id` → 下次 Screener run 生效。

**Tab B：新闻渠道**

7 个 AkShare 渠道列表：

```
| 渠道              | 接口                         | cron           | ✓启用 | 上次抓取        | 操作         |
|-------------------|------------------------------|----------------|-------|-----------------|--------------|
| 央视网            | news_cctv                    | 每天 08:00     |  ✓    | 2h 前 12 条     | [▶ 立即抓]   |
| 东财-财经早餐     | stock_info_cjzc_em           | 每天 07:00     |  ✓    | 3h 前 400 条    | [▶ 立即抓]   |
| 东财-全球资讯     | stock_info_global_em         | 盘中每小时     |  ✓    | 5m 前 8 条新增  | [▶ 立即抓]   |
| ...                                                                                        |
| [+ 新增渠道]                                                                               |
```

每行可 enable/disable + 编辑 cron + 立即抓取按钮。

---

## 五、Prompt 编辑浮层（§3.1 点击 Agent 头像触发）

**路径**：顶栏头像 onClick → 全屏浮层（不是新页面，保持上下文）

```
╔═════════════════════════════════════════════════════════╗
║ ✏️ 编辑 Research Agent 的 Prompt                  [✕]   ║
║ ─────────────────────────────────────────────────────── ║
║ ⚠️ 保存后影响下次 Research 调用的 LLM 行为                ║
║                                                         ║
║ ┌─────────────────────────────────────────────────────┐ ║
║ │ 你是一个专业的 A 股市场数据研究员，使用 ReAct...      │ ║
║ │                                                     │ ║
║ │ [Monaco editor 支持 Markdown 语法高亮 + 占位符高亮]  │ ║
║ │                                                     │ ║
║ └─────────────────────────────────────────────────────┘ ║
║                                                         ║
║ 占位符：{trigger_summary_json} {research_instructions} ║
║         {candidate_stocks_hint}                         ║
║                                                         ║
║ 历史版本 [git log 📜]（每次保存自动 commit）             ║
║                                                         ║
║         [取消]    [保存]    [保存并试跑一次]              ║
╚═════════════════════════════════════════════════════════╝
```

**后端**：
- GET `/api/prompts/:agent` → 返回当前文件内容
- PUT `/api/prompts/:agent` → 原子写入 + 可选 auto-commit
- POST `/api/prompts/:agent/test` → 触发 `main.py default`（快速模式）再返回 run_id

**安全考虑**：
- 浮层里做简单 lint（提示缺失必填占位符）
- 保存前 diff 预览（与当前文件对比）
- 每次保存自动写一个 git commit（无需用户操作），**可随时 revert**

---

## 六、技术栈（v2）

| 层 | 选型 | 备注 |
|---|---|---|
| 前端框架 | React 19 + Vite | 与 agent-team 一致 |
| 样式 | 纯内联 CSS + `<style>` | 不引 Tailwind |
| 路由 | React Router v6 | 4 视图简单切换 |
| Monaco Editor | `@monaco-editor/react` | Prompt 浮层用；其他地方不用 |
| SSE | 原生 `EventSource` | 单向推送，代码极简 |
| 字体 | DM Mono + Noto Serif SC | CDN 加载 |
| 后端 | FastAPI + Uvicorn | 与项目代码同仓，共用 db repos |
| 实时推送 | SSE（`/api/stream`）| 后端轮询 DB + 读 system_logs 作为事件源 |
| 启动 | `uvicorn api.main:app` + `npm run dev` | 两进程；未来 Tauri 打包 |

---

## 七、API 层（FastAPI 端点清单）

| 端点 | 方法 | 描述 | 数据源 |
|---|---|---|---|
| `/api/runs` | GET | 最近 N 条 run | runs 表 |
| `/api/runs/:id` | GET | 某 run 的完整时间线 + 推荐 | v_recommendation_trace + agent_outputs + tool_calls |
| `/api/runs/:id/stream` | GET (SSE) | 该 run 执行中的实时事件 | agent_outputs / tool_calls 轮询 |
| `/api/queue` | GET | pending / processing / completed 计数 | triggers |
| `/api/queue/consume?n=1` | POST | 触发 main --consume | 启子进程 |
| `/api/stock` | POST | 个股分析 `{code_or_name, with_peers}` | 启子进程跑 main.run(stock=...) |
| `/api/stocks/:code/history` | GET | 某股 v_stock_analysis_history | view |
| `/api/conditions` | GET/PUT | 条件增删改 | conditions 表 |
| `/api/channels` | GET/PUT | 渠道配置读写 | news_channels.json |
| `/api/channels/:name/run` | POST | 立即抓一次 | scheduler.tasks.fetch_channel |
| `/api/prompts/:agent` | GET/PUT | Prompt 文件读写 | config/prompts/*.md |
| `/api/prompts/:agent/test` | POST | 保存后快速试跑 | main.run(trigger_key="default") |
| `/api/agents/status` | GET | 5 Agent 最近 5 分钟活动摘要（用于顶栏头像脉冲）| agent_outputs 最近数据 |
| `/api/stream` | GET (SSE) | 全局事件流（system_logs + agent_outputs 新增）| 轮询 |
| `/api/logs?level=error&limit=50` | GET | 系统日志 | system_logs |

---

## 八、复用 agent-team 的 5 个 CSS 模式（与 v1 一致）

1. `ringPulse` Agent 工作脉冲 → **时间线节点正在运行时的圆点动画**
2. `Dots` 3 点跳动 → **"Supervisor 正在思考..."、"Research 调用中..."**
3. iMessage 气泡 → **时间线节点展开时的 Agent 输出样式**
4. 缩进层级 → **Research 的 tool_calls 缩进 12px、Supervisor→子 Agent 缩进 24px**
5. 浮动 Emoji → **顶栏 Agent 头像空闲时的微浮动装饰**

---

## 九、实施路线图（6 步，约 3.5 天）

| 步骤 | 内容 | 工作量 | 里程碑 |
|---|---|---|---|
| F1 | FastAPI 后端：14 个端点 + SSE | 0.6d | 后端跑通（无前端） |
| F2 | React + Vite 初始化 + 路由 + 全局样式（顶栏 Agent 头像 + 左侧导航 + 队列条）| 0.4d | 壳跑起来 |
| F3 | 🏠 主页（今日概览 + 最近 runs 叠加时间线 + SSE 事件流）| 0.6d | 看到"系统在动" |
| F4 | 📋 推荐详情（完整时间线 + 节点抽屉 + 推荐卡片）| 0.9d | 核心价值视图 |
| F5 | 📊 个股视图（输入 → 实时时间线填充 → 历史列表）| 0.5d | Phase 4 可视化 |
| F6 | ⚙️ 配置视图（条件 + 渠道 2 tab）+ Prompt 编辑浮层 | 0.5d | 完成 MVP |
| | **合计** | **3.5 天** | |

**MVP 最小可见**：F1 + F2 + F4（**主页和个股可跳过**）即可让产品可用——用户通过时间线看推荐。

---

## 十、数据样例（协助前端开发）

### 10.1 `GET /api/runs/46`

```json
{
  "run_id": 46,
  "status": "completed",
  "started_at": "2026-04-19T10:37:14",
  "finished_at": "2026-04-19T10:44:23",
  "duration_ms": 429000,
  "trigger": {
    "id": 5, "trigger_id": "T-20260419-ES-1",
    "headline": "发改委明确新型储能补贴细则，5月起执行",
    "industry": "新能源储能", "type": "policy_landing",
    "strength": "high", "priority": 10,
    "source_news_ids": [943]
  },
  "timeline": [
    { "id": 101, "agent": "supervisor", "sequence": 1,
      "started_at": "10:37:14", "duration_ms": 2300,
      "summary": "第 1 轮默认调 Research...",
      "payload": { "action": "dispatch_research", "instructions": "...", "notes": null } },
    { "id": 102, "agent": "research", "sequence": 1,
      "started_at": "10:37:16", "duration_ms": 222000,
      "summary": "储能补贴落地利好电池龙头...",
      "payload": { "tool_call_count": 6, "tool_names": ["akshare_industry_leaders", "stock_financial_data", ...] },
      "tool_calls": [
        { "sequence": 1, "tool_name": "akshare_industry_leaders", "args": {"industry":"新能源储能"}, "latency_ms": 820, "error": null },
        { "sequence": 2, "tool_name": "stock_financial_data", "args": {"code":"300750"}, "stock_code": "300750", "latency_ms": 1210, "error": null },
        ...
      ] },
    { "id": 103, "agent": "supervisor", "sequence": 2, ... },
    { "id": 104, "agent": "screener", "sequence": 1, ... },
    { "id": 105, "agent": "supervisor", "sequence": 3, ... },
    { "id": 106, "agent": "skeptic", "sequence": 1, ... },
    { "id": 107, "agent": "supervisor", "sequence": 4,
      "summary": "所有 agent 完成，finalize",
      "payload": { "action": "finalize", "notes": "储能补贴落地强度高..." } }
  ],
  "recommendations": [
    { "code": "300750", "name": "宁德时代",
      "total_score": 0.68, "level": "recommend", "rank": 1,
      "recommendation_rationale": "...",
      "key_strengths": ["全球动力电池市占率 37%", "归母净利润同比 +48.5%", "聪明钱占比 60%"],
      "key_risks": ["PE 28x 高于行业中位数", "技术面数据缺失"],
      "condition_scores": [
        { "condition_id": "C2", "name": "行业龙头", "satisfaction": 1.0, "weight": 0.28, "weighted_score": 0.28, "reasoning": "..." },
        ...
      ],
      "skeptic_findings": [
        { "finding_type": "logic_risk", "content": "..." },
        { "finding_type": "data_gap", "content": "..." }
      ]
    }
  ],
  "comparison_summary": "本批三只候选股均属于新能源储能板块...",
  "supervisor_notes": "储能补贴落地强度高..."
}
```

### 10.2 SSE `/api/runs/47/stream`（实时填充个股分析时间线）

```
data: {"type":"run_started","run_id":47,"trigger":"T-STOCK-300750-..."}
data: {"type":"agent_started","agent":"supervisor","sequence":1}
data: {"type":"agent_completed","agent":"supervisor","sequence":1,"summary":"..."}
data: {"type":"agent_started","agent":"research","sequence":1}
data: {"type":"tool_call","tool_name":"stock_financial_data","args":{"code":"300750"},"latency_ms":1200}
data: {"type":"tool_call","tool_name":"stock_holder_structure","args":{"code":"300750"},"latency_ms":890}
data: {"type":"tool_call","tool_name":"stock_technical_indicators","args":{"code":"300750"},"latency_ms":1510}
data: {"type":"agent_completed","agent":"research","sequence":1,"tool_call_count":3}
data: {"type":"agent_started","agent":"screener","sequence":1}
...
data: {"type":"run_completed","run_id":47}
```

---

## 十一、数据流与配置的 AI-native 呈现

### 11.1 核心设计张力

新闻、触发队列、系统日志这些本质是"列表数据"。传统做法 = 表格 + 分页 + 筛选器 + 批量按钮，**瞬间变成 ERP**，完全打掉 AI-native 感。

解决之道不在 UI 控件选型，而在**心态转换**：

| 传统做法 | AI-native 做法 |
|---|---|
| "表格 row" | "时间流卡片" |
| "分页" | "时间段分组（今日/昨日/3 天前）+ 懒加载" |
| "下拉筛选器" | "顶部 chip 一键切换" |
| "批量操作复选框" | "自然语言批量"（如"把东财源全部暂停"→ LLM 转 API 调用） |
| "填表单→提交→成功弹窗" | "内联编辑→自动保存→iOS 风 toast" |
| "无数据" | "Trigger 队列清空了，Agent 们都在休息 ☕" |
| "数据字段标签" | "ⓘ 点击让 LLM 讲这是什么" |

### 11.2 主页新布局：4 Tab 数据流

v2 的主页加一层横向 Tab，不再只有"最近 runs + 事件流"：

```
┌─────────────────────────────────────────────────────────┐
│  [🏠 概览]  [📰 新闻流]  [🎯 触发队列]  [📜 日志]         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│         <根据选中 tab 显示不同的"流">                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- **🏠 概览**：§4.1 的今日概览 + 最近 5 runs 时间线（保留 v2 原设计）
- **📰 新闻流**：新闻河流（§11.3）
- **🎯 触发队列**：事件卡片堆（§11.4）
- **📜 日志**：system_logs 流（§11.5）

### 11.3 新闻流 —— "News River"

```
┌─────────────────────────────────────────────────────────┐
│ 📰 新闻流                              [🔍 问 AI] [⚙ 过滤]│
│                                                         │
│ 过滤 chip: [全部] [未消费] [已消费] [央视网] [东财-早餐]... │
│                                                         │
│ ─── 今日（23 条）─────────────────────────────────────── │
│  ┌─ 10:37  🔵 未消费 ──────────────────────────────────┐│
│  │ [东财-全球资讯] 国际航协警告欧洲航班最早下月底...     ││
│  │ 停牌时间 2026-04-19 10:37  ·  Hover 展开内容          ││
│  └─────────────────────────────────────────────────────┘│
│  ┌─ 10:12  ✓ 已消费 → Trigger #5 ──────────────────────┐│
│  │ [发改委官网] 发改委明确新型储能补贴细则，5月起执行   ││
│  │ 引用的 trigger 卡片 →（点击跳转 /triggers/5）         ││
│  └─────────────────────────────────────────────────────┘│
│  ...                                                    │
│ ─── 昨日（142 条）[▼ 展开] ─────────────────────────── │
│ ─── 3 天前（310 条）[▼ 展开] ─────────────────────── │
└─────────────────────────────────────────────────────────┘
```

**AI-native 要点**：
- 新新闻**从顶部渐入**（SSE 推送，`slide-down + fade-in 300ms`）
- **未消费/已消费用颜色**而不是列："🔵" 蓝点 = 未消费，"✓" 绿勾 = 已消费
- 已消费的卡片**点击跳转到引用它的 trigger**（追溯链路）
- 空状态：**"今日尚未有新新闻进来。Scheduler 下次抓取 08:00。☕"**

**过滤**：
- Chip 单击切换，不用下拉
- 顶部 "🔍 问 AI" 按钮点击弹输入框，输入"最近 3 天关于锂矿的新闻"→ LLM 转 SQL WHERE 条件查 DB

### 11.4 触发队列 —— "事件卡片堆"

不是表格，是**优先级堆叠的 hero 卡片**：

```
┌─────────────────────────────────────────────────────────┐
│ 🎯 触发队列    🔴Pending 3  🟡Processing 1  ✓Completed 42│
│                                                         │
│ ─── 🔴 Pending（等待被消费，按 priority 排）──────────── │
│                                                         │
│  ╔═══════════════════════════════════════════════════╗  │
│  ║ 🔥 priority 10  ·  policy_landing  ·  high         ║  │
│  ║ 发改委明确新型储能补贴细则，5月起执行               ║  │
│  ║ 新能源储能  ·  引用 1 条新闻  ·  2 分钟前生成        ║  │
│  ║ [▶ 立即消费]                                        ║  │
│  ╚═══════════════════════════════════════════════════╝  │
│                  ↕ 悬浮漂浮动画（float）                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │ priority 7  ·  industry_news  ·  medium           │  │
│  │ 国际航协警告欧洲航班最早下月底或现停飞潮           │  │
│  │ 航空运输  ·  引用 2 条新闻                          │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│ ─── 🟡 Processing ─────────────────────────────────── │
│  ╔═══════════════════════════════════════════════════╗  │
│  ║ ⏵ Run 46 正在跑  ·  已 2:14                        ║  │
│  ║ 碳中和专项再贷款 3000 亿                           ║  │
│  ║ → Research (工具调用中 4/8)  [🔗 去 Run Detail]    ║  │
│  ╚═══════════════════════════════════════════════════╝  │
│                  ↻ 旋转光环 + Dots 动画                  │
│                                                         │
│ ─── ✓ Recent Completed（最近 10 条）[▼ 展开] ──────── │
│ ─── ✗ Failed [若有]                                   │
└─────────────────────────────────────────────────────────┘
```

**AI-native 要点**：
- **Pending 卡片悬浮漂浮**（`float` 动画），像"等待被取的外卖单"
- **Processing 旋转光环** + "已运行 N 秒"计时
- **Priority 10 卡片最大最亮**（优先级用字号+阴影+颜色传达，不是仅一个数字）
- 点击卡片展开看引用的 news 和 Trigger Agent 的 reasoning
- 无 pending 时空状态：**"队列清空了。Trigger Agent 下次运行 11:05，静候重大事件 🌙"**

### 11.5 日志流 —— "工程噪音的人话翻译"

```
┌─────────────────────────────────────────────────────────┐
│ 📜 系统日志                                              │
│ Level: [all] [ⓘ info] [⚠️ warning] [❌ error]           │
│ Source: [all] [scheduler.*] [agents.*]                  │
│                                                         │
│ ┌ ❌ ERROR  10:35:22  scheduler.news_trade_notify_* ──┐│
│ │ HTTPError: 502 Bad Gateway                         ││
│ │ [▼ 堆栈 3 行]                                        ││
│ │ 影响：这次抓取未入库任何新闻。下次 12:00 再试。      ││
│ │ [🔍 问 AI 这是什么原因]                              ││
│ └─────────────────────────────────────────────────────┘│
│ ┌ ⚠️ WARNING  10:15:08  agents.trigger ──────────────┐│
│ │ LLM 判断无值得分析事件，skip                         ││
│ │ reason: "资讯列表主要为..."                          ││
│ └─────────────────────────────────────────────────────┘│
│ ┌ ⓘ INFO  10:05:00  scheduler.news_cctv ──────────────┐│
│ │ 渠道完成：12 条候选 → 新增 0，去重命中 12            ││
│ └─────────────────────────────────────────────────────┘│
│                                                         │
│ [▼ 加载更早的 50 条]                                    │
└─────────────────────────────────────────────────────────┘
```

**AI-native 要点**：
- 每条日志自带 "**影响**" 一行 —— **这是什么后果 vs 这是什么错误**（一次抓失败不等于系统挂）
- 每条 error 旁边 "🔍 问 AI 这是什么原因" 按钮，点击调 LLM 根据堆栈解读
- Warning / info 用**降噪字号**（error 大字、warning 中字、info 小字）
- 堆栈默认折叠

### 11.6 配置编辑 —— "直接编辑，无表单"

**注**（v3 定版）：
- **渠道 cron**：不做 LLM 自然语言转换。用户直接编辑 `config/news_channels.json`（或前端提供文本框输入标准 cron）。
- **用户条件**：前端可直接内联编辑权重 + 启用开关（调 DB conditions 表）。
- **Prompt**：走 §11.9 的版本化 DB 方案。

**⚙️ 配置** 视图的 2 tab 内（§4.4），每张"配置卡片"都是**可内联编辑 + 自动保存**：

#### Tab A：用户条件（每条 = 一张卡片，不是表格）

```
┌───────────────────────────────────────────────────────┐
│ C2  行业龙头  [screener 层]                   ● 启用    │
│ ───────────────────────────────────────────────────── │
│ 描述：该股票的公司处于受政策支持的行业，且为龙头企业...│
│       ↑ 点击任意处直接编辑                             │
│                                                       │
│ 权重：[0.28]                                          │
│       ↑ 点击数字变输入框，blur 自动保存               │
│                                                       │
│ 预览影响：                                            │
│   改 0.28 → 0.50 会让 C2 占比从 28% 升到 50%           │
│   近 7 天 12 条推荐中，预计 5 条评级会从 watch 升 recommend │
│                     ↑ hover 数字时浮层显示（LLM 计算）│
└───────────────────────────────────────────────────────┘
```

#### Tab B：新闻渠道

```
┌────────────────────────────────────────────────┐
│ 📡 央视网                              ● 启用   │
│ ──────────────────────────────────────────── │
│ 每天 08:00                                    │
│   ↑ 点击改成"每天 09:15"自动转 cron            │
│ 最近：2h 前 12 条  ·  今日共 1 次抓取          │
│ [▶ 立即抓一次]                                 │
└────────────────────────────────────────────────┘
```

**AI-native 要点**：
- **无"保存"按钮**，改完 blur 自动保存 + iOS 风 toast `✓ 已更新`
- **cron 用人话**：输入框接受 "每天早上 8 点" / "盘中每小时" 这类自然语言，LLM 转标准 cron 表达式
- 失败自动回滚 + toast `✗ 保存失败，已回滚：<原因>`
- 预览影响：改权重前 hover 数字→LLM 浮层估算"这次改动会影响哪些历史推荐"

### 11.7 保留 AI-native 的 7 个具体原则

1. **流 > 表格**：数据按时间流呈现，最新在上
2. **卡片 > 行**：每条数据是独立 hero，不追求密度
3. **动画传递"发生"**：渐入、漂浮、脉冲、光环；**不用弹窗**
4. **编辑无表单感**：内联、自动保存、iOS toast
5. **空状态有人情味**：不是"无数据"，是"☕ Agent 们都在休息"
6. **颜色即状态**：pending 蓝 / processing 黄脉冲 / completed 绿 / failed 红，不需要额外标签
7. **无"问 AI"全局入口**（v3 定版决策 9）：列表/配置就是数据展示，不做对话式 NL→SQL

### 11.8 Prompt 版本化方案（DB 驱动，不用 git）

**v3 定版决策 7**：Prompt 编辑保存不碰 git，改用 **DB 新建 `prompt_versions` 表**，每次保存自动生成 `YYYYMMDDXXXX` 版本号存档。

#### 新表：`prompt_versions`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 主键 |
| agent_name | TEXT | NOT NULL | `supervisor` / `research` / `screener` / `skeptic` / `trigger` |
| version_code | TEXT | UNIQUE NOT NULL | 版本号 `202604190101`（YYYYMMDD + 当日序号 HHNN 4 位）|
| content | TEXT | NOT NULL | 完整 prompt 正文 |
| is_active | BOOLEAN | NOT NULL DEFAULT 0 | 当前激活版本只有 1 个（每次保存把老的置 0） |
| author | TEXT |  | 操作人（默认 "admin"；未来多用户可扩展） |
| comment | TEXT |  | 版本备注（用户输入） |
| created_at | DATETIME | NOT NULL DEFAULT now | |
| **唯一索引** | `(agent_name, version_code)` | | |
| **部分唯一索引** | `(agent_name)` WHERE `is_active=1` | | 保证每 agent 只有 1 个激活版本 |

#### 版本号格式

`YYYYMMDDNNNN` 12 位：
- `YYYYMMDD` 当日日期
- `NNNN` 当日序号（从 0001 递增）
- 示例：`202604190101` = 2026-04-19 当日第 1 个保存
- 同一天多次保存：`202604190001` / `202604190002` / ...

生成逻辑（后端）：
```python
from datetime import date
today_prefix = date.today().strftime("%Y%m%d")
# 查当日最大序号
last = sess.scalar(select(PromptVersion).where(
    PromptVersion.agent_name==agent_name,
    PromptVersion.version_code.like(f"{today_prefix}%")
).order_by(PromptVersion.version_code.desc()).limit(1))
next_seq = int(last.version_code[-4:]) + 1 if last else 1
new_version_code = f"{today_prefix}{next_seq:04d}"
```

#### 文件 vs DB 的角色

| 阶段 | 实现 |
|---|---|
| **Agent 运行时读 prompt** | 现在：读 `config/prompts/{agent}.md` 文件 / 之后：改为读 DB `prompt_versions WHERE agent_name=X AND is_active=1` |
| **初始化** | 首次运行 `scripts/seed_prompts.py` 把现有 4 个 md 文件导入 DB 作为 `version_code='202604190001'`（每个 agent 自己的序号独立） |
| **编辑历史** | 全在 DB，可回滚 |
| **`config/prompts/*.md` 文件** | **保留作种子 / 备份**，但不再是运行时真相源 |

#### 前端交互（`§11.6 + §三.1` 浮层）

```
╔═════════════════════════════════════════════════════════╗
║ ✏️ 编辑 Research Agent 的 Prompt            [✕ 关闭]    ║
║ ─────────────────────────────────────────────────────── ║
║ 当前版本：v202604190101   ⦿ 活跃中                      ║
║                                                         ║
║ [Monaco editor 展示 content，支持 Markdown 高亮]          ║
║                                                         ║
║ 保存前备注（可选）：                                     ║
║ [ 调整了 ReAct 约束，要求最少 3 个核心工具      ]         ║
║                                                         ║
║ 历史版本：                                              ║
║ ⦿ v202604190101  (当前活跃)  2m 前 admin                ║
║ ○ v202604180102  2 天前 admin  "加行业反查 fallback"     ║
║ ○ v202604180101  2 天前 admin  "种子导入"                ║
║   [查看 diff]  [回滚到此版本]                            ║
║                                                         ║
║              [取消]      [保存（生成新版本）]           ║
╚═════════════════════════════════════════════════════════╝
```

**交互要点**：
- 保存 → 生成 `v202604190102`（YYYYMMDD + 序号），老版本 `is_active=0`，新版 `is_active=1`
- 回滚 → 选历史版本点"回滚到此版本"→ 复制 content 生成**新的 version_code**（不是直接切 is_active，保持版本线性可追溯）
- 历史列表默认显示最近 10 条，可翻页

#### API 端点（§七 API 层扩充）

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/prompts/:agent` | GET | 当前活跃版本 + 历史版本列表 |
| `/api/prompts/:agent` | POST | 保存新版本（自动生成 version_code） |
| `/api/prompts/:agent/rollback/:version_code` | POST | 回滚：复制指定版本 content 作为新版本 |
| `/api/prompts/:agent/diff?a=v1&b=v2` | GET | 两版本 diff |

**种子脚本** `scripts/seed_prompts.py`：把 `config/prompts/*.md` 4 份文件 + `trigger.md` 导入为 `202604190001`（或当前日期）初始版本。

---

## 十二、实施决策已定版

见 §〇 的 10 项最终决策表。**开工顺序**按 §九 的 F1→F6 执行：

```
F1 FastAPI 后端 (0.6d)
  + 新增 prompt_versions 表 migration + seed 脚本
F2 React + Vite 壳 (0.4d)
  + 顶栏 Agent 头像浮层（Monaco + 版本历史列表）
F3 🏠 主页（4 Tab 数据流：概览 / 新闻 / 队列 / 日志）(0.8d)
F4 📋 推荐详情（核心价值）(0.9d)
F5 📊 个股分析 (0.5d)
F6 ⚙️ 配置（用户条件 + 渠道）(0.4d)
F7 Dockerfile + docker-compose (0.3d)  ← v3 新增
────────────────────────────────────────
合计约 3.9 天
```

### Docker 打包（v3 新增）

最终交付物：**单个 Docker 镜像**，含 FastAPI + React dist + SQLite。

```dockerfile
# Dockerfile（多阶段构建）
FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build        # 产出 /app/dist

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend /app/dist ./api/static
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
services:
  stock-agent:
    build: .
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data          # SQLite 持久化
      - ./config:/app/config      # 可在外部改配置
    env_file: .env
    restart: unless-stopped

  scheduler:
    build: .
    command: python scheduler/run.py
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    env_file: .env
    restart: unless-stopped
    depends_on: [stock-agent]
```

启动：`docker compose up -d` → 浏览器访问 `http://localhost:8000`。
