# 暗色主题写死颜色修复方案（P0.5-4 补完）

> 日期：2026-08-18。作者：yx（评估）。
> 背景：P0.5-4 亮/暗主题已上线（`state/theme.tsx` localStorage + `data-theme` 属性 + antd `darkAlgorithm` 双轨），但手写 CSS 与内联样式中约 250 处颜色写死为亮色，暗色下出现"文字与背景融合"与"亮色孤岛"。
> 本文档为修复方案。**已于 2026-08-19 实施完成**（见文末"五、实施与验证记录"）。

---

## 一、根因

主题机制本身正确：antd 组件由 `darkAlgorithm` 自动适配，`html[data-theme="dark"]` 驱动手写 CSS。
问题在于手写样式几乎没有接入这套机制：

- `frontend/src/index.css`（686 行）约 **200 处**写死的亮色 hex/rgba；
- `[data-theme="dark"]` 目前只覆盖 3 个变量：`--gm-bg` / `--gm-text` / `--gm-layout-bg`（`index.css:12-16`）；
- TSX 内联样式约 **55 处**写死颜色，集中在 `KnowledgeGraph.tsx`（37 处，Cytoscape 画布整套）、`EvidenceViewer.tsx`、`ResearchPlansPage.tsx`、`DiscoverPage.tsx`、`ErrorBoundary.tsx` 等。

融合的两条具体路径：

1. **亮背景 × 继承白字**（白字白底）：全局文字色 `--gm-text` 在暗色下是 `rgba(255,255,255,.85)`；任何写死亮背景、又没有自带文字色的容器，都会让继承来的白字落在浅色底上。
2. **暗背景 × 写死深字**（黑字黑底）：容器本身由 antd 暗色算法变暗（Card/Modal/Sider/Table），上面手写的深色文字不变，直接融进背景。

---

## 二、待修复清单

### A 类：文字与背景直接融合（不可读，优先修）

| # | 位置 | 现象 |
|---|------|------|
| A1 | `index.css:402` `.gm-chat-message.is-assistant .gm-chat-message-body` 背景 `#f7f8fa` | **AI 回答气泡**：暗色下继承全局白字落在浅灰底，最高频融合点 |
| A2 | `index.css:409` `.gm-chat-markdown :not(pre) > code` 背景 `#e8edf3` | 行内代码白字浅灰底 |
| A3 | `index.css:437` `.gm-chat-citations .ant-list-item-meta-description` 色 `#596579` | 引用摘要文字深灰落暗底 |
| A4 | `index.css:385` `.gm-chat-history-item:hover/.is-selected` 背景 `#eaf3ff` | 会话历史 hover：白字浅蓝底 |
| A5 | `index.css:418` `.gm-research-report-modal .ant-modal-title` 色 `#172033` | 研究报告弹窗标题：antd 暗色弹窗 + 写死深色标题 |
| A6 | `index.css:538-539` 棋盘统计卡标题 `#607086`、数值 `--gap-ink:#172033`；`index.css:577` 轴标签 `#1f2c3d` | 棋盘卡是 antd Card（暗色），上面写死深色字 |
| A7 | `index.css:65` `.gm-brand strong` 色 `#12263f` | 品牌名：antd Sider 暗底 + 深藏青字 |
| A8 | `EvidenceViewer.tsx:74-75, 141-142` `pre` 背景 `#fafafa`、mark 背景 `#fff566`/`#ffccc7` | 证据原文面板白字浅底；高亮黄/红底配继承白字 |
| A9 | `KnowledgeWorkbench.tsx:370`、`KnowledgeGraph.tsx:336` `pre` 背景 `#f7f8fa` | 同 A8 |
| A10 | `ErrorBoundary.tsx:51` 背景 `#f5f5f5` | 报错页 antd Result 暗色文字落浅灰底 |
| A11 | `DiscoverPage.tsx:392` 选中 run 背景 `#f0f5ff` | 发现页选中项白字浅蓝底 |
| A12 | `index.css:440` `.gm-chat-source-text mark` 背景 `#fff566` | 对话证据原文高亮：白字黄底 |
| A13 | `ReadingPaperPage.tsx:131` 标注色 `#f59e0b`/`#facc15`/`#60a5fa` | PDF 阅读标注需暗色变体（次要） |

### B 类：亮色孤岛（可读但刺眼、视觉断裂，第二批修）

**index.css：**

- 聊天整体布局 `#fff`（:379）、侧栏 `#fbfcfe`（:380）、输入区 `#fff`（:449）
- 知识卡 `#fff`（:312）、研究报告布局 `#fff`（:420）、agent 引用条 `#f7faff`（:460）
- 阅读页 PDF 框 `#f0f2f5`（:182）、无 PDF 占位 `#f8fafc`（:192）
- AI 助手 hero 渐变（:463）、棋盘 hero 渐变（:506-508）
- 棋盘表格被 `!important` 强制亮色（:567-573）、棋盘格渐变（:584-591）、图例 `#fff`（:558）

**TSX：**

