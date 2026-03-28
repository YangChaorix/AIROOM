# 升级指南 — Critic Agent 版本

## 本次升级内容

| 类型 | 说明 |
|------|------|
| 新功能 | 批评Agent（15:40 自动验证当日选股，LLM 分析维度准确率，自动更新精筛 Prompt） |
| 新页面 | Web UI「🔬 批评报告」导航页 |
| DB 变更 | 新增 2 张表、1 列、4 个配置项；存量提示词分拆为可编辑部分 + 固定格式 |
| 提示词 | 所有 Agent Prompt 拆分为 `system_prompt`（可改）+ `output_format`（系统固定）|
| UI 优化 | 控制台日期筛选、选股分析 Tab 合并、提示词版本对比/删除、Favicon |
| 运维 | 新闻自动清理定时任务（每天凌晨 2 点，保留天数可配置）|

---

## 升级步骤（Docker 部署）

### 第一步：备份数据库

```bash
# 在服务器上执行
cp docker/data/db/stock_agent.db docker/data/db/stock_agent.db.bak-$(date +%Y%m%d)
```

### 第二步：迁移数据库（升级前在宿主机执行）

把新代码同步到服务器后，先跑迁移脚本预览（不写入）：

```bash
python3 scripts/migrate_db.py --db docker/data/db/stock_agent.db --dry-run
```

确认输出无异常后，执行实际迁移：

```bash
python3 scripts/migrate_db.py --db docker/data/db/stock_agent.db
```

> **注意**：迁移脚本是幂等的，重复执行不会造成损坏。
> 如果你直接重启新版 Docker 不跑脚本也可以，`init_db()` 在服务启动时会自动完成相同迁移。
> 手动跑脚本的好处是：可以提前 dry-run 检查、看到详细日志。

### 第三步：构建新镜像

```bash
cd /path/to/stock-agent-v3
docker build -t stock-agent-v3:latest -f docker/Dockerfile .
```

### 第四步：重启容器

```bash
cd docker
docker compose down
docker compose up -d
```

### 第五步：验证

```bash
# 检查服务健康
curl http://localhost:8888/api/health

# 检查调度器日志，确认 critic_job 已注册
docker logs docker-web-1 2>&1 | grep "critic_job\|批评Agent"

# 检查数据库迁移结果
docker exec docker-web-1 python3 -c "
import sqlite3
conn = sqlite3.connect('data/db/stock_agent.db')
rows = conn.execute(\"SELECT agent_name, prompt_name, source, version FROM prompts ORDER BY agent_name, prompt_name\").fetchall()
for r in rows: print(r)
"
```

预期输出中应看到每个 agent 都有 `output_format`（source=system）条目。

---

## 升级步骤（宿主机直接运行）

```bash
# 1. 备份
cp data/db/stock_agent.db data/db/stock_agent.db.bak-$(date +%Y%m%d)

# 2. 预览迁移
python3 scripts/migrate_db.py --dry-run

# 3. 执行迁移
python3 scripts/migrate_db.py

# 4. 重启服务（停掉旧进程）
pkill -f "web_server.py"
python3 web_server.py &
```

---

## 数据库变更详情

### 新增表

```sql
-- 批评报告
CREATE TABLE critic_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, run_id TEXT, screener_run_id TEXT,
    critique_markdown TEXT,
    avg_pick_return REAL, market_avg_return REAL,
    beat_count INTEGER, miss_count INTEGER,
    suggested_prompt TEXT, suggested_prompt_id INTEGER,
    previous_prompt_id INTEGER,  -- 用于一键回滚
    created_at TEXT
);

-- 个股当日表现
CREATE TABLE critic_stock_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, critic_run_id TEXT, stock_code TEXT, stock_name TEXT,
    rank INTEGER, total_score INTEGER,
    d1_score INTEGER, d2_score INTEGER, d3_score INTEGER,
    d4_score INTEGER, d5_score INTEGER, d6_score INTEGER,
    open_price REAL, close_price REAL, pct_return REAL,
    market_avg REAL, beat_market INTEGER,  -- 1=跑赢 0=跑输 -1=无数据
    created_at TEXT
);
```

