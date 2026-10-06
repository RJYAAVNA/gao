# 持仓详情页面修复测试报告

## 测试时间
2026-10-03

## 问题描述
访问持仓详情页面 `http://127.0.0.1:8000/positions/{position_id}` 返回 `{"error":"internal_error"}`

## 根本原因
`Position` 模型只包含基础字段，不包含派生字段（市值、盈亏、收益率等）。
原代码尝试访问不存在的字段导致 `AttributeError`。

## 修复方案
修改 `src/ledger/routes/__init__.py:95-212` 的 `position_detail` 函数：
- 从 `PositionSnapshot` 估值快照获取派生数据
- 提供合理的默认值（无估值数据时）
- 确保页面在任何情况下都能正常显示

## 测试结果

### 单元测试
```
测试持仓ID: be1e0e13-a620-4011-936e-b6f31473aa04
响应状态: 200 OK
页面长度: 8252 字节
```

### 批量测试
```
[OK] /positions/05af92e6-8d1a-4145-aae8-dc988c47362f -> 200
[OK] /positions/be1e0e13-a620-4011-936e-b6f31473aa04 -> 200
[OK] /positions/2f1b9f67-e2aa-4109-bf1e-4d93fda0593f -> 200
```

### 字段验证
- Position 模型字段: shares, remaining_cost, realized_pnl, ledger_version ✓
- 派生字段不存在: market_value, cost, pnl, return_rate, unit_nav ✓

## 结论
✅ 修复成功

所有测试用例都通过，持仓详情页面可以正常访问。

## 注意事项

1. **估值依赖**：市值、盈亏等派生数据依赖估值任务
   - 有估值数据：显示实际市值和盈亏
   - 无估值数据：显示成本和零盈亏（合理降级）

2. **数据一致性**：修复后的逻辑与其他页面一致
   - 首页 (`index`) 使用 `get_simple_portfolio_summary`
   - 持仓列表 (`positions`) 使用 `get_top_positions`
   - 持仓详情 (`position_detail`) 现在也从 `PositionSnapshot` 获取数据

3. **默认值策略**
   - `market_value = remaining_cost`（市值 = 成本）
   - `unit_nav = 1.0`（单位净值 = 1）
   - `pnl = 0`（盈亏 = 0）
   - `return_rate = 0.0`（收益率 = 0%）

## 相关文件
- `src/ledger/routes/__init__.py` - 修复的主文件
- `src/ledger/db/models/portfolio.py` - Position 模型定义
- `src/ledger/db/models/valuation.py` - PositionSnapshot 模型定义
- `src/ledger/portfolio/summary_service.py` - 参考的实现模式
