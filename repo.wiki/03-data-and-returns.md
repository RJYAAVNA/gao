# 数据模型与收益口径

## 公共和私有数据分离

以下为逻辑模型，尚未生成或执行 DDL。主键建议使用 UUID；时间戳存 UTC，业务日期按 Asia/Shanghai 解释。金额、份额、净值采用 Python Decimal / PostgreSQL NUMERIC，不用二进制浮点累计金额。初始可选金额 `NUMERIC(24,8)`、份额和净值 `NUMERIC(28,12)`；最终精度结合数据源验证，展示人民币金额时才舍入到分。

| 表 | 关键字段 | 约束与用途 |
| --- | --- | --- |
| users | id, username, password_hash, status, role | username 唯一；管理员与普通用户分离 |
| institutions | id, name, institution_type | 银行、理财发行机构分别登记 |
| products | id, issuer_id, issuer_code, share_class, name, currency, valuation_method, min_holding_days | `(issuer_id, issuer_code, share_class)` 唯一；share_class 用非空规范值；不放用户份额 |
| product_distributions | id, product_id, bank_id, channel_code | `(bank_id, channel_code)` 唯一；不同销售银行可对应同一产品 |
| data_sources | id, institution_id, adapter_key, base_url, schedule, enabled, priority, config_version | 来源、调度和配置可版本化；密钥存引用 |
| product_source_mappings | product_id, source_id, source_product_id | 来源内代码唯一映射；避免按名字模糊匹配后直接入账 |
| raw_artifacts | id, source_id, owner_user_id?, storage_key, sha256, fetched_at, content_type | 公开/私有证据分区；私有文件严格授权 |
| observations | id, product_id, source_id, valuation_date, metric_type, value, revision, artifact_id, parser_version, quality_status | `(product_id, source_id, valuation_date, metric_type, revision)` 唯一；保留候选和修订 |
| observation_heads | product_id, valuation_date, metric_type, observation_id, selection_version | 每产品/日期/指标只选一个当前有效值；原始版本不删除 |
| bank_accounts | id, user_id, bank_id, alias, masked_account, currency | 不要求保存完整银行卡号；`UNIQUE(user_id,id)` 支持复合外键 |
| import_batches | id, user_id, artifact_id, status, mapping_version, confirmed_at | 预览→确认；文件 hash + 用户范围去重 |
| transactions | id, user_id, account_id, product_id, type, effective_date, shares_delta, cash_amount, fee, cost_basis?, external_ref?, import_batch_id?, reversal_of? | 所有权复合外键；用户范围幂等键；已确认流水用冲正/补录更正 |
| positions | id, user_id, account_id, product_id, shares, remaining_cost, ledger_version | `(user_id,account_id,product_id)` 唯一；可从流水重建的投影 |
| valuation_runs | id, user_id, from_date, to_date, input_version, formula_version, status | 锁定一次计算输入；重算成功后切换当前版本 |
| position_snapshots | run_id, user_id, account_id, product_id, date, shares, cost, market_value, unrealized_pnl, realized_pnl_cumulative, nav_observation_id, nav_date, quality | 每计算版本/账户/产品/日期唯一；记录实际使用的净值 |
| portfolio_snapshots | run_id, user_id, date, currency, market_value, cumulative_pnl, period_pnl, completeness | 每版本/用户/日期/币种唯一；旧版本可追溯 |
| jobs / job_attempts | id, type, dedupe_key, payload_version, status, run_after, lease_until, lease_version / attempt, error_type | 持久任务、领取、退避、重试明细 |
| audit_events | actor_id, action, entity_type, entity_id, before_ref, after_ref, created_at | 记录流水修正、来源配置、净值审核等操作；避免日志复制敏感内容 |

`transactions` 的推荐事件类型：opening_balance、buy、redeem、cash_dividend、reinvest_dividend、fee、reversal。`cash_amount` 为非负业务金额，符号由事件类型解释；份额增减单独记录；手续费独立记录，不能既计入净支出又重复扣减。买入/赎回按确认生效日改变份额；申请中和未确认交易不进入已确认收益。

## 用户隔离必须贯穿整条链路

- session 保存稳定用户 ID；服务层从身份上下文读取 user_id，不信任请求正文传入的 user_id。
- 所有私有读写都用 `(user_id, entity_id)` 查询。账户归属通过 `(user_id, account_id)` 复合外键约束，防止给自己的流水绑定别人的账户。
- 导入文件、下载、缓存、快照、后台任务、导出与日志同样执行隔离；缓存键包含用户 ID 和计算版本。
- 普通用户提交的手工净值作为候选，只有授权管理员审核后才能改变公共行情；用户不能覆盖其他用户依赖的共享净值。
- 第一版强制服务层授权与跨用户测试；可以加 PostgreSQL RLS 作为第二层防护。启用时 Web 数据库角色不得是表所有者或带 BYPASSRLS；事务内设置用户上下文并防止连接池泄漏，后台角色权限单独控制。参见 [PostgreSQL 行级安全](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)。

## 行情选择与修订

单位净值、累计净值、万份收益和七日年化是不同 `metric_type`，不能相互替代。单位净值用于净值型持仓估值；累计净值不能直接乘以份额当资产市值。