### prompts 表变更

| 变更 | 说明 |
|------|------|
| 新增列 `source` | 标记来源：`human`（人工）/ `critic`（自动生成）/ `system`（系统固定）|
| 存量 `system_prompt` 内容 | 裁剪掉固定格式尾部，只保留可编辑的分析准则部分 |
| 新增 `output_format` 条目 | 每个 agent 写入一条固定格式模板，source=system，不可通过 API 修改 |

### 新增系统配置项

| key | 默认值 | 说明 |
|-----|--------|------|
| `schedule_critic_hour` | `15` | 批评Agent执行小时 |
| `schedule_critic_minute` | `40` | 批评Agent执行分钟 |
| `schedule_critic_days` | `1,2,3,4,5` | 执行日（周一到周五）|
| `news_retention_days` | `90` | 新闻保留天数；超出自动删除，`0` = 不清理 |

---

## 补丁说明

### Patch 1 — 补充 `config/models.json` 中 critic agent 配置

**问题**：`models.json` 的 `agents` 字段仅含 trigger / screener / review 三项，缺少 `critic`。
点击「运行批评」时，`build_llm("critic")` 抛出 `KeyError: 'critic'`，前端报错
`批评Agent失败：LLM 调用失败: 'critic'`。

**修复**：在 `config/models.json` 的 `agents` 块末尾追加：

```json
"critic": {
  "model": "deepseek/deepseek-chat"
}
```

> 无需迁移数据库，重启服务即可生效。如需使用其他模型，按与其他 agent 相同格式修改 `model` 字段即可。

### Patch 2 — 提示词管理页新增 critic tab + 配置说明 + 固定输出格式预览

**变更**：
- 提示词管理页新增「🔬 批评分析」Tab，四个 Agent 完整可配置
- 每个 Agent 编辑区顶部显示配置说明（可改 / 不可改 / 固定输出）
- 编辑区下方展示系统固定输出格式只读预览

**迁移**：服务启动时 `init_db()` 会自动将 critic `system_prompt` 种子化到 DB（如不存在则写入默认值）。无需手动操作，重启即可。

---

### Patch 3 — 选股分析页合并触发事件与精选股票

**变更**：
- 左侧导航「触发事件」+「精选股票」合并为单一入口「⚡ 选股分析」
- 页内通过 Tab 切换，**默认显示「🏆 精选股票」Tab**，批次选择器各自独立
- 移除「⚡ 重新触发」独立按钮（功能由「▶ 触发分析」全流程覆盖）

**迁移**：纯前端 UI 改动，无数据库变更，无需任何迁移操作。

---

### Patch 4 — 提示词版本历史去除 100 条上限 + 分页 + 对比 + 删除

**变更**：
- `tools/db.py`：`save_prompt()` 移除每个 agent/prompt_name 组合最多保存 100 条的限制，版本数量不再受约束
- `web/index.html`：版本历史改为分页展示，**每页 5 条**，支持翻页
- 版本历史新增「**对比**」按钮：与当前编辑区内容进行逐行 LCS Diff，绿色显示新增行、红色显示删除行（纯前端实现，无需后端）
- 版本历史新增「**删除**」按钮（红色）：带 confirm 确认弹窗，调用 `DELETE /api/prompts/{id}` 删除该版本；系统固定版本（source=system）和当前激活版本不可删除
- `web_server.py` 新增 `DELETE /api/prompts/{prompt_id}` 接口：双重保护，拒绝删除 source=system 和 is_active=1 的记录
- 提示词编辑区布局调整：**版本历史在上，系统固定输出格式预览在下**

**迁移**：无需数据库迁移。已有的历史版本不受影响，移除上限后新版本可无限积累。

> **存储提示**：SQLite 单文件数据库，提示词内容（纯文本）每条约 1–5 KB。即使积累数千条版本，DB 文件增长也在可接受范围内。如需定期清理旧版本，可手动执行：
> ```sql
> -- 仅保留每个 agent/prompt_name 最近 200 条（示例，按需调整）
> DELETE FROM prompts WHERE source != 'system' AND id NOT IN (
>   SELECT id FROM prompts p2
>   WHERE p2.agent_name = prompts.agent_name AND p2.prompt_name = prompts.prompt_name
>   ORDER BY id DESC LIMIT 200
> );
> ```

