# Stock Agent v6 — Phase 4：个股分析入口执行计划

> 版本：2026-04-19
> 状态：**待实施（本文档供审阅，尚未写任何代码）**
> 前置：Phase 1 MVP + Phase 2 真实数据接入已完成，22/22 测试通过
> 与 Phase 3 关系：**独立 / 可并行**——本期不动 DB 层，只扩展入口与 Research；若 Phase 3 已启动，本期输出自然落 DB

---

## 一、背景与目标

### 1.1 当前架构的入口限制

Stock Agent v6 目前是**事件驱动**的流水线：

```
AkShare 新闻聚合
    ↓
trigger（含 industry）
    ↓
Research 从 industry_leaders_map.json 选 3 只候选股
    ↓
Screener → Skeptic → 报告
```

**用户场景不能覆盖**：投资者手里已经有一只股票（比如"我想看看宁德时代现在能不能买"），需要**跳过"找候选股"**，直接让 Supervisor 多 Agent 走完整流程分析这只股。

### 1.2 本期目标

- 新增 CLI：`python main.py --stock <code_or_name>` → 跑 Supervisor 多 Agent 流程分析指定股票
- **自动拉取 2-3 只行业对标股**做横向对比（提升分析深度，而非只看一只股）
- **图结构零改动**、**4 个 Agent 代码几乎零改动**——通过合成 Trigger 复用现有管道
- 支持股票代码和公司名两种输入（用 AkShare 做名称↔代码解析）

### 1.3 用户确认的关键决策

| # | 问题 | 决定 |
|---|---|---|
| 1 | 输入格式 | **同时支持代码和名称**（`--stock 300750` 或 `--stock 宁德时代`） |
| 2 | 横向对比 | **带 2-3 只行业对标股**（从 `industry_leaders_map.json` 自动拉取） |
| 3 | Prompt 复用 | **复用 `research.md`**，在 prompt 里加 `focus_codes` 分支 |

---

## 二、设计核心：合成 Trigger

**关键洞察**：现有 Research Agent 从 `state.trigger_summary.industry` 开始找候选股。把"用户输入的股票"包装成一个**合成 Trigger**，在 trigger 里加一个可选字段 `focus_codes`，Research 看到非空的 focus_codes 就切成"只深度分析这几只"模式。**图结构、Supervisor、Screener、Skeptic 完全不改**。

### 数据流对比

```
事件驱动（原）：                         股票驱动（新）：
news → LLM 摘要                         用户输入: 300750 / "宁德时代"
    ↓                                      ↓
trigger {                               stock_resolver → code=300750, industry="动力电池"
  industry: "新能源储能",                   ↓
  focus_codes: [] ← 默认为空             [行业对标] 从 industry_leaders_map
}                                       找 2 只同行业龙头：002594, 300274
    ↓                                      ↓
Research 从行业表找候选                  合成 Trigger {
    ↓                                     trigger_id: "T-STOCK-300750-...",
...照常                                   headline: "个股深度分析：宁德时代",
                                          industry: "动力电池",
                                          type: "individual_stock_analysis",
                                          focus_codes: ["300750","002594","300274"]
                                          ← 主股 + 对标股
                                       }
                                          ↓
                                       Research 看到 focus_codes 非空 →
                                       只查这 3 只 + 每只 3 个核心工具
                                          ↓
                                       Screener 打分 + 横向对比
                                       （主股 vs 对标股）
                                          ↓
                                       Skeptic 对主股 logic_risk/data_gap
                                          ↓
                                       报告
```

---

## 三、实施步骤（共 5 步，预计 2 小时）

### 步骤 S1：股票名↔代码解析（0.3h）

**新建 `tools/stock_resolver.py`**：

