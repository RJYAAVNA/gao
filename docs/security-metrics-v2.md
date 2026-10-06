# 多银行理财台账 v2：实现说明与发布验收

更新时间：2026-10-04。基于 `09cf0a5` 工作区，保留原有未提交文件。本次已修改代码和新增迁移，**未对现有账本数据库执行迁移、重建或生产发布**。

## 交付状态

| 范围 | 本次实现 | 发布前限制 |
|---|---|---|
| 认证和隔离 | 页面/API 共用认证；失败计数和审计提交；可撤销会话；停用检查；CSRF；身份上下文；管理员任务权限 | 已在隔离 PostgreSQL 17.11 执行并发与租约测试 |
| 浏览器 | 多标签同步；旧上下文拒绝提交；异步响应隔离；私有 no-store；静态资源 SW；独立离线页 | 已执行本机 Edge 无头测试，其他目标浏览器仍应验收 |
| 账本 | 共享重放；赎回前成本；全清仓收益；费用；冲正；成对红利再投；历史补录重建 | 无配对、顺序不明确或非法旧账须人工核对，不自动改账 |
| 收益 | 资金占用单利年化；披露区间收益；每万元市值收益；币种分组；空值语义；前后端共用读模型 | 分红/拆分的公共复权数据接入未完成；遇已知分红返回缺失原因 |
| 行情和任务 | 同日修订、Head、冲突阻断、受影响用户重算；租约回收及发布校验；每日 03/12/20 时调度 | 公共来源上线前仍需真实样本核验 |
| 配置来源 | JSON/HTML 草稿、隔离预览、冻结版本审核、域名批准、启停、证据下载、私有任务进度 | 网络出口私网阻断需要部署层实施；HTTPS 固定解析地址的应用防护已实现 |
| 建设银行 | 公开目录分页发现、历史净值/现金管理采集、审核映射、覆盖清单、历史回填；真实样本契约通过 | 目录候选须核对发行人、份额及币种；尚未逐一映射全部公开产品 |