---

### Patch 5 — 项目 Favicon（K 线图样式）

**变更**：
- 新增 `web/favicon.svg`：深色背景 K 线图，A 股风格（红涨绿跌），3 根红柱 + 2 根绿柱 + 蓝色上升趋势线
- `web_server.py` 新增路由：同时响应 `/favicon.ico` 和 `/favicon.svg`，Content-Type 均为 `image/svg+xml`
- `web/index.html` `<head>` 新增 `<link rel="icon" href="/favicon.svg" type="image/svg+xml"/>`

**迁移**：无需迁移，重启服务即可（浏览器可能需要强制刷新 Ctrl+Shift+R 更新缓存）。

---

### Patch 6 — 控制台日期筛选 + 「今日」标签修复

**问题**：控制台汇总数据来自数据库最新日期，若当天无运行记录则展示昨日数据，但标签仍显示「今日运行次数」。

**变更**：
- `web_server.py` `/api/summary` 接口新增 `date` 查询参数（可选），新增 `server_date` 字段（服务器当前日期）返回
- 前端将 `latest_date`（数据日期）与 `server_date`（服务器日期）对比：相同才显示「今日」，否则显示实际日期
- 控制台页面 section-header 新增**日期选择器** + 「回到今日」按钮，可查看任意历史日期的汇总数据
- 日期选择器选项来自 `S.dates`（已有数据的日期列表），无需额外接口

**迁移**：无需数据库迁移，重启服务即可。

---

### Patch 7 — 新闻自动清理定时任务

**变更**：
- `tools/db.py` 新增系统配置项 `news_retention_days`，默认值 `90`（天），含义：自动清理超出天数的新闻记录，`0` 表示不清理
- `web_server.py` 新增 `job_clean_news()` 定时任务，每天凌晨 2:00 执行，删除 `news_items` 表中 `collect_date` 早于阈值的记录
- `web/index.html` 系统配置页新增「📰 新闻保留」下拉选项（30/60/90/120/180/365/0 天），可在页面直接修改保留周期

**新增配置项**：

| key | 默认值 | 说明 |
|-----|--------|------|
| `news_retention_days` | `90` | 新闻保留天数，超出自动删除；`0` = 不清理 |

**迁移**：服务启动时 `init_db()` 自动写入默认值，无需手动操作。重启服务后定时任务即生效。

> 若需立即手动清理，可执行：
> ```sql
> DELETE FROM news_items WHERE collect_date < date('now', '-90 days');
> ```

---

### Patch 8 — 批评报告 UI 修复（批次格式 + 表格对齐 + source 标签）

**问题集合**：
1. 批评报告批次显示格式与选股分析不一致（缺少「第N次批评」样式）
2. 个股表现表格表头与内容列对不齐（涨跌幅列左右对齐不一致）
3. Critic 自动生成的提示词 `source` 字段在前端未显示紫色「critic」徽章

**修复**：
1. `web/index.html` 批评报告批次选择器格式统一为 `HH:MM 第N次批评`
2. 个股表现表格各列显式设置 `text-align`：股票代码/名称左对齐，评分/价格/涨跌幅右对齐
3. `web_server.py` `/api/prompts` SELECT 查询补充 `source` 字段（之前漏选导致前端收到 `undefined`）

**迁移**：纯代码修复，无数据库变更，重启服务即可。

---

## 回滚方案

如果升级出现问题，直接还原备份：

```bash
# Docker
docker compose down
cp docker/data/db/stock_agent.db.bak-YYYYMMDD docker/data/db/stock_agent.db
# 切换回旧镜像（或 git revert 后重新 build）
docker compose up -d

# 宿主机
pkill -f "web_server.py"
cp data/db/stock_agent.db.bak-YYYYMMDD data/db/stock_agent.db
git stash  # 或 git checkout 到旧版本
python3 web_server.py &
```