默认选取已校验的发行机构官方来源；其他官方销售渠道作为备选。来源冲突时保留全部候选，超出配置容差则标记争议。OCR 低置信度值不自动成为有效值；大幅净值变化只触发复核，不能一律删除真实涨跌。人工审核更正保留理由和证据，来源优先级改变也需要可追溯。

同一输入 hash、产品、日期和指标重试不产生新修订；值或证据实质变化生成 revision。生效净值历史更正后，从受影响日期重算相关用户直至当前日期，并重算覆盖区间的周/月报表。流水补录或冲正同理。

## 第一版收益定义

### 1. 估值和成本

净值型产品：`市值 M_t = 当日已确认份额 Q_t × 当日可用单位净值 NAV_t`。

成本使用移动加权平均法：买入增加份额与含买入手续费成本；部分赎回按赎回前的平均单位成本结转，余下持仓保留剩余成本。现金分红计入已实现收益，不降低此口径下的剩余成本；若未来引入不同成本展示方式，必须单列口径。

定义 B 为累计买入总支出（含买入手续费），R 为累计赎回净收入（已扣赎回手续费），D 为累计现金分红，F 为未计入 B/R 的独立费用，C 为剩余成本：

```text
未实现收益 U_t = M_t - C_t
已实现收益 G_t = R_t - 已赎回成本 + D_t - F_t
累计投资收益 P_t = U_t + G_t = M_t + R_t + D_t - B_t - F_t
区间收益金额 = P_end - P_start
```

上述恒等式要求历史账目完整。红利再投资同时登记“分红收入”和“再投资买入”两个关联事件，前者增加 D，后者增加 B 和份额，现金净流为零；避免仅增份额又重复加分红。完全赎回后市值为零，仍保留历史已实现收益。

示例：买入 100 份、总成本 100；净值 1.10 时赎回 40 份到账 44，无费用和分红。剩余成本 60、市值 66、未实现收益 6、已实现收益 4、累计收益 10。该例应成为计算验收用例。

### 2. 周期与现金流

按自然日生成快照，周一到周日为自然周，月报用自然月。日期区间 `[from, to]` 的收益以 `from` 前一日收盘快照为期初、`to` 日收盘为期末；自定义区间采用相同定义。跨币种不直接求和，第一版人民币以外资产单独展示。

“最近两次净值变化贡献”应与“当日收益”区分。如果周五后直到周一才出现新净值，只能确认整个间隔的变化；不能伪造周末每日真实收益。未公布日可沿用之前净值作暂估，但必须记录 nav_date 和 `carried_forward`。

第一版默认展示累计/区间收益金额、持仓成本收益率、估值日期和完整性。`未实现收益 / 剩余成本` 只是当前持仓成本收益率，不等于含申赎的区间投资回报率。

无现金流且期初价值为正时，区间收益率可用 `V_end / V_start - 1`。存在申赎的投资组合百分比，后续可实现按现金流分段的 TWR 或 XIRR；实现前返回 `unsupported_cashflows`，不得直接用区间收益除以当前成本冒充回报率。

无分红且无份额拆分的产品净值区间年化：`(NAV_end / NAV_start)^(365 / 实际间隔天数) - 1`。起点采用选中的真实净值日期，不用固定 7/14 替代实际天数；注明这只是区间净值年化。发生分红或拆分时需完整复权/现金流处理，否则不显示该年化。

### 3. 数据不足与估值状态

| 情况 | 展示与计算规则 |
| --- | --- |
| 首次没有可用净值 | 市值和收益为 null，标记 missing；不能用 0 冒充 |
| 最新净值未到应公布日 | 最近可用净值估算，显示估值日期与 carried_forward |
| 超出来源允许延迟 | 标记 stale，保留暂估并提示延迟 |
| 部分产品无净值/存在冲突 | 汇总标记 partial，显示已估值产品数和缺失产品；不能标为完整总资产 |
| 现金管理/非净值型产品 | 保存专属指标，标记未支持估值，不套用单位净值公式 |
| 历史份额或期初成本缺失 | 只提供已知区间的跟踪结果，不生成假历史收益 |

每份报表带 `as_of_date`、`generated_at`、`formula_version`、`data_version`、`completeness`。同一计算版本内日收益可以加总为周/月收益；更正后原版本保留，但当前视图统一切到新版本，避免混用新旧快照。

## 旧数据迁移约束

旧 `products` 的 shares/cost 是截面数据，缺少完整交易流水，即便存在 buy_date 也不能推断所有历史交易。迁移时创建指定历史用户及其账户，将产品公共字段拆出，为每条持仓建立指定 `opening_date` 的 opening_balance（份额、剩余成本）。保存旧 ID 映射和迁移批次。

若有期初净值，可以计算期初未实现盈亏，并以此作为迁移后区间观察基线；迁移前已实现收益未知，生命周期总收益应标记不完整。若期初净值也未知，从首个可靠估值日开始观察。不得按种子成本和最早净值日期自动补造买入记录。

旧净值按产品映射迁移，并标记 `legacy_import`，不把没有原始来源证据的值标成已经核验的官方行情。交易历史可后续通过真实账单补录，经核对后重算。
