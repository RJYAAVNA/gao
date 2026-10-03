# S4: Valuation replay and API endpoints

## 概述
实现 S4 阶段的估值回放和 API 端点功能。

## 主要变更

### 估值回放功能
- **replay.py**: 实现交易回放和每日快照回放逻辑
  - `replay_transactions()`: 从交易历史回放生成持仓和估值快照
  - `replay_daily_snapshots()`: 基于已有的每日持仓快照重新计算估值
  - 支持指定日期范围和单个日期回放
  - 包含完整的状态和估值数据类

### 估值计算器增强
- **calculator.py**: 扩展估值计算功能
  - `calculate_position_valuation()`: 计算单个持仓估值
  - `calculate_portfolio_valuation()`: 计算组合整体估值
  - 支持收益率、成本收益率等指标计算
  - 包含数据质量标记（full/partial/stale/none）

### API 端点
- **valuation.py**: 新增估值相关 API
  - `POST /api/valuation/replay-transactions`: 交易回放
  - `POST /api/valuation/replay-daily`: 每日快照回放
  - `GET /api/valuation/portfolio`: 查询组合估值快照
  - `GET /api/valuation/positions`: 查询持仓估值快照
  - 所有端点都需要用户认证

### 认证装饰器
- **decorators.py**: 实现 `@login_required` 装饰器
  - 检查 `g.current_user` 确保用户已登录
  - 统一的 401 错误响应

### 测试
- **test_valuation_calculator.py**: 估值计算器测试（10 个测试）
- **test_valuation_replay.py**: 回放功能测试（8 个测试）
- 覆盖所有核心功能和边界情况

## 代码质量
- ✅ 所有测试通过（149 个测试）
- ✅ Ruff 格式化和代码检查通过
- ✅ Mypy 类型检查通过
- ✅ 符合项目代码规范

## 依赖项
无新增外部依赖，使用现有的 Flask、SQLAlchemy 等。

🤖 Generated with [Claude Code](https://claude.com/claude-code)