建行公开入口：[理财净值](https://www.ccb.com/cn/finance/products/net_value/list.html)、[产品信息](https://www.ccb.com/cn/home/product_info.html)。已通过正常证书校验的 Edge 验证 `www3.ccb.com/tran/WCCMainPlatV5`：NLC165 查询公开目录，NLC164 查询历史指标。Python 原生 TLS 遇到旧协议兼容错误，因此适配器使用隔离浏览器，未降低 TLS 或证书校验；仅保留临时公共匿名行情会话，不使用个人银行凭据。

## 认证和权限

- `ledger_identity` 只保存高熵随机值；数据库保存哈希。旧的签名 `user_id` Cookie 不再认证。
- 空闲 30 分钟、绝对 7 天；读取接口轮询不续空闲时间。退出撤销当前会话，改密撤销该用户全部会话。每次请求检查用户当前状态和角色。
- 登录失败计数、锁定和审计由认证事务提交。PostgreSQL 下使用用户行锁和 IP advisory lock，登录共享限流为每 IP 每分钟 5 次。
- 登录与其他写接口均受 CSRF 保护；已登录写请求另外检查 `X-Auth-Context`。表单使用隐藏字段 `auth_context`。
- `GET /api/auth/csrf` 返回 `csrf_token`、`auth_context`；API 客户端在 Cookie 会话下必须同时发送 `X-CSRFToken`、`X-Auth-Context`。登录成功后更新两者。
- 页面退出只接受 POST；普通用户不得访问全局 `/api/jobs`。本人任务通过 `/api/my/jobs/{id}` 查询，不返回内部 payload。
- 页面默认遮蔽私有区域，验证当前身份后再显示。BroadcastChannel 和 storage 仅传身份变化标识。恢复标签、后退恢复均重新验证。
- `/sw.js` 只缓存静态公共资源及无身份脚本的 `/offline`；清理 `ledger-` 旧缓存及旧 `/static/` 注册。
- 生产关闭 Secure Cookie 将拒绝创建应用。数据库用户停用即时阻止后续访问；运行中已绑定身份的请求不会改为另一用户。

## 计算口径与可解释性

`P = 市值 - 剩余成本 + 本轮已实现赎回收益 + 分红 - 独立费用`。

`A = Σ每日确认交易后的剩余成本`，区间为建仓日至实际净值日 `[S,D)`，单位为元·天。

`持仓年化 = P × 365 / A`。10,000 元持有 30 天收益 30 元，结果 3.65%。真实净值未更新时年化截止日不向后延长；不足一天、缺历史或缺净值返回 `null`。

`最新收益 = 累计收益(D1) - 累计收益(D0)`，D0/D1 是相邻真实披露日，纳入该区间内实际交易。冲正后的同一账本用于区间两端，避免假现金流。清仓收益保留为零市值的历史记录。

`最新万收 = (NAV1 / NAV0 - 1) × 10000`，是每万元期初市值的披露区间收益，不是官方每万份收益。存在已知分红而无公共复权证据时不计算该数字。当前尚不能自动发现公共拆分或除息事件，相关产品须先核验数据，不应宣称已经实现完整复权总回报。

现金管理类仅返回官方万份收益和七日年化，不用净值法计算个人收益。组合按币种分组；混合披露日期会标识不一致；组合万收要求相同区间和无影响可比性的现金流。金额均返回 Decimal 字符串，缺失是 null，真实零保留。

周期 ID 使用首次建仓交易 ID；同日排序为生效日、创建时间和交易 ID。清仓后再买开启新周期，旧周期明细进入快照 `metrics.closed_cycles`。期初余额标记历史不完整。清仓后费用/分红必须显式填写 `cycle_ref`，避免计入新周期。

新增/更新接口：

- `GET /api/positions`：保留基础字段，新增 `metrics`；按账户、银行、状态、币种筛选和精确值排序。
- `GET /api/portfolio/summary`：与卡片共用读模型，按币种返回汇总。
- `POST /api/valuation/runs`、`POST /api/valuation/recalculate`：返回 `202 + run_id + job_id`。
- 页面 `/`、`/positions`、`/positions/{id}` 共用 v2 结果；新账本正在重算时不会把旧快照冒充更新后的收益。

## 用户配置采集

流程：创建草稿 → 管理员批准域名 → 试抓取 → 核对预览 → 提交冻结版本 → 管理员审核 → 生成公共来源和映射。

- `/sources` 为用户和管理员提供相应操作。用户不能传入 `allowed_domains` 或 `verified_contract` 信任字段。
- `/api/source-proposals` 创建/列出本人申请；`/{id}` 查看/更新。更新生成新版本，旧公共来源在新版本批准前继续使用旧规则。
- `/{id}/preview` 异步预览；`/{id}/submit` 提交当前版本。
- `/api/admin/domains` 审批公开域名；`/api/admin/source-proposals` 查看申请；`/{id}/review` 必须带版本、结论和理由。
- `/api/admin/sources` 列出来源；`/{id}` PATCH 启停，版本增加使旧任务失效。
- `/api/catalog/products/{id}/sync` 仅允许本人已有持仓关系的产品，每小时最多 20 次；公共抓取可共享，每人只取得自己的请求关联。
- 预览每用户每小时 10 次、最多 3 页、60 秒、总响应 5 MB；预览不写 Observation。
- JSON 固定字段路径和 HTML 表格列提取；不执行脚本，不接收个人 Cookie、口令或任意代码。压缩响应当前拒绝，避免解压炸弹。
- DNS 所有地址及实际连接地址必须公网；使用已解析 IP 建连且保留正确 SNI/证书校验；每次重定向重新检查 URL。只允许已批准域名 HTTPS 443。
- Worker 通过 PostgreSQL 会话 advisory lock 实现同域名单路采集，释放前留 2 秒间隔，网络期间不持有数据库事务。来源连续失败 5 次暂停；启用时重置失败计数。
- 原始证据存储目录由 `ARTIFACT_STORAGE_PATH` 统一配置；预览证据需要本人或管理员权限，路径限制在存储根目录。

## 建行接入与运行

真实公共响应冻结于 `tests/contracts/fixtures/ccb/`，包含建信净值、浦银理财代销、现金管理、两页目录、历史分页和无数据区间。采样时目录返回 7,423 条、743 页；这只是当次公开目录规模，不代表这些产品均已映射或都存在完整公开行情。适配器真实抓取已取得建信产品 2026-09-30 至 10-03 的单位/累计净值。七日年化原始值按比例保存，官方万份收益与七日年化日期分别保留。

管理员在 `/sources` 查询建行候选，搜索已有产品并核对发行机构、销售银行、份额、币种后审核启用。不根据名称自动猜测产品身份。接口：

- `POST /api/admin/ccb/discovery`：指定 first_page/last_page，每页独立任务，自动串联至所选范围末页。
- `GET /api/admin/ccb/discovery/{job_id}`：查询目录候选和后续任务。
- `POST /api/admin/ccb/sources`：审核映射并排队首次采集。
- `GET /api/admin/ccb/coverage/{capture_id}`：输出已采集页数及候选待映射、待行情、已支持、暂停状态。
- `POST /api/admin/sources/{id}/backfill`：按不超过 31 天的窗口排队历史回填，总范围最多 3,660 天。

生产 Worker 需要 Playwright Chromium。Dockerfile 已加入安装步骤；非 Docker 环境运行 `python -m playwright install chromium`，Windows 可配置 `CCB_BROWSER_CHANNEL=msedge`。浏览器请求固定到已验证公网地址和建行固定路径，阻止其他请求、页面脚本、服务工作线程；流式响应大小限制 5 MB。常规采集默认近 30 天，历史由回填接口处理。

定时与用户请求共用包含来源版本的小时去重键，来源重新审核后不会复用旧配置任务。来源停用或连续失败暂停会重新选择有效行情并排队受影响用户重算，冲突不会回退到该来源更旧的修订。

## 迁移与历史重建

新增迁移 `0002_security_metrics`，不修改已发布初始迁移。新增可撤销会话、申请/版本/域名/任务关联，快照 metrics 与所有权复合约束，以及每用户当前估值的部分唯一索引。DataSource 回填稳定 source_key 并移除 adapter_key 唯一性。

先备份，在专用测试库演练：

```sh
alembic upgrade head
alembic check
python -m ledger.cli rebuild-v2
```

`rebuild-v2` 默认只重放验证并输出用户级待核对原因，不修改账本。验证通过后，在发布窗口执行：

```sh
python -m ledger.cli rebuild-v2 --apply
# 或仅处理一个用户
python -m ledger.cli rebuild-v2 --user-id USER_UUID --apply
```

按用户事务重建投影并排队估值，Worker 生成 v2 快照后原子发布，旧快照保留。非法赎回、缺失冲正引用等产生 `needs_review`，不静默修账。旧会话统一重新登录。

回滚开关：`METRICS_V2_ENABLED=false` 使页面不展示新指标；`SOURCE_COLLECTION_ENABLED=false` 使采集/预览任务取消而不请求外部站点。开关不删除修订、证据、审核或历史快照。不要为应用回滚直接执行破坏性降级迁移。

## 验证方法和待完成门槛

```sh
python -m ruff check src tests migrations
python -m ruff format --check src tests migrations
python -m mypy src/ledger
python -m pytest
```

默认测试使用隔离内存数据库，不读取或清理开发账本。专用 PostgreSQL 测试连接通过 `TEST_POSTGRES_URL` 设置，数据库名必须以 `_test` 结尾；每例使用随机独立 schema，清理仅涉及该 schema：

```sh
TEST_POSTGRES_URL=postgresql://.../ledger_test python -m pytest tests/integration tests/v2
RUN_BROWSER_TESTS=1 python -m pytest tests/browser
```

Windows 可设置 `BROWSER_CHANNEL=msedge` 使用已安装 Edge；其他环境先 `python -m playwright install chromium`。CI 已接入 PostgreSQL 和 Chromium 回归。

最终验收记录（2026-10-04）：

| 检查 | 结果 |
|---|---|
| 默认完整测试 | 228 passed、6 skipped；跳过项需要专用 PostgreSQL 或浏览器条件 |
| PostgreSQL integration + v2 | 45 passed、1 skipped；其中跳过项为 SQLite 专用路径 |
| Edge 多标签/PWA/来源页面回归 | 1 passed |
| 建行真实公共响应契约 | 5 passed，包含在默认测试中 |
| 建行适配器真实请求 | 成功返回 8 条单位/累计净值 |
| Ruff / 格式 / mypy | 全部通过，63 个源码文件类型检查通过 |
| Alembic 升级/降级重演/模型检查 | 全部通过，仅隔离测试库 |

上述测试集合有重叠，不把各行数量相加作为总用例数。

本机已验证：收益案例、清仓持仓、补录/冲正、来源版本审批和归属、数字零值、SSRF 地址边界、行情修订和冲突、会话撤销/锁定/CSRF、页面/API 身份一致；Edge 验证多标签退出/换号、后退、离线以及来源草稿流程。

已在本机独立 PostgreSQL 17.11 测试库完成迁移升级、重复升级、降级至 base 后重新升级以及 `alembic check`，模型与迁移一致。该临时实例仅含合成测试数据，未连接或修改原有业务数据库。真实 PostgreSQL 测试覆盖并发领取、租约、版本发布，以及“私有预览 → 审核 → 抓取 → Head → 本人估值”的完整链路。

发布前仍需：备份并演练真实旧账迁移，处理异常历史记录，核对目标产品映射，部署网络出口私网阻断，并验证目标运行环境。Docker Desktop 服务在本机不可用，Docker 镜像实际构建未验证。应用层地址固定不能替代部署层出口策略；Worker 仅应获准连接必要的数据库、DNS 与公开 HTTPS，禁止其余私网和云元数据访问。公共分红/拆分复权链路尚未接入，相关产品不能宣称完整复权总回报。

本次交付未执行生产发布，不将测试通过等同于所有银行产品覆盖或生产上线。
