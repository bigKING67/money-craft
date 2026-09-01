# 报告渲染合同

Money Craft 的 `report.md`、来源、审计和离线 verifier 是研究真源。HTML/PDF 只是绑定同一份 Markdown SHA-256 的阅读层，不得修改数字、来源、估值、证据状态或结论。

## 视觉与交付合同

- 唯一主题是 `editorial-ivory`：温暖纸张、宋体标题、编辑化网格和数据优先的中文研究刊物，服务长期投资者阅读和复核。
- HTML 必须是单文件离线产物；CSS、JavaScript 和图表内联，不依赖 CDN、远程字体、图片或接口。
- 外部来源地址必须可见但不可点击，使用 `data-source-url` 保留定位符，避免离线报告变成新的网络边界。
- 屏幕端提供目录、阅读进度、浅色/深色切换和响应式布局；打印端固定 A4、页眉页脚、表头重复和分页保护。
- 中文正文使用 `line-break: strict; word-break: keep-all`，主栏全宽；禁止用西文 `ch` 限制中文行宽。PDF 页脚必须同时包含证券、研究日期和页码。审计封使用中文阅读标签，不用系统回执腔。
- 图表只从 canonical Markdown 的已披露表格确定性派生。财务小倍图不用共享纵轴比较绝对规模；估值情景图必须标明假设属性，不得包装为目标价。
- 图表注册表 `CHART_BUILDERS` 决定渲染顺序：前两位（财务趋势小倍图、估值情景条形图）是首屏主图，其余进入其后的扩展视图。新增图表类型时在注册表追加 builder，缺输入时静默返回空，不得生成未披露数字。
- 内置图表清单与数据源契约：

  | 图表 | 数据源 | 降级条件 |
  |---|---|---|
  | 财务趋势小倍图 | 含「营业收入」行 + ≥3 个年份列的趋势表 | 无匹配表格则不出图 |
  | 估值情景条形图 | Bear/Base/悲观 等规范标签 + 「价值/目标价」列 | 少于 3 个有效情景则不出图 |
  | 盈利质量背离图 | 含「同比」列头 + 营业收入行的变化表，「持平」等非数值行跳过 | 可解析行 < 2 则不出图 |
  | 现金流结构图 | 趋势表中经营现金流与资本开支代理项两行；FCF 代理为显式公式派生（INFERRED） | 缺任一实体行或年份 < 3 则不出图 |
  | 证伪条件状态 | 行首 R 编号 + material/fatal 强度 + WATCH/CLEAR/UNVERIFIED/BROKEN 状态的表格 | 无匹配行则不出组件 |
  | 证据来源覆盖 | 渲染输入的 evidence manifest groups | 无 manifest 或无 groups 则不出组件 |

- 派生序列（如 FCF 代理）必须用中性虚线语义并在图注标明公式与 INFERRED 属性，不得伪装为披露值；图表 meta 需标注数据状态（OBSERVED/HYPOTHESIZED）。
- 图表颜色走 CSS 变量三态 token（`--chart-*`）：SVG presentation attribute 保 light hex 作为 WeasyPrint 最坏回退，class 规则赋 `var(--chart-*)` 实现屏幕亮/暗切换；打印区显式重置为 light 值阻断暗色泄漏。系列色板与 Python `CHART_SERIES_LIGHT/DARK` 常量同源，由测试对账防漂移。文字一律用文本 token，不占用系列色。
- 任何 render 都要求显式 `--output-dir`、`--output-html` 或 `--output-pdf`，禁止把 canonical revision 目录当作隐式写入目标。

## 可选渲染运行时

核心研究运行时仍只需要 Python 标准库。HTML/PDF 渲染另外需要 `Markdown`、`WeasyPrint` 和 `pypdf`：

```bash
MONEY_CRAFT_DATA_HOME="${MONEY_CRAFT_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/money-craft}"
python3 -m venv "$MONEY_CRAFT_DATA_HOME/venvs/report"
"$MONEY_CRAFT_DATA_HOME/venvs/report/bin/python" -m pip install \
  -r "$MONEY_CRAFT_SKILL_DIR/requirements-report.txt"
```

可用 `MONEY_CRAFT_REPORT_PYTHON` 指向其他受控 Python；不要把虚拟环境、缓存或凭据复制进 Skill。

## 预览渲染

下面的命令只生成显式目录中的派生物，不创建或修改正式 research revision：

```bash
REPORT_PYTHON="${MONEY_CRAFT_REPORT_PYTHON:-${MONEY_CRAFT_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/money-craft}/venvs/report/bin/python}"
"$REPORT_PYTHON" "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" report render \
  --source <revision>/report.md \
  --output-dir <repo-external-preview-dir> \
  --evidence-manifest <revision>/sources/sources.manifest.json \
  --audit <revision>/report.audit.json \
  --revision-manifest <revision>/REVISION.json \
  --archive-manifest <revision>/manifest.json \
  --json

"$REPORT_PYTHON" "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" report verify \
  --source <revision>/report.md \
  --html <repo-external-preview-dir>/report.html \
  --pdf <repo-external-preview-dir>/report.pdf \
  --json
```

`report verify` 必须确认 Markdown SHA-256、portable HTML、零外部依赖和有效 PDF 页数。视觉验收另做真实浏览器宽屏、窄屏和 PDF 页面检查；静态 verifier 不能替代视觉判断。

## 正式档案

正式 Money 档案使用非破坏性的 rendition 流程：以已封存 revision 为输入，创建 preview，记录 renderer/template/style/script 的不可变摘要，完成视觉 review 后再原子切换当前 rendition。当前阅读层的用户文件名固定为公司目录下的 `report.html` 和 `report.pdf`，不得暴露底层渲染实现名；内部 `renders/` 只作可重建档案。任何渲染都不得覆写 canonical `report.md`。