- `KnowledgeGraph.tsx`：画布底 `#f5f7fb`（:806）、检查器面板 `#f8fafc` + 边框（:927-928）、径向渐变白底（:951）、节点标签白底 `text-background-color:#ffffff`（:557-573）
- `ResearchPlansPage.tsx:402` 弹窗 footer 背景 `#fff` + 边框 `#e8edf3`

**说明**：棋盘格子（:584-591）、用户气泡（:401，自带 `#164477` 深字）、katex 公式块（:416）属于"亮底 + 自带深色字"的自洽组合，暗色下可读，归入 B 类孤岛而非 A 类融合——修的时候决定是"变暗"还是"保持纸面感"。

**不在问题范围**：antd 组件（Table/Card/Modal/Steps/Tag/Button 等）由 darkAlgorithm 正确适配；`main.tsx` 的 `colorPrimary: #1677ff` 两种主题下均可用。

---

## 三、推荐方案：扩展现有 CSS 变量体系

机制已在（`data-theme` 切变量），只是变量太少。**不推荐**逐条写 `[data-theme="dark"] .xxx` 覆写（两份清单、双写必漏），也不引入 CSS-in-JS 主题化（接近封版，重构面过大）。

### 3.1 变量集（在 `:root` 定义，`[data-theme="dark"]` 给对应值）

| 变量 | 亮色（现状沿用） | 暗色（建议） | 用途 |
|------|------|------|------|
| `--gm-bg` | `#f5f7fa` | `#141414` | 页面底（已有） |
| `--gm-text` | `#213547` | `rgba(255,255,255,.85)` | 全局文字（已有） |
| `--gm-layout-bg` | `#f5f7fa` | `#141414` | 布局底（已有） |
| `--gm-surface` | `#fff` | `#1f1f1f` | 卡片/面板主底（聊天布局、知识卡、报告布局、输入区） |
| `--gm-surface-2` | `#fbfcfe` | `#141414` 或 `#161616` | 次级底（聊天侧栏、棋盘表格外框） |
| `--gm-surface-3` | `#f7f8fa` | `#2a2a2a` | 气泡/hover/代码块内嵌底 |
| `--gm-hover` | `#eaf3ff` | `rgba(22,119,255,.15)` | hover/选中 |
| `--gm-border` | `#e8edf3` | `#333` | 主分隔线/边框 |
| `--gm-border-2` | `#edf0f4` | `#2a2a2a` | 次级边框 |
| `--gm-text-secondary` | `#59677a` | `rgba(255,255,255,.55)` | 次要文字（品牌副标、引用摘要等） |
| `--gm-ink` | `#172033` | `rgba(255,255,255,.9)` | 强调文字（报告标题、棋盘数值、轴标签） |
| `--gm-code-bg` | `#e8edf3` | `#33373d` | 行内代码底 |
| `--gm-mark` | `#fff566` | `rgba(250,204,21,.35)` | 黄色高亮（叠加原文字色，避免白字黄底） |
| `--gm-mark-danger` | `#ffccc7` | `rgba(255,120,120,.35)` | 红色高亮 |
| 阴影 | `rgba(31,55,87,.05-.1)` 系 | `rgba(0,0,0,.35)` 系 | 各 box-shadow |

具体暗色值实施时以 antd v5 暗色 token 为参照（`colorBgContainer #141414`、`colorBgElevated #1f1f1f` 一族），保持与 antd 组件的层次一致。

### 3.2 实施步骤

1. **index.css 变量化**：把上表用途对应的写死值全量替换为 `var(...)`；棋盘 hero 渐变、棋盘格渐变这类复杂背景，直接给 `[data-theme="dark"] .gm-gap-*` 少量覆写规则（渐变整体换暗色基底、保留强调色）。
2. **A 类点位换变量**：上表 A1-A7、A12 直接受益；`--gm-mark` 系列落在黄/红底上的文字保持继承色，实现"高亮底随主题、文字色不换"。
3. **TSX 内联样式下沉**：`EvidenceViewer` / `KnowledgeWorkbench` / `ErrorBoundary` / `DiscoverPage` / `ResearchPlansPage` / `ReadingPaperPage` 中涉及颜色的内联 style 改为新增 CSS 类（放在 index.css，用同一套变量）；`#1677ff` 图标色这类两主题通用的可保留内联。
4. **KnowledgeGraph（Cytoscape）单独处理**：画布底、检查器面板、径向渐变、节点/边标签的 `text-background-color` 全部改为读主题（组件内用 `useTheme()` 的 `isDark` 选两套样式对象，或全局 CSS 变量 + `getComputedStyle` 读取——推荐前者，Cytoscape 样式是 JS 对象，直接 `isDark ? darkStyles : lightStyles`）。节点/关系配色本身饱和度适中，两主题通用，**不动**。
5. **棋盘自洽组合的取舍**：棋盘格、用户气泡、katex 公式块——建议棋盘格随主题变暗（保持强调色条），用户气泡与公式块可保持"纸面感"但需显式写死配套深字（现状已自洽，可后置）。
6. **PDF 标注色（A13）**：`ReadingPaperPage.tsx:131` 三色给暗色变体（降饱和/加透明度）。