```python
"""股票代码 ↔ 公司名解析 + 行业查询。

底层：AkShare stock_info_a_code_name() 返回全市场 A 股 code/name 表（Sina，稳）。
支持：
- 输入 6 位代码 → 返回 (code, name, industry)
- 输入名称 → 返回 (code, name, industry)；模糊命中多条时按总市值排序取最大（未来可改成用户选择）
"""
import akshare as ak

from tools._cache import ttl_cache


@ttl_cache(seconds=86400)  # 全市场清单每天刷新一次即可
def _load_code_name_table() -> list[dict]:
    df = ak.stock_info_a_code_name()  # 返回 code/name
    return df.to_dict("records")


def resolve(stock: str) -> dict:
    """返回 {"code": "300750", "name": "宁德时代", "industry": "动力电池/储能"} 或 raise ValueError。
    
    - stock 是 6 位数字 → 查 code
    - stock 不是 6 位数字 → 按 name 模糊匹配（先精确，再包含）
    """
    table = _load_code_name_table()
    if stock.isdigit() and len(stock) == 6:
        hits = [r for r in table if r["code"] == stock]
    else:
        # 先精确匹配
        hits = [r for r in table if r["name"] == stock]
        if not hits:
            # 再模糊包含
            hits = [r for r in table if stock in r["name"]]
    if not hits:
        raise ValueError(f"无法找到股票: {stock}")
    if len(hits) > 1:
        # 多个命中时提示用户，但默认取第一个（可改成按市值排序）
        names = [f"{h['code']} {h['name']}" for h in hits[:5]]
        print(f"[stock_resolver] 多个匹配，默认取第一个；候选：{names}", file=sys.stderr)
    code = hits[0]["code"]
    name = hits[0]["name"]
    # 行业查询：从 industry_leaders_map 反查；若未命中返回 "未分类"
    industry = _infer_industry(code, name)
    return {"code": code, "name": name, "industry": industry}


def _infer_industry(code: str, name: str) -> str:
    """反查 data/industry_leaders_map.json：若该 code 出现在某行业龙头表里，返回该行业名。"""
    import json
    from pathlib import Path
    table = json.loads((Path(__file__).parent.parent / "data" / "industry_leaders_map.json").read_text(encoding="utf-8"))
    for industry_name, entries in table.items():
        if industry_name.startswith("_"):
            continue
        if any(e["code"] == code for e in entries):
            return industry_name
    return "未分类"


def fetch_peers(industry: str, exclude_code: str, limit: int = 2) -> list[dict]:
    """从行业龙头表拉 `limit` 只同行业对标股（排除主股自身）。"""
    import json
    from pathlib import Path
    table = json.loads((Path(__file__).parent.parent / "data" / "industry_leaders_map.json").read_text(encoding="utf-8"))
    entries = []
    for key, val in table.items():
        if key.startswith("_"):
            continue
        if key == industry or industry in key or key in industry:
            entries = val
            break
    peers = [e for e in entries if e["code"] != exclude_code][:limit]
    return peers
```

### 步骤 S2：合成 Trigger 工厂（0.3h）

**新建 `tools/single_stock_trigger.py`**：

```python
"""把单股分析请求合成为一条 Trigger（复用现有流水线）。

结构与 live/fixture trigger 完全一致，仅多一个 focus_codes 字段指示
Research 只聚焦这几只股，不扩大候选范围。
"""
from datetime import datetime
from typing import Any, Dict

from tools.stock_resolver import resolve, fetch_peers


def build_single_stock_trigger(stock: str, with_peers: bool = True) -> Dict[str, Any]:
    """根据输入（code 或 name）构造个股分析 Trigger。"""
    main = resolve(stock)
    peers = fetch_peers(main["industry"], main["code"], limit=2) if with_peers else []
    focus_codes = [main["code"]] + [p["code"] for p in peers]
    peer_names = "、".join(p["name"] for p in peers) if peers else "无"

    return {
        "trigger_id": f"T-STOCK-{main['code']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "headline": f"个股深度分析：{main['name']}（对标 {peer_names}）",
        "industry": main["industry"],
        "type": "individual_stock_analysis",  # 新类型
        "strength": "medium",  # 单股分析无强度概念，填 medium 占位
        "source": "user_request",
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": (
            f"用户请求分析 {main['name']}（{main['code']}，{main['industry']}）。"
            f"本次同时拉取行业对标 {peer_names} 做横向对比。"
        ),
        "focus_codes": focus_codes,  # ★ 新字段：Research 看到非空则只分析这几只
        "focus_primary": main["code"],  # ★ 新字段：主股（Skeptic 重点质疑对象）
    }
```

### 步骤 S3：Research Prompt + 候选股提示调整（0.5h）

**修改 `config/prompts/research.md`**：在"工具调用硬性要求"前面加一段：

```markdown
## focus_codes 模式（单股分析）

如果触发信号里 `focus_codes` 字段**非空**：
- **只对这几只股做深度分析**，不得扩大候选范围（不调 `akshare_industry_leaders`）
- 第一只是主股，其余为行业对标；对每只都要调满 3 个核心工具
- 最终 ResearchReport 的 candidates 只包含这几只股，不要自作主张加别的
- overall_notes 里用一句话说明"本次为个股分析模式，对标股为 xxx"

如果 `focus_codes` 为空（事件驱动模式）：按原默认逻辑——先调 akshare_industry_leaders 找候选池。
```

