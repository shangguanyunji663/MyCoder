# MyCoder API 服务镜像
# 用法: docker build -t mycoder-harness .
#       docker run --rm -p 8910:8910 --ollama 组合见 docker-compose.yml
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MYCODER_CONFIG=/app/config/docker.yaml

WORKDIR /app

# 源码 + 安装(普通安装,非 editable;依赖 .dockerignore 裁剪体积)
COPY pyproject.toml README.md ./
COPY mycoder ./mycoder
COPY config ./config
RUN pip install ".[api]"

# 运行期数据(记忆/检查点/工件/日志)统一放 /app/.mycoder,便于卷挂载
RUN mkdir -p /app/.mycoder/workspace

EXPOSE 8910

CMD ["mycoder", "serve", "--impl", "fastapi", "--host", "0.0.0.0", "--port", "8910", "--config", "config/docker.yaml"]
