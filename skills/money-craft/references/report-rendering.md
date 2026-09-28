# 报告渲染合同

Money Craft 的 `report.md`、来源、审计和离线 verifier 是研究真源。HTML/PDF 只是绑定同一份 Markdown SHA-256 的阅读层，不得修改数字、来源、估值、证据状态或结论。

## 视觉与交付合同

- 唯一主题是 `editorial-ivory`：温暖纸张、宋体标题、编辑化网格和数据优先的中文研究刊物，服务长期投资者阅读和复核。
- HTML 必须是单文件离线产物；CSS、JavaScript 和图表内联，不依赖 CDN、远程字体、图片或接口。
- 外部来源地址必须可见但不可点击，使用 `data-source-url` 保留定位符，避免离线报告变成新的网络边界。
- 屏幕端提供目录、阅读进度、浅色/深色切换和响应式布局；打印端固定 A4、页眉页脚、表头重复和分页保护。
- 中文正文使用 `line-break: strict`，宽屏 `word-break: keep-all`、760px 以下 `word-break: normal` 自然折行，主栏全宽；禁止用西文 `ch` 限制中文行宽。PDF 页脚必须同时包含证券、研究日期和页码。审计封使用中文阅读标签，不用系统回执腔。
- 页头只展示源文已披露的指标，识别千分位价格并区分 TTM 与静态 PE。YAML `as_of` / `data_cutoff` 必须保留且在渲染验证中与可见日期逐项核对；首段结论及引用不重复生成。
- 图表只从 canonical Markdown 的已披露表格确定性派生。财务小倍图不用共享纵轴比较绝对规模；估值情景图必须标明假设属性，不得包装为目标价。
- 图表注册表 `CHART_BUILDERS` 决定渲染顺序：前两位（财务趋势小倍图、估值情景条形图）是完整结论之后的核心图表，其余进入其后的扩展视图。新增图表类型时在注册表追加 builder，缺输入时静默返回空，不得生成未披露数字。
- 内置图表清单与数据源契约：

  | 图表 | 数据源 | 降级条件 |
  |---|---|---|
  | 财务趋势小倍图 | 含收入与归母净利润的趋势表，≥3 年，年份可为行或列 | 无匹配表格则不出图 |
  | 估值情景条形图 | Bear/Base/悲观 等规范标签 + 「价值/目标价」列 | 少于 3 个有效情景则不出图 |
  | 盈利质量背离图 | 含「同比」列头 + 营业收入行的变化表，「持平」等非数值行跳过 | 可解析行 < 2 则不出图 |
  | 现金流结构图 | 趋势表中经营现金流与资本开支代理项两行，行标须明确相同单位；FCF 代理为显式公式派生（INFERRED） | 缺任一实体行、年份 < 3、单位缺失或不一致则不出图；原表保留 |
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

渲染在写入前检查输出与全部报告输入的路径关系：HTML/PDF 不得指向源 Markdown、模板、CSS、JS、证据清单、审计或版本/归档清单；HTML 与 PDF 也必须是不同文件。解析后的同路径、软链接别名及现有硬链接均拒绝，避免在事后哈希检查前覆盖输入。此检查不提供跨文件发布事务，也不防止外部进程在检查后替换路径；PDF 或 I/O 中途失败的产物处置仍须单独验收。

模板字段只对模板原文做一次替换，不递归解释报告内容或其他替换值中的字段。替换后仍含 `{{...}}` 的文档会在写出前拒绝；报告正文中的此类未解析标记也会被拒绝，不按字段顺序解释。此规则不是原始 HTML 消毒或完整浏览器安全验收。

资源/导航属性校验使用 HTML 属性解析，识别无引号、大小写及字符实体编码；检查 href/xlink:href、src/srcset、poster、action/formaction、ping、background 和 object data。页内锚点和指定 PNG/JPEG/GIF/WebP base64 内嵌图片允许，其他地址（含相对路径、file 和脚本协议）拒绝。来源地址的文本或 data-source-url 说明不算资源依赖。external_dependency_count 统计这些被拒绝的属性，不代表真实网络请求数；CSS、脚本行为、嵌套文档和完整浏览器语义尚未完成验收，不应将此检查当作不可信 HTML 的安全沙箱。

