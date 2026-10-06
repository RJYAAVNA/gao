# 持仓详情页面错误修复

## 问题描述

访问持仓详情页面 `http://127.0.0.1:8000/positions/{position_id}` 时返回 `{"error":"internal_error"}`

## 根本原因

在 `src/ledger/routes/__init__.py` 的 `position_detail` 函数（第 95-157 行）中，代码尝试访问 `Position` 模型对象上不存在的字段：

```python
# 错误代码：直接访问 Position 对象的派生字段
position_data = {
    "market_value": float(position.market_value),  # ❌ 不存在
    "cost": float(position.cost),                   # ❌ 不存在
    "pnl": float(position.pnl),                     # ❌ 不存在
    "return_rate": float(position.return_rate),     # ❌ 不存在
    "unit_nav": float(position.unit_nav),           # ❌ 不存在
}
```

### Position 模型实际字段

根据 `src/ledger/db/models/portfolio.py`，`Position` 模型只包含基础字段：

- `shares` - 持有份额
- `remaining_cost` - 剩余成本
- `realized_pnl` - 已实现盈亏
- `ledger_version` - 账本版本号
- `last_transaction_date` - 最后交易日期

### 派生数据的正确来源

市值、盈亏、收益率等派生数据应该从 `PositionSnapshot`（估值快照）中获取，这与其他页面的实现一致（例如 `get_top_positions` 函数）。

## 修复方案

修改 `position_detail` 函数，使其：

1. 从 `Position` 模型获取基础持仓信息
2. 从 `PositionSnapshot` 获取最新的估值数据（市值、盈亏等）
3. 如果没有估值数据，使用合理的默认值，确保页面不会报错

### 修复后的逻辑

```python
# 1. 获取 Position 基础信息
position = db.query(Position).filter(...).first()

# 2. 查询最新估值任务
run = db.query(ValuationRun).filter(
    ValuationRun.user_id == user_id,
    ValuationRun.is_current == True
).first()

# 3. 设置默认值（无估值数据时使用）
market_value = position.remaining_cost  # 默认市值 = 成本
unit_nav = 1.0                          # 默认净值 = 1
pnl = 0.0                               # 默认盈亏 = 0
return_rate = 0.0                       # 默认收益率 = 0

# 4. 如果有估值数据，从快照中获取
if run:
    snapshot = db.query(PositionSnapshot).filter(...).first()
    if snapshot:
        market_value = snapshot.market_value or position.remaining_cost
        pnl = snapshot.unrealized_pnl or 0
        # 计算收益率和单位净值
        ...
```

## 修改文件

- `src/ledger/routes/__init__.py` - 第 95-212 行的 `position_detail` 函数

## 测试验证

1. **语法检查**：`python -m py_compile src/ledger/routes/__init__.py` ✓
2. **模块加载**：路由模块可以正常加载 ✓
3. **字段验证**：确认 Position 模型不包含派生字段 ✓

## 相关代码模式

该修复遵循了项目中已有的模式：

- `get_top_positions()` (portfolio/summary_service.py:130-226) - 同样从 PositionSnapshot 获取派生数据
- `get_portfolio_summary()` (portfolio/summary_service.py:54-127) - 从快照获取汇总数据

## 数据库设计说明

根据项目文档，这是有意的设计：

- `Position` 表是交易流水的投影，只存储基础持仓数据
- `PositionSnapshot` 表存储每日估值结果，包含市值、盈亏等派生数据
- 估值数据需要单独的估值任务 (`ValuationRun`) 生成
- 如果用户没有运行过估值，就没有市值等数据

## 后续建议

1. 考虑在用户首次登录或添加交易后，自动触发一次估值计算
2. 在持仓详情页面增加提示，告知用户需要运行估值才能看到准确的市值和收益
3. 添加单元测试，覆盖「有估值数据」和「无估值数据」两种场景