**修改 `agents/research.py::_candidate_hint()`**：

```python
def _candidate_hint(trigger: dict, limit: int = 3) -> str:
    """若 trigger.focus_codes 非空，直接用它；否则走行业龙头表。"""
    focus = trigger.get("focus_codes") or []
    if focus:
        # 个股分析模式：直接给 focus_codes
        # （name 先留空，LLM 会在 stock_financial_data 返回里拿到）
        brief = [{"code": c, "name": "", "note": "单股分析指定"} for c in focus[:limit]]
        return json.dumps(brief, ensure_ascii=False, indent=2)
    # 事件驱动模式：原逻辑
    industry = trigger.get("industry", "")
    # ... (现有代码不变)
```

**修改 `_run_react()` 的 user_input 构造**：把 `_candidate_hint(trigger.get('industry', ''))` 改为 `_candidate_hint(trigger)`。

### 步骤 S4：main.py CLI 扩展（0.2h）

**修改 `main.py`**：

```python
import argparse
# ... 现有 imports

def run(trigger_key: str = "live", stock: str | None = None) -> AgentState:
    load_dotenv(_ROOT / ".env")
    if stock:
        from tools.single_stock_trigger import build_single_stock_trigger
        trigger = build_single_stock_trigger(stock, with_peers=True)
    elif trigger_key == "live":
        trigger = _load_live_trigger()
    else:
        trigger = _load_fixture_trigger(trigger_key)
    # ... 其余不变

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("trigger_key", nargs="?", default="live",
                        help="live / default / strong_policy / weak_noise")
    parser.add_argument("--stock", help="股票代码（6 位）或公司名，走个股分析流程")
    args = parser.parse_args()
    state = run(trigger_key=args.trigger_key, stock=args.stock)
    # ... 打印 md 路径
```

**用法示例**：

```bash
python main.py                       # 事件驱动（live）
python main.py --stock 300750        # 个股分析（代码）
python main.py --stock 宁德时代       # 个股分析（名称）
python main.py default               # fixture 事件
```

### 步骤 S5：Screener/Skeptic Prompt 的轻微兼容性调整（0.3h）

Screener / Skeptic **不需要切分支**，但 Prompt 里对"候选股数量"的假设需要放宽：

**修改 `config/prompts/screener.md`**：

- 当前模板里可能假设"多只候选横向对比"；加一句："如果候选股只有 1 只（无对标），`comparison_summary` 可以简短说明'单股分析，无同批对比'"
- `recommendation_rationale` 单股时可聚焦"是否符合用户条件 + 关键优势/风险"，不强制与同批对比

**修改 `config/prompts/skeptic.md`**：

- 当前对 TOP5 质疑；单股时 TOP=1，自然退化
- 若有 2-3 只对标，Skeptic 对每只都会产出质疑——符合预期

### 步骤 S6：测试（0.4h）

**新增 `tests/test_single_stock_mode.py`**：

- `test_resolve_by_code`: `resolve("300750")` → `{"code": "300750", "name": "宁德时代", ...}`
- `test_resolve_by_name`: `resolve("宁德时代")` → 同上
- `test_resolve_name_fuzzy`: `resolve("宁德")` → 模糊命中
- `test_resolve_invalid`: `resolve("999999")` → `ValueError`
- `test_build_trigger_with_peers`: `focus_codes` 长度 = 3
- `test_build_trigger_no_peers`: `with_peers=False` 时 `focus_codes` 长度 = 1
- `@pytest.mark.real_data` 标记的集成测试：`python main.py --stock 300750` 跑完整流程，report 里 Screener 的 candidates 只包含 focus_codes 指定的股票

---

## 四、关键文件清单

### 新建
- `tools/stock_resolver.py` — 股票名↔代码解析 + 行业反查 + peers 拉取
- `tools/single_stock_trigger.py` — 合成 Trigger 工厂
- `tests/test_single_stock_mode.py` — 单股模式集成测试

### 修改
- `main.py` — argparse + `--stock` 参数 + 分支调用
- `config/prompts/research.md` — 加 `focus_codes` 分支说明
- `config/prompts/screener.md` / `skeptic.md` — 放宽"多只候选"假设的文字
- `agents/research.py::_candidate_hint()` — 接受 trigger dict 参数，支持 focus_codes