Markdown 转换后的正文在嵌入模板前接受标签/属性允许列表检查。常用文本、标题、列表、表格、代码、链接、图片及 details/summary 可用；事件属性、脚本、iframe/srcdoc、表单、meta/base/link、原始 SVG/MathML 和其他未列入元素被拒绝。正文内联样式仅支持表格单元格的 text-align；代码块中的转义 HTML 保持文字。模板自身的 CSS/JS 与程序生成图表在正文检查后插入，属于可信渲染资产。历史 Markdown 中的 style 块仍沿用既有解析行为移除。此规则是渲染入口的内容限制，不能替代任意 HTML 的浏览器级安全验证；独立 verify 命令也不因此获得正文来源证明。

HTML/PDF 先在各自输出父目录下的临时目录生成，完成 PDF 生成、源 Markdown 哈希复核及资产摘要读取后才替换正式输出。生成或上述校验失败时保留已有 HTML/PDF，不留下新的正式输出；正常异常处理会清理本次临时目录，但已创建的父目录可能保留。最终两个 os.replace 分别原子，二者不是一个事务：第二次替换失败、进程强杀或断电仍可能留下混合版本。本流程不承诺发布阶段回滚或强杀残留自动清理。

图表数值必须是完整单元格中的明确有限标量，支持规范千分位、小数、科学计数法和单层 Markdown 强调/代码包裹。财务趋势与现金流派生只接受裸数并沿用行标单位；同比允许 `%` 后缀，估值情景和截止日价格允许 `元` 后缀。不从范围、约数、比较式、来源编号或其他文字中截取数字；括号负数和单元格中的异类单位等未支持写法不用于绘图。无法解析的行/情景不画，正文表格保留。这不代表已完成表头单位推断、超大有限数的后续算术或完整 SVG 几何验收。

图表计算若产生不可表示的量程或 FCF 差额，会省略对应图表并保留正文数据；首末年变化率溢出时显示“变化率超出数值范围”。坐标与柱宽先求比例再映射画布，避免大数乘画布尺寸造成中间溢出。该保护不等于金额精度、全部 SVG 几何或实际视觉验收。

数值标签在固定小数位会将非零数舍入为零时使用科学计数法；绝对值达到 1e12 也用科学计数法，避免展开过长标签。负零统一显示为零，常规价格与同比仍保留两位小数。估值/同比柱条按实际比例输出，不再人为设置最小宽度；极小值可能低于可见像素，具体值以标签和正文为准。本合同不保证二进制浮点的十进制精确性，也不代表完整布局验收。

估值情景图只支持明确的每股元值：值列标题接受“目标价”“示意价值”“每股价值”“每股内在价值”“每股合理价值”，可带“元”“元/股”“人民币元”或“人民币元/股”括号单位；无标题单位时各情景值必须自带这些后缀。多个候选值列、外币、总价值、其他单位或裸数无单位不画估值图，保留原表。此处“示意价值”沿用既有每股情景表约定；不做币种识别、汇率换算或总价值到每股值换算。

同比图仅接受百分比：列名为“同比”“同比增长率”“同比增速”“同比变化率”或“同比变动率”，可附“（%）”；无列头百分号时，单元格必须带 `%`。百分点、基点、金额变化和单位不明的裸数不绘制为百分比，原表保留；不将比率自动乘 100，不做单位转换。当前选择器仍先检查首个含“同比”的列，多候选列择优不在此合同内。

财务趋势/现金流要求行标末尾明确金额单位。支持元/千元/万元/百万元/亿元（可前缀人民币）及美元、港元、欧元、日元的裸单位或千/万/百万/亿前缀；不推断或换算。首列标题若带括号单位，须与行标完全一致；缺失、非金额或冲突单位不用于绘图。趋势图每项单独展示单位；现金流差额仍要求两行单位完全相同。该检查只处理末尾括号合同，不解析任意自然语言单位声明，不代表汇率或完整视觉验收。

财务趋势与现金流图对已支持的 `20xx` 年份按升序排列并同步重排数值，累计变化按最早至最晚年计算；横坐标按实际年差定位，不把缺失年份压成连续年。少于三个唯一年份或存在重复年份时不绘制这些图，原表保留。不补值，不扩展季度或其他年代解析；连接线只连接已披露点。

