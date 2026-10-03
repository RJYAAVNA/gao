# 本地开发环境启动指南

本项目提供两种启动方式：**Docker Compose（推荐）** 和 **手动启动**。

---

## 方式一：使用 Docker Compose（推荐）

这是最简单的方式，所有服务（PostgreSQL、Web、Worker、Scheduler）都会自动启动。

### 前置条件

- Docker 和 Docker Compose 已安装

### 步骤

#### 1. 配置环境变量

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

生成会话密钥并替换 `.env` 中的 `SESSION_SECRET`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**重要**：`.env.example` 中的密码和密钥只是示例，必须替换为安全的随机值。

#### 2. 启动所有服务

```bash
docker compose up -d
```

这会自动完成：
- 创建 PostgreSQL 数据库
- 运行数据库迁移
- 启动 Web 服务器（端口 8000）
- 启动 Worker 进程
- 启动 Scheduler 进程

#### 3. 查看日志

```bash
docker compose logs -f web
```

#### 4. 创建管理员账号

```bash
docker compose run --rm web python scripts/create_admin_user.py \
  --email admin@example.com \
  --password yourpassword \
  --is-admin
```

#### 5. 访问应用

应用已启动在 http://localhost:8000

#### 6. 停止服务

```bash
docker compose down
```

保留数据卷（下次启动数据还在）或完全清理：

```bash
docker compose down -v  # 删除数据卷
```

---

## 方式二：手动启动

如果你不想使用 Docker，可以手动启动各个组件。

### 前置条件

1. PostgreSQL 数据库已安装并运行
2. Python 3.12+ 已安装
3. uv 包管理器已安装

### 步骤

#### 1. 配置环境变量

复制 `.env.example` 为 `.env` 并修改：

```bash
cp .env.example .env
```

生成会话密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将生成的密钥填入 `.env` 文件的 `SESSION_SECRET` 字段。

#### 2. 创建数据库

打开 PostgreSQL 命令行工具（psql）或数据库管理工具，执行：

```sql
CREATE DATABASE ledger;
CREATE USER ledger WITH PASSWORD 'ledger_dev_password';
GRANT ALL PRIVILEGES ON DATABASE ledger TO ledger;
```

**注意**：密码要与 `.env` 文件中的 `POSTGRES_PASSWORD` 一致。

#### 3. 运行数据库迁移

```bash
uv run alembic upgrade head
```

#### 3. 运行数据库迁移

```bash
uv run alembic upgrade head
```

#### 4. 创建管理员账号

```bash
uv run python scripts/create_admin_user.py \
  --email admin@example.com \
  --password yourpassword \
  --is-admin
```

#### 5. 初始化测试数据（可选）

```bash
uv run python scripts/seed_test_data.py
```

#### 6. 启动应用

**启动 Web 服务器**：

```bash
uv run flask --app ledger.app run --debug
```

应用将在 http://localhost:5000 启动（使用 Flask 开发服务器）。

**启动 Worker（后台任务处理）**，在另一个终端窗口：

```bash
uv run python -m ledger.jobs.worker
```

**启动 Scheduler（定时任务生成）**，在另一个终端窗口：

```bash
uv run python -m ledger.jobs.scheduler
```

---

## API 测试示例

以下示例使用 Docker Compose 启动的服务（端口 8000），如果是手动启动请改为端口 5000。

### 登录获取 Session

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"yourpassword"}' \
  -c cookies.txt
```

### 查看当前用户

```bash
curl http://localhost:8000/api/auth/me -b cookies.txt
```

### 列出机构

```bash
curl http://localhost:8000/api/catalog/institutions -b cookies.txt
```

### 列出产品

```bash
curl http://localhost:8000/api/catalog/products -b cookies.txt
```

### 创建数据源（管理员）

```bash
curl -X POST http://localhost:8000/api/catalog/sources \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "collector_name": "bocwm",
    "config": {"product_code": "XXX001"},
    "enabled": true
  }'
```

### 创建产品与源的映射（管理员）

```bash
curl -X POST http://localhost:8000/api/catalog/products/{product_id}/sources \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"source_id": "{source_id}"}'
```

### 手动触发净值同步（管理员）

```bash
curl -X POST http://localhost:8000/api/jobs/trigger-nav-sync \
  -b cookies.txt
```

### 查看任务列表（管理员）

```bash
curl http://localhost:8000/api/jobs -b cookies.txt
```

## 目录结构

```
ledger/
├── api/              # REST API 路由
│   ├── accounts.py   # 账户管理
│   ├── auth.py       # 认证登录
│   ├── catalog.py    # 机构、产品、数据源
│   └── jobs.py       # 任务管理
├── collectors/       # 数据采集器
│   ├── bocwm.py      # 中银理财
│   └── chinawealth.py # 银行理财
├── jobs/             # 后台任务
│   ├── queue.py      # 任务队列
│   ├── worker.py     # 任务执行器
│   └── scheduler.py  # 定时任务生成器
└── db/
    └── models/       # 数据模型
```

## 故障排查

### 数据库连接失败

检查 `.env` 中的 `DATABASE_URL` 是否正确，PostgreSQL 是否正在运行。

### Session 验证失败

确保 `SESSION_SECRET` 已设置且不是占位值。

### Worker 无法启动

确保数据库迁移已完成，`artifacts` 目录存在且可写。

### 采集器报错

检查采集器配置的 `product_code` 是否正确，网络是否可达目标 API。
