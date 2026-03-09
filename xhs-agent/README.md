# xhs-agent — 小红书自动运营脚本

每天自动抓取热点、生成文案、发布 1~2 篇笔记。

**完全独立的 Python 项目，不依赖 OpenClaw 运行时。**
OpenClaw 仅作为定时触发器使用（可替换为系统 cron）。

---

## 目录结构

```
xhs-agent/
├── run.py              # 主入口，串联完整流程
├── xhs_tool.py         # 小红书操作封装（trending / publish / analytics）
├── generate.py         # 调用 LLM 生成文案
├── setup.sh            # 一键初始化脚本
├── requirements.txt    # 依赖列表
├── config/
│   └── settings.json   # 账号风格、标签、发布频率配置
├── logs/               # 每日运行日志（自动创建）
└── images/             # 待发布图片目录（可选）
```

凭证单独存放（不进 git）：
```
~/.openclaw/credentials/xhs.json   # a1 + web_session
```

---

## 快速开始

### 1. 初始化环境

```bash
cd /workspaces/AIROOM/xhs-agent
chmod +x setup.sh && ./setup.sh
```

### 2. 填写 Cookie

登录 [xiaohongshu.com](https://www.xiaohongshu.com) → F12 → Application → Cookies，复制：
- `a1`
- `web_session`

```bash
nano ~/.openclaw/credentials/xhs.json
```

```json
{
  "a1": "你的a1值",
  "web_session": "你的web_session值"
}
```

### 3. 配置账号风格

```bash
nano config/settings.json
```

填写 `account.style`（如
：职场干货、穿搭分享、美食探店）和常用标签。

### 4. 测试运行（不发布）

```bash
.venv/bin/python run.py --dry-run
```

### 5. 正式运行

```bash
.venv/bin/python run.py
```

---

## 定时触发

### 方式 A：OpenClaw cron（推荐）

在 OpenClaw 控制台添加 cron job：
- 时间：每天 09:00
- 命令：`cd /workspaces/AIROOM/xhs-agent && .venv/bin/python run.py`

### 方式 B：系统 cron（备选，完全脱离 OpenClaw）

```bash
crontab -e
# 添加：
0 9 * * * cd /workspaces/AIROOM/xhs-agent && .venv/bin/python run.py >> logs/cron.log 2>&1
```

---

## 常见问题

**Cookie 失效怎么办？**
重新登录小红书，F12 复制新的 a1 和 web_session，更新 `~/.openclaw/credentials/xhs.json`。Cookie 有效期通常为数周到数月。

**发布图文笔记**
把图片放入 `images/` 目录，在 `generate.py` 的输出中加入 `image_paths` 字段，或手动在 `run.py` 中指定。

**如何更换 LLM 模型？**
修改 `generate.py` 中的 `model="claude-haiku-4-5"` 为其他模型名称。

---

## 风险说明

- 使用非官方 API，存在封号风险
- 频率控制在 1~2 篇/天，风险极低
- 仅用于个人账号自有内容发布
