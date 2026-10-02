# 多银行理财台账

管理银行理财持仓与交易，自动采集产品净值，按日/周/月/自定义区间跟踪收益，
并能说明每个数字用的是哪天的净值、来自哪个来源、数据是否完整。

当前进度：**S1（项目骨架与数据底座）已完成**。
阶段规划见 [docs/roadmap.md](docs/roadmap.md)，实际交付记录见 [docs/progress.md](docs/progress.md)。

本版本不开放注册，由管理员用 CLI 建号试用功能。

## 技术栈

| 层 | 选型 |
|---|---|
| Web | Flask 3.1（应用工厂 + Blueprint）、Gunicorn |
| 数据库 | PostgreSQL 17、SQLAlchemy 2.0、Alembic |
| 配置与校验 | pydantic-settings、Pydantic v2 |
| 安全 | argon2id 口令哈希、Flask-WTF（CSRF）、Flask-Limiter（限流） |
| 采集 | httpx、tenacity、lxml / BeautifulSoup |
| 任务 | 数据库持久队列（`FOR UPDATE SKIP LOCKED`）+ APScheduler |
| 日志 | structlog（生产输出 JSON） |
| 质量 | pytest、ruff、mypy strict |

## 架构

三类进程共用同一镜像，以不同入口运行：

```
浏览器 → HTTPS 反向代理 → Web (Gunicorn)  ─┐
                                           ├→ PostgreSQL
            Scheduler（生成任务）          ─┤
            Worker（领取任务 → 采集 → 计算）─┘
                     ↓
              原始证据存储（文件 / OSS）
```

关键设计决策：

- **采集离开 Web 请求**。网页只投递任务并立即返回 `202 + job_id`，
  避免多个银行接口串行超时拖垮请求。
- **公共行情共享，持仓按用户隔离**。同一产品只采集一次；
  `transactions` / `positions` 用复合外键 `(user_id, account_id)` 在数据库层面
  阻止跨用户写入。
- **用交易流水重建持仓**。当前份额不能代表历史份额，
  所以每日快照由流水重放生成，净值修订后可重算。
- **行情不覆盖**。观测值按 revision 保留历史，
  `observation_heads` 指向当前有效值，修订可追溯。
- **金额一律 Decimal / NUMERIC**。浮点不参与金额累计。

更完整的设计说明在 [repo.wiki/](repo.wiki/)。

## 本地开发

需要 Python 3.12 与 Docker（数据库）。

```bash
cp .env.example .env
```

填入 `.env`：`POSTGRES_PASSWORD` 和 `SESSION_SECRET`。生成密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

安装依赖：

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

启动全部服务（含自动迁移）：

```bash
docker compose up --build
```

创建管理员（密码从标准输入读取，不进 shell 历史）：

```bash
docker compose run --rm web python -m ledger.cli create-admin --username admin --email you@example.com
```

写入机构参考数据：

```bash
docker compose run --rm web python -m ledger.cli seed-institutions
```

## 质量门槛

四项全部通过才提交：

```bash
uv run ruff format --check src tests migrations
```

```bash
uv run ruff check src tests migrations
```

```bash
uv run mypy src/ledger
```

```bash
uv run pytest
```

## 数据库迁移

迁移是发布阶段的独立一次性任务，应用启动时不建表。

```bash
uv run alembic upgrade head
```

修改模型后生成迁移（需要可连接的数据库）：

```bash
uv run alembic revision --autogenerate -m "描述改动"
```

`tests/unit/test_migration_matches_models.py` 会校验迁移与模型是否一致，
漏写迁移会直接导致测试失败。

## 目录结构

```text
src/ledger/
  config.py          配置（缺密钥则启动失败）
  app.py             应用工厂
  cli.py             运维命令：建管理员、机构种子、配置自检
  wsgi.py            Gunicorn 入口
  db/
    base.py          ORM 基类、金额列类型、枚举列约定
    models/          22 张表的模型定义
    session.py       引擎与短事务上下文
  auth/              用户、会话、权限
  catalog/           机构、产品、销售渠道
  portfolio/         账户、流水、持仓
  market_data/       行情标准化、校验、选择、修订
  collectors/        各数据源适配器
  valuation/         持仓重放、收益、周期汇总
  jobs/              scheduler / worker
  api/               /api/v1 路由与 DTO
migrations/          Alembic 迁移
tests/               unit / integration / contracts
deploy/              Dockerfile
docs/                进度与决策记录
legacy/              旧版单文件应用（不入库，仅本地参考）
```

## 安全约定

- 生产缺少 `SESSION_SECRET` 或 `DATABASE_URL` 时进程启动失败，没有默认值兜底。

- 占位密钥（`change-me` 等）会被配置校验拒绝。

- 数据库不对公网暴露；容器以非 root 用户运行。

- 日志不记录持仓金额、口令、会话内容与账单原文。

- 用户上传的账单属私有证据，必须绑定 `user_id`，未经审核不转为公共行情。

- 普通用户提交的手工净值只是候选，需管理员审核才影响公共行情。

  ## 开发阶段规划

  | 阶段 | 内容                                                         | 找你确认什么                     |
  | ---- | ------------------------------------------------------------ | -------------------------------- |
  | S1   | GitHub 建仓（清理种子数据和凭据）、项目骨架、Docker Compose、PostgreSQL schema + Alembic 迁移 | 仓库建好后给你看目录结构和表设计 |
  | S2   | 注册登录（邮箱验证+限流）、多用户隔离、账户/产品/交易/持仓 CRUD | 跑起来给你试用，确认交互         |
  | S3   | 采集层：中银适配器 + 中国理财网适配器 + 任务队列 + 证据存储  | 给你看真实采集结果和数据准确性   |
  | S4   | 收益计算（流水重放、日快照、周/月/自定义区间）+ 完整性标记   | 用你的真实数据对账               |
  | S5   | 手机端页面 + PWA + ECharts 图表                              | 你在手机上实际用                 |
  | S6   | 阿里云部署 + HTTPS + 备份 + 监控                             | 上线前确认安全配置               |
