# 文件名就是 Dockerfile（旧版名为 Dockerfile.txt，导致 compose 的 build 找不到）
# 多阶段构建：构建层装依赖，运行层只保留运行所需内容。

# ---------------------------------------------------------------- 构建层
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# lxml 和 psycopg 需要编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

# 装到独立前缀，便于整体复制到运行层
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install .

# ---------------------------------------------------------------- 运行层
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Shanghai

# 只装运行时库，不含编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行
RUN groupadd --system --gid 1001 ledger \
    && useradd --system --uid 1001 --gid ledger --create-home ledger

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=ledger:ledger src/ ./src/
COPY --chown=ledger:ledger migrations/ ./migrations/
COPY --chown=ledger:ledger alembic.ini ./

# 证据存储目录
RUN mkdir -p /var/lib/ledger/artifacts && chown -R ledger:ledger /var/lib/ledger

USER ledger

EXPOSE 8000

# 默认入口是 Web。scheduler / worker 由 compose 覆盖 command。
# 注意：这里不执行建表或迁移——迁移是发布阶段的独立一次性任务。
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "ledger.wsgi:app"]
