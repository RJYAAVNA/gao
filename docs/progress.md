# 实施进度

## 阶段划分

| 阶段 | 内容 | 状态 |
|---|---|---|
| S1 | 建仓、项目骨架、Docker、PostgreSQL schema + 迁移 | 已完成 |
| S2 | 注册登录（邮箱验证 + 限流）、多用户隔离、账户/产品/交易/持仓 CRUD | 待开始 |
| S3 | 采集层：中银适配器、中国理财网适配器、任务队列、证据存储 | 待开始 |
| S4 | 收益计算：流水重放、日快照、周/月/自定义区间、完整性标记 | 待开始 |
| S5 | 手机端页面、PWA、ECharts 图表 | 待开始 |
| S6 | 阿里云部署、HTTPS、备份、监控 | 待开始 |

## S1 完成内容

### 旧版问题的处理

`01-current-state.md` 列出的 P0 问题，本阶段的处理方式：

| 旧版问题 | 处理 |
|---|---|
| `Dockerfile.txt` 文件名导致 compose 构建失败 | 改为 `deploy/Dockerfile`，compose 显式指定路径 |
| `init_db()` 只在 `__main__` 调用，Gunicorn 首启不建表 | 迁移改为独立的一次性服务，成功退出后 web/worker/scheduler 才启动 |
| 源码与 compose 内嵌默认口令、真实持仓 | 旧文件移入 `legacy/`（已被 gitignore）；配置缺密钥即启动失败，占位值被校验拒绝 |
| 调度器在模块导入阶段启动 | scheduler 独立进程；应用工厂不启动任何后台线程 |
| API 不含用户条件，多用户读写同一份持仓 | `transactions` / `positions` 用复合外键 `(user_id, account_id)`，数据库层面阻止跨用户绑定 |
| 金额用 REAL / float | 全部 NUMERIC + Decimal，有测试扫描所有金额字段 |
| `INSERT OR REPLACE` 覆盖净值 | `observations` 按 revision 保留，`observation_heads` 指向当前有效值 |

P1 中的收益口径问题（当前份额套用历史日期、固定 7/14 天分母、不同净值日直接相加）
属 S4 范围，schema 已为其预留 `position_snapshots.nav_date` 与 `completeness` 字段。

### 数据模型

22 张表，240 个字段，分五组：

- **身份**：`users`、`email_tokens`、`audit_events`
- **公共目录**：`institutions`、`products`、`product_distributions`、`data_sources`、`product_source_mappings`
- **行情**：`raw_artifacts`、`observations`、`observation_heads`、`manual_nav_submissions`
- **用户私有**：`bank_accounts`、`transactions`、`positions`、`import_batches`
- **估值**：`valuation_runs`、`position_snapshots`、`portfolio_snapshots`
- **任务**：`jobs`、`job_attempts`、`schedule_watermarks`

机构按 `institution_type` 区分销售银行与发行机构，两个维度分开建模。
`products.registration_code` 存全国银行业理财登记编码，是对接中国理财网的关键。

### 测试覆盖

130 个测试，不需要数据库即可运行：

- 配置校验：必填项缺失、占位密钥、弱密钥、边界值
- 模型完整性：金额字段类型、时间戳时区、复合外键、唯一约束
- DDL 编译：22 张表逐一编译、枚举 CHECK 用值而非成员名、枚举列宽留余量
- 迁移一致性：离线生成 SQL 与模型 DDL 逐项对比、索引齐全、downgrade 删净、无硬编码凭据
- 应用工厂：Cookie 安全标志、上传限制、健康检查分离、导入无副作用

### 本阶段修正的实现问题

记录三个在验证中发现并修掉的问题，都属于「只在运行时才暴露」的类型：

1. **mixin 列缺少 `Mapped[]` 注解**。SQLAlchemy 2.x 拒绝加载，模型导入即失败。
2. **枚举 CHECK 约束用成员名而非值**。ORM 写入的是 `member.value`（`'bank'`），
   而 CHECK 默认按成员名（`'BANK'`）生成，每次插入都会违反约束。
   需要 `values_callable`；同时 SQLAlchemy 1.4 起默认不生成 CHECK，
   要显式 `create_constraint=True`。
3. **枚举列按当前最长值定宽**。`VARCHAR(5)` 这类列宽在新增更长的枚举值后插入失败。
   统一固定为 32。
4. **`alembic.ini` 含中文导致 Windows 下解析失败**。Alembic 用 `encoding="locale"`
   读该文件，GBK 环境下 UTF-8 多字节字符会抛 `UnicodeDecodeError`。
   该文件保持纯 ASCII，说明移入 `migrations/env.py`。

### 未完成 / 需要环境支持

- **未在真实 PostgreSQL 上执行迁移**。本机没有 Docker，
  迁移经过离线 SQL 生成与模型一致性校验，但没有实际建库验证。
  CI 配置里已包含真实数据库上的 upgrade / downgrade / 幂等测试。
- **未推送 GitHub**。本机没有 `gh` CLI，需要确认远端仓库地址与可见性。

## 待确认事项

- 中国理财网 `/prod/search` 的入参结构需要抓真实浏览器请求（S3 范围，已决定暂不逆向）
- 交银理财、苏银理财官网入口未找到，当前方案是统一走中国理财网
- 邮件发送通道（阿里云邮件推送 / SMTP）需要在 S2 前确定
