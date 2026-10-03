# S5 功能测试清单

## 测试环境
- **应用地址**: http://127.0.0.1:5000
- **浏览器**: Chrome/Edge (推荐), Firefox, Safari
- **测试日期**: 2026-10-03

---

## 1. 基础功能测试

### 1.1 页面导航
- [ ] 访问首页 `/`
- [ ] 点击"持仓"导航到 `/holdings`
- [ ] 点击"分析"导航到 `/analytics`
- [ ] 点击"设置"导航到 `/settings`
- [ ] 所有页面正常加载，无 404 错误

### 1.2 响应式布局
- [ ] 打开 Chrome DevTools (F12)
- [ ] 切换到移动设备模式 (Ctrl+Shift+M)
- [ ] 测试设备：iPhone SE (375px), iPad (768px), Desktop (1920px)
- [ ] 导航栏在移动端正确显示
- [ ] 卡片布局响应式调整
- [ ] 无横向滚动条

---

## 2. 数字格式化测试

### 2.1 在浏览器控制台测试工具函数

打开浏览器控制台 (F12 > Console)，逐个执行：

```javascript
// 测试货币格式化
console.log(formatCurrency(12345));          // "1.23万"
console.log(formatCurrency(123456789));      // "1.23亿"
console.log(formatCurrency(1234.56));        // "1,234.56"

// 测试百分比格式化
console.log(formatPercent(12.5));            // "+12.50%"
console.log(formatPercent(-5.3));            // "-5.30%"
console.log(formatPercent(0));               // "0.00%"

// 测试数字格式化
console.log(formatNumber(1234567));          // "1,234,567"
console.log(formatNumber(1234.567, 2));      // "1,234.57"

// 测试日期格式化
console.log(formatDate('2024-10-01'));       // "2024-10-01"
```

### 2.2 页面上的数字显示
- [ ] 首页总资产显示格式正确（如 "85.00万"）
- [ ] 持仓页面金额显示格式正确
- [ ] 收益率显示正确（正数绿色，负数红色）
- [ ] 分析页面图表数字格式正确

---

## 3. Toast 通知系统测试

在浏览器控制台执行：

```javascript
// 成功提示（绿色）
showToast('操作成功！', 'success');

// 等待 3 秒后测试错误提示（红色）
setTimeout(() => showToast('操作失败，请重试', 'error'), 3000);

// 等待 6 秒后测试警告提示（黄色）
setTimeout(() => showToast('余额不足', 'warning'), 6000);

// 等待 9 秒后测试信息提示（蓝色）
setTimeout(() => showToast('数据已更新', 'info'), 9000);
```

验证：
- [ ] Toast 出现在右上角（桌面）或顶部（移动）
- [ ] 颜色正确（成功=绿，错误=红，警告=黄，信息=蓝）
- [ ] 3 秒后自动消失
- [ ] 点击关闭按钮可手动关闭
- [ ] 多个 Toast 垂直堆叠显示

---

## 4. PWA 功能测试

### 4.1 Service Worker 注册

1. 打开 Chrome DevTools > Application 标签
2. 左侧选择 "Service Workers"
3. 验证：
   - [ ] Service Worker 状态为 "activated and is running"
   - [ ] 源文件显示 `/sw.js`

### 4.2 缓存测试

1. 在 Application 标签下选择 "Cache Storage"
2. 验证缓存：
   - [ ] 看到 `ledger-v1.0.0` 缓存
   - [ ] 看到 `ledger-runtime-v1.0.0` 缓存
3. 展开 `ledger-v1.0.0`，应包含：
   - [ ] `/` (首页)
   - [ ] `/offline` (离线页面)
   - [ ] `/static/css/main.css`
   - [ ] `/static/js/main.js`
   - [ ] `/static/js/utils.js`
   - [ ] `/static/manifest.json`
   - [ ] `/static/icons/icon-192.png`
   - [ ] `/static/icons/icon-512.png`

### 4.3 离线功能测试

1. 浏览几个页面（首页、持仓、分析）
2. 在 Service Workers 部分勾选 "Offline" 复选框
3. 刷新页面
4. 验证：
   - [ ] 页面仍可访问（显示缓存内容或离线页面）
   - [ ] 离线页面显示友好提示
   - [ ] 点击"重新加载"按钮功能正常
5. 取消 "Offline" 复选框，恢复在线

### 4.4 PWA 安装测试（Chrome/Edge）

1. 访问 http://127.0.0.1:5000
2. 地址栏右侧查找安装图标（➕ 或电脑图标）
3. 点击安装
4. 验证：
   - [ ] 弹出安装对话框
   - [ ] 显示应用名称："多银行理财台账"
   - [ ] 显示应用图标