证据摘要仅展示输入清单声明的计数，不据“失败为零”断言完整，也不据条目数量判断质量。计数必须为非负整数，禁止布尔值；别名冲突、非法值或计数大于预期显示“清单计数不可用”，失败计数缺失显示“未提供”。来源组件展示登记组及条目数，空列表为零，缺少列表则“条目数未提供”；这些信息不证明采集成功、证据质量或审计通过。真实性与哈希核验仍由对应审计承担。

实际渲染的图表候选来自正文使用的同一 Markdown 语法树，只接受顶层 Markdown 表格；引用、列表、代码示例、原始 HTML 与注释内的表格不选作图表数据。含原始 HTML 占位的单元格也保守省略整表；正文保持渲染器原有呈现。各图表仍按文档顺序选取首个符合自身入口条件的表，不跨表拼接，不承诺任意 Markdown 方言。估值情景只画唯一的 Bear/Base/Bull 或悲观/中性/乐观三行，重复或混用两套标签省略图表。

审计及离线状态仅展示输入清单声明，不代表本次渲染重新执行审计、绑定来源或离线核验。未知列表格式不据条目数推断通过；非法/矛盾计数不显示 PASS，显式 valid=false 优先于 PASS 声明。可信模板/CSS/JS 必须由调用方控制，内置资产无网络请求逻辑；自定义资产不属于不可信输入沙箱。

## 宿主默认报告入口（2026-09-20）

用户已选择停止使用 Kami。新报告以本仓库 DESIGN.md 与 Design Craft 为设计依据，复用本节自有渲染合同，不再安装或调用 Kami 插件。宿主正式路由为 `report-full` / `report-summary`；摘要需由研究阶段提供，renderer 不自动删减全文。宿主 `investment_report_render.py` 调用本项目 renderer，`investment_archive_report.py` 使用 `--report-python` 指定独立运行时。旧档案内部 `report-kami.*` 仅为快照格式兼容；用户阅读副本仍为 `report.html` / `report.pdf`。研究证据是否完整与报告呈现是否通过必须分别报告。

仅当宿主已提供 `~/.codex/tools/investment_render_gate.py` 且使用正式投资运行账本时，在当前 `render` 阶段运行期间，先生成 HTML/PDF 并完成实际视觉检查，再生成 v2 回执：

```bash
python3 ~/.codex/tools/investment_render_gate.py \
  --run-dir <run-dir> --markdown <report.md> \
  --html <report.html> --pdf <report.pdf> \
  --visual-review <visual-review.json> \
  --skill-root "$MONEY_CRAFT_SKILL_DIR" --python "$REPORT_PYTHON" \
  --output-dir <new-validation-directory>
python3 ~/.codex/tools/investment_run.py complete \
  --run-dir <run-dir> --stage render \
  --render-validation <new-validation-directory>/validation.json
```

`visual-review.json` 至少包含 `status`、实际检查者 `reviewer` 和本次 PDF 的 `pdf_sha256`，仅在已检查实际文件且通过时填 `PASS`；自动生成文件、计划截图或其他版本的检查不能代替实际审查。失败或输入变化后使用新的验证目录。宿主 renderer 通过环境变量 `MONEY_CRAFT_SKILL_DIR` 选择当前固定的 Skill；冻结候选验收时必须传该目录，避免归档时切回其他源码。

阶段完成回执的 `--output` 应登记不会再改写的阶段结果 JSON；后续证据导入、封存仍会更新的工作态 `manifest.json` 不应作为不可变阶段输出。完成 seal 操作后仍需 complete 对应账本阶段，并执行 `investment_run.py verify --run-dir <run-dir> --artifacts` 和独立归档根的 `verify-all`。这些宿主要求不适用于仅生成阅读预览的任务。

正式 archive 阶段应给 `investment_archive_report.py` 传入 `--render-validation <已完成render阶段的v2回执>`，收录刚才实际验证的 HTML/PDF 原始字节，不再重渲染。预览与默认归档可能使用不同的 audit/manifest 输入，省略此参数可能产生哈希不一致并被 seal 拒绝。回执的 run_id 必须与 `--run-id` 一致，源 Markdown 必须匹配；宿主仍在 seal 前验证完成回执与实际档案。没有此宿主工具时继续使用 Skill 自有 rendition 流程。