### 3.3 验证清单（亮暗各走一遍）

- [ ] AI 助手：新对话空态、发送中、回答气泡（markdown/行内代码/表格/公式）、引用展开、证据原文高亮、历史列表 hover/选中
- [ ] 研究空白棋盘：hero、统计卡、矩阵表头/表体/固定列、图例、格子弹层
- [ ] 知识工作台：知识卡、证据 `pre` 面板、知识图谱（画布/节点标签/边标签/检查器/图例/全屏）
- [ ] 发现页：run 列表选中态、阶段条部分成功警告色
- [ ] 研究计划页：弹窗 header/footer/标题
- [ ] 阅读页：无 PDF 占位、PDF 标注三色
- [ ] 报错兜底页（ErrorBoundary）
- [ ] `npm test -- --run` + `tsc --noEmit`（38+ 前端测试不涉及颜色，应全绿）

### 3.4 工作量估计

- index.css 变量化 + 暗色值一套：约半天
- TSX 少量点位下沉 + Cytoscape 双套样式：约半天
- 五页面 × 两主题走查：再加少量时间
- 若只先修 A 类（1-13 项）：约 1-2 小时，B 类孤岛后置

---

## 四、明确不做

- ❌ 不逐条写 `[data-theme="dark"] .xxx` 覆写清单（双写必漏、难维护）
- ❌ 不引入 CSS-in-JS / 换主题库（封版期不做大重构）
- ❌ 不动 antd 组件默认行为与 `main.tsx` 主题配置（双轨机制是对的）
- ❌ 不改节点/关系语义配色（`TYPE_COLORS`/`RELATION_COLORS` 两主题通用）

---

## 五、实施与验证记录（2026-08-19）

### 改动文件（7 个，均在前端）

| 文件 | 改动 |
|---|---|
| `src/index.css` | 扩展 `:root`/`[data-theme="dark"]` 变量集（surface×3/border×2/ink/mark/code-bg/primary-soft/chip/表格×5 等）；约 45 处写死颜色替换为变量；hero 渐变、gap 格子底色等补暗色覆写 |
| `src/components/KnowledgeGraph.tsx` | Cytoscape 双套样式（`useTheme().isDark` 三元）：节点边框/边线/聚焦边框/展开底衬/画布渐变/标签底色；JS 侧容器、工具栏、悬浮条、开发信息 pre 换变量 |
| `src/components/EvidenceViewer.tsx` | pre 背景×2、mark 高亮×2 → 变量 |
| `src/components/ErrorBoundary.tsx` | pre 背景 → `--gm-surface-3` |
| `src/components/KnowledgeWorkbench.tsx` | 结构化内容 pre → `--gm-surface-3` |
| `src/pages/DiscoverPage.tsx` | 运行历史选中行 → `--gm-hover` |
| `src/pages/ResearchPlansPage.tsx` | 报告弹窗 header/footer 边框与底色 → 变量 |

### 验证

- `tsc --noEmit` 0 错误；`npm test -- --run` 43/43 通过。
- 无头 Chrome（puppeteer-core，localStorage 预设 `gm-theme`）对 6 个页面 × 2 主题共 13 张截图（对话/会话列表/棋盘/图谱/发现/计划/计划详情弹窗），逐张视觉检查无文字-背景融合。
- DOM 计算样式抽查（决定性证据）：暗色下 `.gm-sider`=#141414、assistant 气泡=#2a2a2a+白字、棋盘表头=#262626/单元格=#1a1a1a+`rgba(255,255,255,.9)` 文字、引用条=白 4% 底；亮色下各值与改动前原值一致（无回归）。
- 视觉模型两次误报（"亮色侧边栏深蓝""AI 回复深灰底"）均被 DOM 实测推翻：亮色侧边栏实为 `rgb(255,255,255)`、AI 气泡 `#f7f8fa`。
- KnowledgeGraph 主题切换即时生效（stylesheet useMemo 依赖 `isDark`），无需刷新页面。

### 补充修复（2026-08-19，用户反馈）

- **用户消息气泡暗色下白字浅蓝底融合**：根因是 `index.css` 只在气泡容器上设字色，但文字实际是 antd `Typography.Paragraph`，antd 暗色算法在 `.ant-typography` 上直接给出白色 token，压过了继承色。修复：新增 `--gm-user-bubble-bg`/`--gm-user-bubble-ink` 变量（亮色 `#eaf3ff`/`#164477` 不变；暗色反转为 `#164477`/`#eaf3ff`），并用 `.gm-chat-message.is-user .gm-chat-plain-text` 显式钉住段落字色。实测暗色段落字 `rgb(234,243,255)` on 底 `rgb(22,68,119)`（对比度 ≈8.9:1），亮色与原版一致；43/43 测试通过。
- 经验：凡是"自定义底色容器内放 antd Typography"的地方，字色必须在 Typography 元素本身设置，不能依赖父级继承（antd 直接规则永远赢）。
