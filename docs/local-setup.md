# 本地开发环境启动指南

## 前置条件

1. PostgreSQL 数据库已安装并运行
2. Python 3.12+ 已安装
3. uv 包管理器已安装

## 步骤

### 1. 配置环境变量

复制 `.env.example` 为 `.env` 并填写真实值：

```bash
cp .env.example .env
```

生成会话密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将生成的密钥填入 `.env` 文件的 `SESSION_SECRET` 字段。

### 2. 创建数据库

```sql
CREATE DATABASE ledger;
CREATE USER ledger WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE ledger TO ledger;
```

### 3. 运行数据库迁移

```bash
uv run alembic upgrade head
```

### 4. 创建管理员账号

```bash
uv run python scripts/create_admin_user.py --email admin@example.com --password yourpassword --is-admin
```

### 5. 初始化测试数据（可选）

```bash
uv run python scripts/seed_test_data.py
```

### 6. 启动应用

#### 启动 Web 服务器

```bash
uv run flask --app ledger.app run --debug
```

应用将在 http://127.0.0.1:5000 启动。

#### 启动 Worker（后台任务处理）

在另一个终端窗口：

```bash
uv run python -m ledger.jobs.worker
```

#### 启动 Scheduler（定时任务生成，可选）

在另一个终端窗口：

```bash
uv run python -m ledger.jobs.scheduler
```

## API 测试

### 登录获取 Session

```bash
curl -X POST http://127.0.0.1:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"yourpassword"}' \
  -c cookies.txt
```

### 查看当前用户

```bash
curl http://127.0.0.1:5000/api/auth/me -b cookies.txt
```

### 列出机构

```bash
curl http://127.0.0.1:5000/api/catalog/institutions -b cookies.txt
```

### 列出产品

```bash
curl http://127.0.0.1:5000/api/catalog/products -b cookies.txt
```

### 创建数据源（管理员）

```bash
curl -X POST http://127.0.0.1:5000/api/catalog/sources \
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
curl -X POST http://127.0.0.1:5000/api/catalog/products/{product_id}/sources \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"source_id": "{source_id}"}'
```

### 手动触发净值同步（管理员）

```bash
curl -X POST http://127.0.0.1:5000/api/jobs/trigger-nav-sync \
  -b cookies.txt
```

### 查看任务列表（管理员）

```bash
curl http://127.0.0.1:5000/api/jobs -b cookies.txt
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
