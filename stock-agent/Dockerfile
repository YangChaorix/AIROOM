# ============================================================
# 选股Agent Docker镜像
# 基于 python:3.11-slim 构建
# ============================================================

FROM python:3.11-slim

# 设置标签
LABEL maintainer="stock-agent"
LABEL description="A股选股Agent - LangGraph多Agent架构"
LABEL version="1.0.0"

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
# build-essential: 编译某些Python包需要
# curl: 健康检查使用
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements.txt（利用 Docker 层缓存）
COPY requirements.txt .

# 安装 Python 依赖
# 使用阿里云镜像加速（中国大陆环境）
RUN pip install --upgrade pip && \
    pip install -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# 复制项目文件
COPY . .

# 创建非 root 用户运行应用（安全最佳实践）
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口（如果将来添加 Web API）
# EXPOSE 8000

# 健康检查（验证Python环境正常）
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import langchain; import akshare; print('OK')" || exit 1

# 默认入口：分析贵州茅台（600519）作为示例
# 实际使用时通过 docker run 覆盖参数
ENTRYPOINT ["python", "main.py"]
CMD ["600519"]