5. 确认安装
6. 验证：
   - [ ] 应用以独立窗口打开（无浏览器地址栏）
   - [ ] 任务栏/开始菜单有应用图标
   - [ ] 应用标题栏显示应用名称

### 4.5 Manifest 测试

1. 在 Application 标签下选择 "Manifest"
2. 验证：
   - [ ] Identity: `name` = "多银行理财台账"
   - [ ] Presentation: `display` = "standalone"
   - [ ] Icons: 显示 192x192 和 512x512 图标
   - [ ] 主题颜色正确显示

---

## 5. 可访问性测试

### 5.1 键盘导航测试

**只使用键盘，不使用鼠标：**

1. 刷新页面 (F5)
2. 按 `Tab` 键：
   - [ ] 第一个聚焦元素是 "跳转到主内容" 链接（可能需要按一次 Tab 才能看到）
   - [ ] 按 `Enter` 跳转到主内容
3. 继续按 `Tab` 遍历：
   - [ ] 导航菜单各项可聚焦
   - [ ] 所有按钮可聚焦
   - [ ] 所有链接可聚焦
   - [ ] 焦点样式清晰可见（蓝色外框）
4. 按 `Enter` 或 `Space` 激活按钮和链接：
   - [ ] 功能正常执行

### 5.2 图表键盘导航测试

1. 访问分析页面 `/analytics`
2. 按 `Tab` 直到聚焦到"资产趋势"图表
3. 使用键盘控制：
   - [ ] 按 `→`（右箭头）：高亮下一个数据点
   - [ ] 按 `←`（左箭头）：高亮上一个数据点
   - [ ] 显示对应数据点的 tooltip
4. 重复测试饼图和柱状图

### 5.3 屏幕阅读器测试（可选）

**Windows 用户使用 NVDA：**

1. 下载 NVDA：https://www.nvaccess.org/download/
2. 安装并启动 NVDA (`Ctrl+Alt+N`)
3. 访问应用
4. 验证：
   - [ ] 页面标题正确朗读："首页 - 多银行理财台账"
   - [ ] 导航区域可识别
   - [ ] 图表有描述性标签（如"资产趋势折线图"）
   - [ ] 按钮和链接文本清晰

### 5.4 Lighthouse 可访问性审计

1. 打开 Chrome DevTools > Lighthouse 标签
2. 勾选 "Accessibility"
3. 选择 "Desktop" 或 "Mobile"
4. 点击 "Analyze page load"
5. 等待报告生成
6. 验证：
   - [ ] Accessibility 分数 ≥ 85
   - [ ] 无严重 (Critical) 问题
   - [ ] 无中等 (Serious) 问题

### 5.5 颜色对比度测试

使用工具：https://webaim.org/resources/contrastchecker/

测试主要文本：
- 前景色：`#F8FAFC` (白色文本)
- 背景色：`#0F172A` (深蓝色背景)
- [ ] 对比度应 ≥ 4.5:1 (WCAG AA 标准)

测试次要文本：
- 前景色：`#94A3B8` (灰色文本)
- 背景色：`#0F172A`
- [ ] 对比度应 ≥ 4.5:1

---

## 6. 图表交互测试

### 6.1 资产趋势折线图

1. 访问分析页面
2. 测试交互：
   - [ ] 鼠标悬停显示 tooltip
   - [ ] Tooltip 显示日期和金额
   - [ ] 图表响应窗口大小变化（调整浏览器窗口）
3. 键盘导航：
   - [ ] Tab 聚焦图表
   - [ ] 箭头键切换数据点

### 6.2 持仓分布饼图

1. 测试交互：
   - [ ] 鼠标悬停高亮扇区
   - [ ] Tooltip 显示银行名称、金额、占比
   - [ ] 点击图例切换显示/隐藏

### 6.3 收益对比柱状图

1. 测试交互：
   - [ ] 鼠标悬停显示数据
   - [ ] 正收益显示绿色，负收益显示红色
   - [ ] 图例可点击切换

---

## 7. 响应式测试

### 7.1 桌面端 (≥1024px)

- [ ] 访问首页，验证三栏布局
- [ ] 导航栏水平排列
- [ ] 卡片以网格形式排列（2-3 列）
- [ ] 图表宽度合适

### 7.2 平板端 (768px - 1023px)

1. Chrome DevTools > 切换到 iPad (820x1180)
2. 验证：
   - [ ] 导航栏仍水平排列或折叠
   - [ ] 卡片 2 列布局
   - [ ] 图表响应式调整