### 不改（架构零侵入）
- `graph/builder.py` / `graph/edges.py` — 图结构不动
- `agents/supervisor.py` / `screener.py` / `skeptic.py` — Agent 代码不动（Prompt 小改而已）
- `schemas/*.py` — Pydantic 不动（focus_codes 在 trigger dict 的动态字段里，不强约束）
- Phase 3 DB schema — 个股分析 run 自然落 runs / agent_outputs 表（trigger.type='individual_stock_analysis' 即可区分）

---

## 五、验证方案

### 单元
```bash
pytest tests/test_single_stock_mode.py -v -m real_data
```

### 端到端
```bash
# 代码输入
python main.py --stock 300750
# 期望：报告含 3 只股（300750 主 + 2 只对标），Screener 有横向对比说明

# 名称输入
python main.py --stock 宁德时代
# 期望：同上

# 无对标模式（如果想只看一只）
# 需要：CLI 加 --no-peers 参数（可选）

# 不干扰原流程
python main.py              # 仍走 live 事件模式
python main.py default      # 仍走 fixture
```

### 人工验收
- 打开最新 `outputs/runs/run_*.md`：
  - Headline: `个股深度分析：宁德时代（对标 XXX、YYY）`
  - 推荐列表 3 行
  - Screener comparison_summary 有实质对比文字
  - Skeptic 对主股的质疑 ≥ 2 条
- 打开 LangSmith trace：Research 节点的工具调用应该是 `stock_financial_data(300750)` / `stock_financial_data(002594)` / ... 而不是 `akshare_industry_leaders(...)`

---

## 六、与 Phase 3 DB 的关系（已确认：走路径 A）

### 6.1 整体关系

**Phase 4 零 DB schema 改动，所有数据自然落入 Phase 3 已设计的表**：
- 若 Phase 3 已完成：单股分析的 run 直接落盘，通过 `triggers.type='individual_stock_analysis'` 区分
- 若 Phase 3 未完成：单股分析走当前的"state 内存 + outputs/runs/md" 输出

### 6.2 存储映射总览

跑 `python main.py --stock 300750` 产生 1 主股 + 2 对标 = 3 只股票的分析结果时，数据分布：

| 数据 | 落点表 | 记录数 | 该条数据怎么识别这是"个股分析" |
|---|---|---|---|
| 运行元信息 | `runs` | 1 | 无区分（跨所有模式共用） |
| 合成触发信号 | `triggers` | 1 | `type='individual_stock_analysis'` + `source='user_request'` |
| Supervisor 每轮决策 | `agent_outputs` (agent_name='supervisor') | 4 | 通过 run_id 回查 triggers.type |
| Research 顶层 | `agent_outputs` (agent_name='research') | 1 | 同上 |
| 每只股票研究数据（主+2 对标） | `stock_data_entries` | 3 | code 字段 |
| Research 工具调用 | `tool_calls` | ≈9（3 股 × 3 工具） | stock_code 字段 |
| Screener 顶层 + comparison_summary | `agent_outputs` (agent_name='screener') | 1 | |
| 每只股票的推荐打分 | `stock_recommendations` | 3 | 通过 agent_output_id 回查 triggers |
| 每条件×每股打分 | `condition_scores` | ≈15（3 股 × 5 条件） | |
| Skeptic 顶层 | `agent_outputs` (agent_name='skeptic') | 1 | |
| Skeptic 质疑 | `skeptic_findings` | ≥2 | stock_recommendation_id 可查哪些是主股的 |
| AkShare 数据快照 | `financial_snapshots` / `holder_snapshots` / `technical_snapshots` | 各 ≤3 | 与事件驱动共享，跨运行复用 |

### 6.3 `focus_codes` 的存储方案：路径 A（metadata_json）

**决策**：不给 `triggers` 表加专用列，而是放 `triggers.metadata_json` 里——符合 Phase 3 §2 "metadata_json 扩展性" 原则，加新字段零 schema 改动。

**写入（Phase 4 的 `single_stock_trigger.py` 生成 trigger 时）**：

```python
trigger = {
    # ... 其他字段
    "type": "individual_stock_analysis",
    "source": "user_request",
    # focus_codes 和 focus_primary 进 metadata_json
    "_metadata": {
        "focus_codes": ["300750", "002594", "300274"],
        "focus_primary": "300750",
        "peer_names": ["比亚迪", "阳光电源"],
    },
}
# triggers_repo.insert() 时把 _metadata 字典 json.dumps 进 metadata_json 列
```

**读取**：

