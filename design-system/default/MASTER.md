# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** 多银行理财台账
**Generated:** 2026-10-03 11:28:34
**Category:** Fintech/Crypto
**Design Dials:** Variance 3/10 (Centered / Minimal) | Motion 4/10 (Standard) | Density 7/10 (Standard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#D6BE8C` | `--color-primary` |
| On Primary | `#151B24` | `--color-on-primary` |
| Secondary | `#BAC8D8` | `--color-secondary` |
| On Secondary | `#151B24` | `--color-on-secondary` |
| Accent/CTA | `#A9B7CC` | `--color-accent` |
| On Accent/CTA | `#000000` | `--color-on-accent` |
| Background | `#151B24` | `--color-background` |
| Foreground | `#E8ECF2` | `--color-foreground` |
| Card | `#1D2531` | `--color-card` |
| Card Foreground | `#E8ECF2` | `--color-card-foreground` |
| Muted | `#283341` | `--color-muted` |
| Muted Foreground | `#A7B3C4` | `--color-muted-foreground` |
| Border | `#465568` | `--color-border` |
| Destructive | `#F0A4A4` | `--color-destructive` |
| On Destructive | `#000000` | `--color-on-destructive` |
| Ring | `#D6BE8C` | `--color-ring` |

**Color Notes:** 2026-10-04 用户要求统一治理：深灰蓝背景、柔和白文字、低饱和香槟金操作强调。产品标题使用正文色；图表读取同一语义 token。

### Typography

- **Heading Font:** IBM Plex Sans
- **Body Font:** IBM Plex Sans
- **Mood:** financial, trustworthy, professional, corporate, banking, serious
- **Google Fonts:** [IBM Plex Sans + IBM Plex Sans](https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

*Density: 7/10 — Standard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: var(--color-primary);
  color: #000000;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  /* No position shift on hover. */
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #D6BE8C;
  border: 2px solid #D6BE8C;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #151B24;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #D6BE8C;
  outline: none;
  box-shadow: 0 0 0 3px #D6BE8C20;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Minimalism & Swiss Style

**Keywords:** Clean, simple, spacious, functional, white space, high contrast, geometric, sans-serif, grid-based, essential

**Best For:** Enterprise apps, dashboards, documentation sites, SaaS platforms, professional tools

**Key Effects:** Subtle hover (200-250ms), smooth transitions, sharp shadows if any, clear type hierarchy, fast loading

### Page Pattern

**Pattern Name:** Trust & Authority + Conversion

- **Conversion Strategy:** Security badges. Case studies. Transparent pricing. Low-friction form. Provide pause/stop and stop the logo carousel on focus, hover, and reduced motion. Previous/next controls provide the keyboard equivalent; pause offscreen/hidden and render a static logo set under reduced motion.
- **CTA Placement:** Contact Sales / Get Quote (primary) + Nav
- **Section Order:** Hero (mission/credibility) > Proof (logos, certs, stats) > Solution overview > Clear CTA path

---

## Motion

**Stagger List** (Standard) — Trigger: load or scroll | Duration: 300-450ms | Easing: `back.out(1.4)`

```js
gsap.from('.grid-item', { opacity: 0, scale: 0.92, y: 16, duration: 0.4, stagger: { each: 0.06, from: 'start', grid: 'auto' }, ease: 'back.out(1.4)' });
```

**Framework notes:** grid: 'auto' lets GSAP infer rows/columns from a CSS grid layout for a natural wave stagger; Use matchMedia('(prefers-reduced-motion: reduce)') to skip non-essential motion and render the final state immediately

- ✅ Combine with from: 'center' for a bento-grid layout to draw the eye inward first
- ❌ Don't use back.out on dense data tables; the overshoot reads as sloppy on informational UI
- ⚡ Group DOM writes; avoid interleaving layout reads (getBoundingClientRect) between staggered tweens

---

## Anti-Patterns (Do NOT Use)

- ❌ Playful design
- ❌ Unclear fees
- ❌ AI purple/pink gradients

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile

## 2026-10-04 UI 治理规则（优先于旧示例）

- 卡片标题链接与正文同色，hover 下划线及暖金反馈；不可出现浏览器默认蓝/紫链接。
- 按钮主次通过背景和边框区分；输入控件边框 #718096，焦点可见，最小高度 44px。
- 非交互卡片不漂浮、不位移；正文/次要文字对比度至少 4.5:1。
- 数值使用等宽数字，指标标题 14px，卡片标题约 20px；手机端指标两列、市值独占首行。
- 共用 main.css 管理收益网格、过滤栏、链接与按钮；登录和图表使用相同颜色变量。
- 金融仪表盘 color 搜索结果用于深色层级参考；首次 design-system 检索误匹配 wellness，未采用其营销布局和字体。

### 验收记录（2026-10-05）

- Edge 隔离测试：7 页面 × 375/768/1024/1440 四档宽度，共 28 检查通过，无横向溢出、无脚本错误。
- 启用减少动态效果，等待 document.fonts.ready 后确认手机端指标及导航图标显示正常。
- 正文/卡片对比度 13.01:1，次要文字 7.26:1，主按钮文字 9.56:1，输入边框/背景 4.31:1。
- 产品标题计算颜色 rgb(232,236,242)，与正文一致；手机端使用两列指标。
- 样式已于上一轮构建进本地 Docker 镜像；本轮 Docker 因 engine.sock 访问失败未能启动，最终复查使用隔离内存库演示数据，未修改真实账本。
