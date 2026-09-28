# 共用核心逐文件审查台账

更新：2026-09-19。范围仅 `skills/money-craft/scripts/*.py` 的 15 个顶层运行时文件，不是全仓 canonical 审查或评分。

**15 REVIEWED_BOUNDED / 0 PARTIAL / 0 PENDING**。各文件完成声明范围整文件读取、问题处置和相关验证；支持边界外的环境不被升级为已验证。当前源码哈希、行数与历史证据路径见[机器台账](../acceptance/core-review-coverage-20260917.json)，本次收口见[统一记录](../acceptance/core-closeout-20260919.json)。

| 文件 | 状态 | 声明范围 |
|---|---|---|
| [earnings_baseline.py](../skills/money-craft/scripts/earnings_baseline.py) | REVIEWED_BOUNDED | 整文件核查前瞻封存、哈希/关联模型、披露时间与回放边界；修复预期期间长度准入。 |
| [earnings_crosscheck.py](../skills/money-craft/scripts/earnings_crosscheck.py) | REVIEWED_BOUNDED | 累计转单季、阈值、日期、证券/币种绑定与结果分级；12 项合成测试。 |
| [earnings_drivers.py](../skills/money-craft/scripts/earnings_drivers.py) | REVIEWED_BOUNDED | 历史勾稽、情景排序、单变量敏感性及顺序归因；12 项合成测试。 |
| [earnings_update.py](../skills/money-craft/scripts/earnings_update.py) | REVIEWED_BOUNDED | 整文件核查来源/期间、重述比较与冻结旧估值、预期首披及 tracking 提案；修复未来研究日期准入。 |
| [financial_reconciliation.py](../skills/money-craft/scripts/financial_reconciliation.py) | REVIEWED_BOUNDED | 整文件核查报表等式、期间/来源合同和异常输入；修复溢出、JSON 小数精度、枚举类型与期间绑定。 |
| [financial_rigor.py](../skills/money-craft/scripts/financial_rigor.py) | REVIEWED_BOUNDED | 整文件核查 Decimal 运算、容差与收据解析；修复多行/损坏收据漏审，极大 JSON 整数转结构化错误。 |
| [fred_adapter.py](../skills/money-craft/scripts/fred_adapter.py) | REVIEWED_BOUNDED | 整文件阅读及独立复核完成；修复Decimal解析逃逸/跳转体无界读取与异常关闭，默认opener受控TLS通过；真实FRED、跨平台及来源语义另列限制。 |
| [money_craft.py](../skills/money-craft/scripts/money_craft.py) | REVIEWED_BOUNDED | 整文件 CLI/配置/Provider/委派/错误语义与独立复核闭合；凭据HTTP头准入、日期上界和UTF8响应补齐。 |
| [report_audit.py](../skills/money-craft/scripts/report_audit.py) | REVIEWED_BOUNDED | 整文件核查元数据、章节/来源解析、引用与占位符；修复索引后漏审、空来源跨行、非规范日期。文件编码/I/O及 Markdown 全语法不作保证。 |
| [report_renderer.py](../skills/money-craft/scripts/report_renderer.py) | REVIEWED_BOUNDED | 整文件与独立复核闭合；同树可见数据投影、状态列绑定、审计计数、可信资产及SVG数值；真实三页PDF和宽窄/明暗HTML另附产物证据。 |
| [research_run.py](../skills/money-craft/scripts/research_run.py) | REVIEWED_BOUNDED | 整文件研究生命周期与独立复核闭合；JSON运行时错误、请求/原始证据/manifest/状态及完成收据合同已验证。 |
| [research_workflow.py](../skills/money-craft/scripts/research_workflow.py) | REVIEWED_BOUNDED | 整文件核查计划身份/期间/Provider 路由及论文解析/diff；修复报告期矛盾、事实与来源变化漏报。 |
| [runtime_paths.py](../skills/money-craft/scripts/runtime_paths.py) | REVIEWED_BOUNDED | 整文件核查路径优先级/legacy/显式env及常量文件名调用；修复symlink绕过、半加载与空进程变量覆盖；POSIX有界验证，父目录/同inode并发/Windows/NFS不保证。 |
| [tracking_workflow.py](../skills/money-craft/scripts/tracking_workflow.py) | REVIEWED_BOUNDED | 整文件初始化、工作区/版本/历史/状态与独立复核闭合；run-state身份/日期/绑定/执行边界与JSON错误准入补齐。 |
| [yfinance_adapter.py](../skills/money-craft/scripts/yfinance_adapter.py) | REVIEWED_BOUNDED | 全文及直接CLI独立复核完成，真实pandas/缺失/类型/日期/导出/超时有界验证；真实Yahoo与证券/财务事实仍需另验，见yfinance-review-boundaries.md。 |

Skill/reference/schema/template、仓库工具和宿主自然语言行为单列，不计入这 15 个运行时文件的分母。旧回执只证明其绑定版本；最终准出以[收口说明](acceptance-closeout.md)为准。