```sql
-- 某只股票最近 10 次"主动分析"（作为主股被分析）的评分轨迹
SELECT r.total_score, r.recommendation_level, r.created_at, t.headline
FROM stock_recommendations r
JOIN agent_outputs ao ON ao.id = r.agent_output_id
JOIN triggers t ON t.run_id = ao.run_id
WHERE t.type = 'individual_stock_analysis'
  AND json_extract(t.metadata_json, '$.focus_primary') = '300750'
  AND r.code = '300750'
ORDER BY r.created_at DESC LIMIT 10;
```

### 6.4 ★ 新增 SQL 视图：`v_stock_analysis_history`（跨模式股票分析历史）

**动机**：合并"事件驱动候选股 + 个股主动分析"两种模式，一条查询看某只股的完整被分析轨迹（含角色标签）。

```sql
CREATE VIEW v_stock_analysis_history AS
SELECT
  r.code,
  r.name,
  r.total_score,
  r.recommendation_level,
  r.rank,
  r.recommendation_rationale,
  r.key_strengths_json,
  r.key_risks_json,
  t.type AS analysis_type,         -- 'individual_stock_analysis' / 'policy_landing' / 'industry_news' / ...
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
-- 1. 宁德时代所有被分析历史（主动 + 事件驱动）
SELECT created_at, analysis_type, role, total_score, recommendation_level, trigger_headline
FROM v_stock_analysis_history WHERE code='300750' ORDER BY created_at DESC;

-- 2. 只看主动分析（用户主动发起）
SELECT * FROM v_stock_analysis_history
WHERE code='300750' AND role='primary' ORDER BY created_at DESC;

-- 3. 最近一个月被主动分析过的所有股票 + 最近一次评分
SELECT code, name, MAX(created_at) AS last_analysis, total_score, recommendation_level
FROM v_stock_analysis_history
WHERE role='primary' AND created_at >= date('now', '-30 days')
GROUP BY code ORDER BY last_analysis DESC;

-- 4. 事件驱动 vs 主动分析对同一股的评分差异（诊断用）
SELECT code, role, AVG(total_score) AS avg_score, COUNT(*) AS n
FROM v_stock_analysis_history
WHERE code='300750' GROUP BY role;
```

### 6.5 Phase 3 计划需要同步的改动

**新增到 `docs/PHASE3_DB_PLAN.md`**：
- 表 16（新增 SQL View）：`v_stock_analysis_history` 定义（本文档 §6.4 即可复用）
- `triggers.metadata_json` 用法示例加一个 `individual_stock_analysis` 场景
- 步骤 D7 的 `docs/DB_SCHEMA.md` 要补 `focus_codes` / `focus_primary` 的 metadata_json key 约定

### 6.6 推荐实施顺序（两种合理选项，选其一）

| 选项 | 顺序 | 论点 |
|---|---|---|
| **A** | Phase 4（2h）→ Phase 3（8h） | 个股分析是立刻可见的产品功能；先验证"合成 Trigger 复用管道"的架构判断是否站得住；Phase 3 晚一点不影响使用 |
| **B** | Phase 3（8h）→ Phase 4（2h） | 先把持久化底座打好；Phase 4 上线即可查询历史；`v_stock_analysis_history` 视图可一次性建好不返工 |

无强硬建议，取决于你现在更想"能用"还是"能查"。

---

## 七、预计工作量

| 步骤 | 时长 |
|---|---|
| S1 stock_resolver | 0.3h |
| S2 single_stock_trigger | 0.3h |
| S3 research prompt + _candidate_hint | 0.5h |
| S4 main.py CLI | 0.2h |
| S5 screener/skeptic prompt 兼容 | 0.3h |
| S6 测试 | 0.4h |
| **总计** | **≈ 2h** |

---

## 八、审阅要点

请对照以下判断方案是否合理：

1. **合成 Trigger** 思路：给 trigger 加 `focus_codes` 字段复用现有管道，是否符合你的预期？或者你希望单独开一条 graph？
2. **对标股数量 2 只**是否合适？想 3 只或不要也可以改
3. **行业反查**：当前用 `industry_leaders_map.json` 反查 —— 若输入股票不在表里（比如 2026 年新上市的公司），industry 会是"未分类"，Research 可能拉不到好对标。要不要降级到调 AkShare 实时查行业？（代价：多 1 个网络请求；好处：覆盖全市场）
4. **CLI 参数命名**：`--stock` 还是 `--symbol` / `--code`？
5. **与 Phase 3 先做哪个**？

确认无误 + 选好实施顺序后我就开工。
