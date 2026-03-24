# 阿里云服务器运维手册

> 服务器目录：`/opt/project/stock-agent`
> 服务端口：`8888`
> 镜像名称：`stock-agent-v3:latest`

---

## 目录结构

```
/opt/project/stock-agent/
├── docker-compose.yaml      # 容器编排配置
├── .env                     # API Keys（勿提交）
├── config/
│   └── models.json          # 模型配置
├── data/
│   └── db/
│       └── stock_agent.db   # SQLite 数据库
├── logs/                    # 运行日志（按日期）
└── stock-agent-v3.tar.gz   # 镜像包（更新时上传）
```

---

## 一、首次部署

### 1. 创建目录并设置权限

```bash
mkdir -p /opt/project/stock-agent/data/db
mkdir -p /opt/project/stock-agent/logs
mkdir -p /opt/project/stock-agent/config
chmod -R 777 /opt/project/stock-agent/data
chmod -R 777 /opt/project/stock-agent/logs
```

### 2. 上传文件（本地执行）

```bash
scp stock-agent-v3.tar.gz   root@<IP>:/opt/project/stock-agent/
scp docker/docker-compose.yaml root@<IP>:/opt/project/stock-agent/
scp .env                    root@<IP>:/opt/project/stock-agent/
scp config/models.json      root@<IP>:/opt/project/stock-agent/config/
```

### 3. 导入镜像

```bash
cd /opt/project/stock-agent
docker load < stock-agent-v3.tar.gz
```

### 4. 初始化数据库（首次必须）

```bash
docker run --rm \
  -v /opt/project/stock-agent/data:/app/data \
  -v /opt/project/stock-agent/logs:/app/logs \
  -v /opt/project/stock-agent/.env:/app/.env:ro \
  -v /opt/project/stock-agent/config/models.json:/app/config/models.json:ro \
  stock-agent-v3:latest python main.py --init-db
```

> 单行版本（避免反斜杠问题）：
> ```bash
> docker run --rm -v /opt/project/stock-agent/data:/app/data -v /opt/project/stock-agent/logs:/app/logs -v /opt/project/stock-agent/.env:/app/.env:ro -v /opt/project/stock-agent/config/models.json:/app/config/models.json:ro stock-agent-v3:latest python main.py --init-db
> ```

### 5. 启动服务

```bash
docker compose up -d
docker compose ps   # 确认两个容器均为 running/healthy
```

### 6. 开放安全组端口

阿里云控制台 → ECS → 安全组 → 入方向规则：

| 端口 | 协议 | 来源 |
|------|------|------|
| 8888 | TCP | 0.0.0.0/0 |

---

## 二、版本更新（常规流程）

每次代码更新后，本地重新打包镜像，然后按以下步骤替换。

### 本地打包（Mac 执行）

```bash
# 构建 amd64 镜像（服务器架构）
docker build --platform linux/amd64 -f docker/Dockerfile -t stock-agent-v3:latest .

# 导出为压缩包
docker save stock-agent-v3:latest | gzip > stock-agent-v3.tar.gz

# 上传到服务器
scp stock-agent-v3.tar.gz root@<IP>:/opt/project/stock-agent/
```

### 服务器替换镜像

```bash
cd /opt/project/stock-agent

# 1. 停止服务
docker compose down

# 2. 删除旧镜像
docker rmi stock-agent-v3:latest

# 3. 导入新镜像
docker load < stock-agent-v3.tar.gz

# 4. 启动服务
docker compose up -d

# 5. 确认状态
docker compose ps
```

> **注意**：常规更新不需要重新 `--init-db`，数据库会自动兼容。

---

## 三、仅重启某个容器

```bash
# 重启 agent（调度配置变更后需要）
docker compose restart agent

# 重启 web（界面/API 更新后）
docker compose restart web

# 重启全部
docker compose restart
```

---

## 四、查看日志

```bash
# 实时查看 agent 日志
docker compose logs -f agent

# 实时查看 web 日志
docker compose logs -f web

# 查看最近 100 行
docker compose logs --tail=100 agent

# 查看文件日志（按日期）
tail -f /opt/project/stock-agent/logs/$(date +%Y-%m-%d).log
```

---

## 五、手动触发分析

```bash
# 手动执行一次触发+精筛
docker compose exec agent python main.py --event

# 手动执行新闻采集
docker compose exec agent python main.py --collect

# 手动执行复盘
docker compose exec agent python main.py --review
```

---

## 六、数据库操作

```bash
# 进入容器操作 SQLite
docker compose exec agent sqlite3 /app/data/db/stock_agent.db

# 常用 SQL
.tables                          # 查看所有表
SELECT * FROM system_config;     # 查看系统配置
SELECT COUNT(*) FROM news_items; # 查看新闻数量
.quit
```

---

## 七、更新配置文件

### 更新 .env（API Keys 等）

```bash
# 上传新 .env（本地执行）
scp .env root@<IP>:/opt/project/stock-agent/

# 重启服务使配置生效
docker compose restart
```

### 更新 models.json（模型配置）

```bash
scp config/models.json root@<IP>:/opt/project/stock-agent/config/

# 重启服务
docker compose restart
```

---

## 八、常见问题排查

### 容器 unhealthy / 启动失败

```bash
# 查看详细错误日志
docker logs stock-agent-web-1
docker logs stock-agent-agent-1
```

**常见原因：**

| 错误信息 | 原因 | 解决方案 |
|----------|------|----------|
| `Permission denied: /app/logs/...` | logs 目录权限不足 | `chmod -R 777 /opt/project/stock-agent/logs` |
| `unable to open database file` | data/db 目录权限不足 | `chmod -R 777 /opt/project/stock-agent/data` |
| `no such table: system_config` | 数据库未初始化 | 重新执行 `--init-db` |
| `platform linux/arm64 does not match` | 镜像架构不符 | 本地用 `--platform linux/amd64` 重新构建 |

### 端口被占用

```bash
# 查看 8888 端口占用
lsof -i :8888
# 或
netstat -tlnp | grep 8888
```

### 磁盘空间不足

```bash
# 查看磁盘使用
df -h

# 清理旧 Docker 资源
docker system prune -f

# 清理旧日志（保留最近 7 天）
find /opt/project/stock-agent/logs -name "*.log" -mtime +7 -delete
```

---

## 九、更新记录

| 日期 | 版本说明 |
|------|----------|
| 2026-03-24 | 初始部署，amd64 镜像，含调度配置 UI、主题切换、个股分析等功能 |
