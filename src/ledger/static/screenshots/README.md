# PWA 截图

此目录用于存放 PWA 应用商店截图。

## 所需截图

根据 `manifest.json` 配置，需要以下截图：

1. **home.png** - 首页资产概览
   - 尺寸：750x1334 (iPhone 8/SE)
   - 内容：显示总资产、累计收益、持仓产品等汇总信息

2. **positions.png** - 持仓列表
   - 尺寸：750x1334
   - 内容：显示所有持仓产品的列表视图

3. **analytics.png** - 收益分析
   - 尺寸：750x1334
   - 内容：显示净值走势图表和收益分析图表

## 如何生成截图

### 方法 1: 使用浏览器开发者工具

1. 在浏览器中打开应用（推荐使用 Chrome）
2. 按 F12 打开开发者工具
3. 点击设备工具栏图标（Ctrl+Shift+M）
4. 选择设备：iPhone SE 或 iPhone 8 (375x667)
5. 设置像素比率为 2（得到 750x1334）
6. 截取页面截图

### 方法 2: 使用 Playwright/Puppeteer 自动化

```python
# 可以编写脚本自动生成截图
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 375, 'height': 667}, device_scale_factor=2)
    page.goto('http://localhost:5000/')
    page.screenshot(path='static/screenshots/home.png')
    browser.close()
```

### 方法 3: 实际设备截图

在 iPhone 8/SE 上安装 PWA 后直接截图，然后裁剪到合适尺寸。

## 注意事项

- 截图应展示真实的应用界面
- 避免包含敏感的个人财务信息
- 可以使用模拟数据
- 确保界面清晰、内容完整
- 截图将显示在 PWA 安装提示和应用商店中

## 当前状态

⚠️ 截图文件尚未生成，需要运行应用后手动截取或使用自动化工具生成。
