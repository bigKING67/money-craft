# 上市公司完整研究

## 统一入口

证券身份、`as_of` 和最新正式报告期明确后，先运行 `money_craft.py research plan`。计划必须绑定公司全称、完整 `thscode`、A 股交易所、最新报告期和最近年度报告期，并输出：

- `identity -> official-evidence -> provider-cross-check -> research -> valuation-and-thesis -> audit` 六阶段门禁；
- 固定来源 ID 的有界 Provider 操作矩阵；
- 最新正式报告、年度报告、交易所或公司 IR 三类一手证据要求；
- report、thesis、metadata-only evidence manifest 和四项 audit artifact 合同。

`research plan` 是可重复的执行规格，不是研究结果。它不访问网络，不证明 Provider 数据存在，也不能替代实际来源捕获、计算和审计。

## 可恢复研究运行

需要落地研究时，使用 `research init` 将 plan 固化到本地 workspace。`case.json` 必须由 `plan.json` 自动派生；不得另写一份 Provider 操作列表。workspace 的状态真源包括不可变 plan、派生 case、append-only `run-state.json`、私有 `evidence/`、报告、论文、审计和完成收据。

1. `research collect --resume` 只执行 case 内有界操作，已有 normalized response 和 capture 不覆盖；单项失败形成显式 Provider gap，并返回非零结果。
2. `research import-official` 逐项导入 plan 声明的 `S11/S12/S13`，校验 PDF/HTML、HTTPS 来源、大小和 SHA-256；不负责联网下载。
3. `research status` 离线重算每一阶段，列出 missing sources 和 provider gaps；文件存在不等于阶段完成。
4. 报告和 thesis 写完后运行 `research finalize`。它生成 metadata-only manifest 和四项 audit artifact；只有身份、证据、report、thesis 与计算全部有效时才产生 completion receipt。
5. 收据绑定 plan、case、manifest、报告、论文和审计文件哈希。收据之后任一绑定文件变化都必须显示 stale，不得继续宣称完成。

默认 workspace 位于 `~/Documents/sixseven/money/<ticker>-<company>/<as_of>/.research/<run-id>/`；`MONEY_CRAFT_OUTPUT_ROOT` 和 `--output-root` 可改变根目录，显式 `--workspace` 可完全覆盖。必须复用 `init` 返回的动态路径，不使用 `latest` 软链接或共享可变目录。`.research` 仅是 Money Craft 私有研究态，不得伪装成正式档案；完成正式投资账本、审计、离线 verifier 和 seal 后，准出真源才位于同一公司/日期下的 `revisions/rNNNN/`。任何凭据、原始 Provider payload、下载公告或网页快照都不得进入 Git。

## 研究顺序

1. **资料与偏见**：评级资料可得性，写出市场共识和最可能的共识陷阱。
2. **生意本质**：客户是谁、为何付费、收入和成本如何形成、哪些变量决定十年结果。
3. **财务画像**：至少覆盖五年收入、利润、现金流、资本开支、负债、股本和回报率；年度优先，季度用于识别变化。
4. **护城河**：只接受可观察证据，例如价格、留存、份额、单位成本、渠道、牌照、研发结果；区分存量和变化方向。
5. **管理层与治理**：承诺兑现、资本配置、关联交易、股权激励、并购和会计选择。
6. **逆向思考**：列出最强反方论证、可导致永久损失的路径、可能被忽略的替代品和监管变化。
7. **估值与安全边际**：使用适合商业模式的方法，至少给悲观/中性/乐观三种情景和关键敏感变量。
8. **结论**：说明当前证据支持什么、不支持什么、需要观察什么，以及哪些事实会推翻结论。

## 护城河证据表

| 类型 | 事实 | 来源 | 方向 | 反方解释 | 置信度 |
|---|---|---|---|---|---|
| 品牌/定价权 |  | `[S#]` | 变宽/稳定/变窄 |  | 高/中/低 |
| 转换成本 |  | `[S#]` |  |  |  |
| 网络效应 |  | `[S#]` |  |  |  |
| 规模/成本 |  | `[S#]` |  |  |  |
| 技术/牌照 |  | `[S#]` |  |  |  |

“竞争对手投入大量资本能否复制”必须拆成时间、渠道、数据、品牌、组织和监管约束，不能只凭直觉回答。

## 结论纪律

清楚区分好公司、好生意和好价格。若估值所依赖的盈利不是正数、现金流不可持续或数据冲突未解决，停止输出精确目标价，改为条件区间和补证事项。不得把报告完整度当成投资确定性。