### 7.3 移动端 (< 768px)

1. 切换到 iPhone SE (375x667)
2. 验证：
   - [ ] 导航栏底部固定
   - [ ] 卡片单列布局
   - [ ] 数字显示简化（如 "1.23万" 而非 "12,345.67"）
   - [ ] 按钮触摸目标足够大（≥ 44x44px）
   - [ ] 无横向滚动

### 7.4 文本缩放测试

1. 浏览器缩放至 200% (`Ctrl` + `+`)
2. 验证：
   - [ ] 页面布局不崩溃
   - [ ] 文本不被截断
   - [ ] 内容仍可阅读
   - [ ] 无横向滚动（或可接受的少量滚动）

---

## 8. 性能测试

### 8.1 首次加载性能

1. 清空缓存：DevTools > Application > Clear storage > Clear site data
2. 打开 DevTools > Network 标签
3. 刷新页面
4. 验证：
   - [ ] DOMContentLoaded < 1s
   - [ ] Load 事件 < 2s
   - [ ] 总传输大小 < 500KB

### 8.2 缓存后加载性能

1. 刷新页面（Service Worker 已激活）
2. 查看 Network 标签
3. 验证：
   - [ ] 大部分资源从 Service Worker 加载（显示为 "(ServiceWorker)"）
   - [ ] 加载时间显著减少 (< 500ms)

### 8.3 Lighthouse 性能审计

1. DevTools > Lighthouse
2. 勾选 "Performance"
3. 运行审计
4. 验证：
   - [ ] Performance 分数 ≥ 70（开发环境）
   - [ ] First Contentful Paint < 2s
   - [ ] Largest Contentful Paint < 3s

---

## 9. 浏览器兼容性测试

### 9.1 Chrome/Edge (推荐)
- [ ] 所有功能正常
- [ ] PWA 可安装
- [ ] Service Worker 正常工作

### 9.2 Firefox
- [ ] 基本功能正常
- [ ] 图表显示正常
- [ ] Service Worker 工作（Firefox 44+）

### 9.3 Safari (macOS/iOS)
- [ ] 基本功能正常
- [ ] 图表显示正常
- [ ] PWA 支持有限（iOS 11.3+）

---

## 10. 错误处理测试

### 10.1 网络错误

1. 在 DevTools 中模拟离线
2. 尝试访问未缓存的页面
3. 验证：
   - [ ] 显示友好的离线页面
   - [ ] 提示检查网络连接
   - [ ] 提供"重新加载"按钮

### 10.2 404 错误

1. 访问不存在的页面：http://127.0.0.1:5000/nonexistent
2. 验证：
   - [ ] 显示 404 错误页面或返回 JSON 错误
   - [ ] 提示页面不存在

---

## 测试结果汇总

### 通过的测试
- [ ] 基础功能 (__ / __)
- [ ] 数字格式化 (__ / __)
- [ ] Toast 通知 (__ / __)
- [ ] PWA 功能 (__ / __)
- [ ] 可访问性 (__ / __)
- [ ] 图表交互 (__ / __)
- [ ] 响应式 (__ / __)
- [ ] 性能 (__ / __)
- [ ] 浏览器兼容性 (__ / __)
- [ ] 错误处理 (__ / __)

### 发现的问题
记录在这里：

1. 
2. 
3. 

### 优先级
- P0 (阻断): 
- P1 (重要): 
- P2 (次要): 

---

## 快速测试命令

在浏览器控制台快速运行所有工具函数测试：

```javascript
// 一键测试所有格式化函数
console.group('数字格式化测试');
console.log('formatCurrency(12345):', formatCurrency(12345));
console.log('formatCurrency(123456789):', formatCurrency(123456789));
console.log('formatPercent(12.5):', formatPercent(12.5));
console.log('formatPercent(-5.3):', formatPercent(-5.3));
console.log('formatNumber(1234567):', formatNumber(1234567));
console.groupEnd();

// 一键测试所有 Toast 类型
console.group('Toast 通知测试');
setTimeout(() => showToast('成功提示', 'success'), 0);
setTimeout(() => showToast('错误提示', 'error'), 3500);
setTimeout(() => showToast('警告提示', 'warning'), 7000);
setTimeout(() => showToast('信息提示', 'info'), 10500);
console.log('将在 14 秒内显示 4 个 Toast');
console.groupEnd();
```

---

**测试完成日期**: _____________  
**测试人员**: _____________  
**整体评估**: ⭐⭐⭐⭐⭐ (1-5 星)
