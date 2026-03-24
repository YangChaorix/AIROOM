FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 layer 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（.env 和 data/ 通过挂载卷注入，不打进镜像）
COPY agents/     agents/
COPY config/     config/
COPY graph/      graph/
COPY tools/      tools/
COPY web/        web/
COPY main.py     .
COPY web_server.py .

# 运行时目录（挂载卷会覆盖，这里只是保证容器内路径存在）
RUN mkdir -p data/db logs

# 非 root 用户
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8888
