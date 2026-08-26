---
schema: money-craft.report-design.v2
surface: research-publication
mode: read
default_theme: editorial-ivory
tokens:
  color:
    canvas: "#E8E4DC"
    paper: "#F8F6F0"
    ink: "#171715"
    ink_secondary: "#4E4B45"
    ink_muted: "#77736B"
    line: "#D5D0C6"
    line_strong: "#AAA398"
    accent: "#C4472D"
    accent_dark: "#8F2E20"
    cool: "#315868"
    warning: "#A56B21"
  type:
    display: "Songti SC, STSong, Noto Serif CJK SC, Source Han Serif SC, serif"
    body: "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    numeric: "SFMono-Regular, Menlo, Consolas, ui-monospace, monospace"
  measure:
    prose: "full-column"
    report: "1120px"
---

# Money Craft Research Publication System

## 设计解读

Money Craft 的最终报告是一份给长期投资者阅读和复核的中文研究刊物。它应当显得 **成熟、具体、编辑化、具有判断力**，而不是 dashboard、审计后台、券商模板或 AI 自动生成页面。

内部参数：`DESIGN_VARIANCE=5`，`MOTION_INTENSITY=1`，`VISUAL_DENSITY=6`。

## 核心原则

1. **刊物而非应用外壳。** 页面围绕标题、判断、图表、正文和脚注组织，不使用左侧后台导航、四等分 KPI 仪表盘或通用卡片网格。
2. **先判断，再解释，再复核。** 首屏必须在一个自然阅读视野中交代公司、证券、研究期、判断、核心命题、关键数字和两张核心图表。
3. **编辑留白，不留空页。** 留白用于建立段落与章节关系，不得让 A4 页面下半部空置，也不得用巨型标题制造虚假高级感。
4. **中西文角色明确。** 中文刊物标题可使用宋体/现代衬线建立编辑气质；正文、表格和界面辅助信息使用高可读无衬线；数字、日期和哈希使用等宽字体。
5. **颜色表达立场。** 象牙纸、近黑正文和朱砂强调构成主视觉；冷蓝灰用于第二数据系列。颜色不替代标签、位置或文字说明。
6. **图表属于文章。** 图表使用细线、直接标注、明确单位和解释文字，与正文共享网格；不放进圆角 dashboard 卡片。

## 阅读结构

1. **Publication masthead**：Money Craft 字标、报告类型、证券、研究日、数据截止和 revision。
2. **Investment call**：公司名、报告类型、研究判断、核心命题和四个关键数字，采用非对称编辑网格。
3. **Evidence spread**：财务趋势和估值情景组成一个双栏证据跨页，宽屏并排、窄屏顺序堆叠。
4. **Research narrative**：每节回答一个研究问题；章节编号、标题和正文沿统一基线组织。
5. **Risk and falsification**：风险、反方证据和反转条件使用更强的文字层级，而不是红色卡片。
6. **Sources and seal**：来源使用脚注索引式排版，最后以审计、证据、离线验证和源哈希收口。

## 字体与排版

- HTML 公司名：42-54px，宋体/现代中文衬线，字重 600 左右，不使用超粗黑体。
- HTML 核心命题：19-22px / 1.65；正文：16-17px / 1.78，主栏全宽。
- 中文正文使用 `line-break: strict; word-break: keep-all`；长 URL、哈希和等宽定位符才允许 `break-all`。
- HTML H2：27-32px；H3：18-21px；章节编号作为边栏坐标，不做装饰徽章。
- PDF 正文：9.6-10pt / 1.55；公司名 25-29pt；章节标题 15-17pt。
- 表格数字右对齐并使用 tabular numerals；长 SHA 与 URL 允许断行。
- 禁止大面积全大写英文、过度字距、遍地等宽字体和连续粗黑标题。

## 组件、页面与网格

- 屏幕主体最大宽度 1120px；正文与图表共用刊物宽度和 padding，禁止用西文 `ch` 把中文主栏掐出空白。
- 首屏采用 12 栏非对称网格：标题与核心命题为主，研究判断为侧栏，指标沿底部基线排列。
- 桌面目录是顶部安静索引，不占据永久左栏；移动端目录使用明确的展开按钮，不显示被裁掉的半个章节。
- 区块默认依靠分隔线、标题和间距分组；只有真正需要状态边界的内容才使用底色。
- 圆角只用于按钮焦点和少数状态控件；研究正文、图表、表格和来源不使用卡片圆角。

## 颜色与材质

- 主纸张为温和象牙白，不做仿古纹理、渐变、玻璃、光晕、目录毛玻璃或软阴影堆叠。
- 朱砂只用于研究判断、负向变化、当前价格和关键引用；正文主体保持近黑。
- 深色阅读模式使用暖黑和浅灰文字，仍保留朱砂语义，不做简单反相。
- 打印始终是白纸、近黑正文和受控朱砂；保证灰度打印时仍可依靠线型和文字区分。

## 图表

- 财务趋势采用三幅 small multiples；各自量程独立，直接标注起止值和累计变化。
- 估值情景采用细条/区间而非厚重 dashboard 柱形；明确标出当前价格和假设属性。
- 图表必须显示分析问题、单位、时间边界、数据状态和解释，不得只显示漂亮线条。
- SVG 颜色、字重、网格线和正文排版共享 token；图表无圆角外框、无阴影、无渐变。

## 交互与可访问性

- 无 JavaScript 时正文、图表和来源全部可见；JavaScript 只增强主题、目录和阅读进度。
- 桌面目录支持页内导航；移动目录通过 44px 以上按钮展开并在选择章节后关闭。
- 主题按钮、目录按钮和链接具备清晰 `focus-visible`。
- 只允许 `#anchor` 内链；外部来源以不可点击的文本定位符保存。
- `prefers-reduced-motion` 关闭过渡；不使用滚动入场或循环动画。

## PDF

- A4 首页必须同时容纳研究判断、核心命题、关键数字、财务趋势、估值情景，并尽量开始结论正文。
- 页眉显示 Money Craft 与当前章节；页脚显示证券、研究日期和页码，三者缺一不可。
- 表头跨页重复；避免孤立标题、孤立图表、空白尾页和仅含审计封印的页面。
- HTML/PDF 文件名统一为 `report.html` / `report.pdf`；禁止在 Money Craft 当前输出中出现 Kami 命名。

## 禁止模式

- `report-kami.*`、Kami 品牌、Kami renderer 或旧兼容命名出现在当前交付。
- 左侧后台导航、巨型粗黑 hero、四等分 KPI dashboard、同尺寸卡片阵列。
- 图表圆角卡片、低对比灰绿配色、通用绿色金融模板。
- 移动端横向截断目录、不可见剩余内容或只有桌面缩小版的响应式处理。
- 大片无意义空白、每章强制换页、单页只有少量文字。
- 用西文 `68ch`/`70ch`/`72ch` 限制中文正文行宽。
- 末页审计封使用 `FAIL 0`、全大写英文标签等系统回执腔。
