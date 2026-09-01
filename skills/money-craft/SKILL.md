---
name: money-craft
description: 面向全球市场的证据优先投资研究与理财决策支持，覆盖上市公司、行业主题、基金与组合分析、财报、估值和论文追踪；不执行自动交易或账户操作。
---

# Money Craft

以可核验事实、精确计算和反方证据支持全球投资研究与理财决策。A 股只是 Fuyao 适配器当前覆盖的一个市场，不是 Money Craft 的产品边界。不要把结构化数据平台、搜索摘要或模型记忆当作正式披露的替代品。

## 路由

先读 [references/routing.md](references/routing.md)，只加载当前模式需要的参考：

- 快速排雷或质量筛选：[references/screening.md](references/screening.md)
- 完整公司研究：[references/company-research.md](references/company-research.md)
- 全球市场、基金/债券/组合或跨币种理财问题：[references/global-investing.md](references/global-investing.md)
- 行业主题、时代主线、核心资产或高增长 α：[references/high-growth-alpha.md](references/high-growth-alpha.md)；研究具体公司时同时加载完整公司研究和估值规则
- 财报或业绩解读：[references/earnings-review.md](references/earnings-review.md)
- 估值、建立或更新投资论文：[references/valuation-and-thesis.md](references/valuation-and-thesis.md)
- 将论文更新封存为公司级跟踪历史：[references/tracking-workflow.md](references/tracking-workflow.md)
- 涉及任何财务、行情或估值数字：[references/financial-data-and-evidence.md](references/financial-data-and-evidence.md)
- 使用 Fuyao A 股客户端：[references/providers/fuyao.md](references/providers/fuyao.md)
- 使用可选 yfinance 港美股客户端：[references/providers/yfinance.md](references/providers/yfinance.md)
- 使用 FRED/ALFRED 宏观、利率、通胀和历史 vintage 数据：[references/providers/fred.md](references/providers/fred.md)
- 生成或验收最终 HTML/PDF：[references/report-rendering.md](references/report-rendering.md)

完整公司研究在身份和最新正式报告期明确后，先运行确定性的统一入口：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research plan \
  --security <公司全称> --security-id <MARKET:SYMBOL> --base-currency <USD|HKD|CNY|...> \
  --as-of <YYYY-MM-DD> --latest-report <YYYY-1..4> --latest-report-end <YYYY-MM-DD> \
  --latest-annual-report <YYYY-4> \
  --provider <auto|fuyao|yfinance> --provider-mode <auto|required|disabled> --json
```

该命令只生成研究阶段、官方证据、Provider 操作和 artifact 准出合同，不联网、不代写报告，也不把“计划存在”描述成研究完成。

需要实际推进研究时，从同一份计划创建本地可恢复运行；不要手工复制 Provider 操作矩阵：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research init \
  --security <公司全称> --security-id <MARKET:SYMBOL> --base-currency <三字母币种> \
  --as-of <YYYY-MM-DD> --latest-report <YYYY-1..4> --latest-report-end <YYYY-MM-DD> \
  --latest-annual-report <YYYY-4> \
  --provider <auto|fuyao|yfinance> --provider-mode <auto|required|disabled> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research collect \
  --workspace <init返回的workspace> --resume --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research import-official \
  --workspace <init返回的workspace> --source-id <S11|S12|S13|S18|S19|S20> \
  --file <正式来源文件> --url <HTTPS正式来源> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research status \
  --workspace <init返回的workspace> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research finalize \
  --workspace <init返回的workspace> --json
```

`security_id` 使用 Money Craft 的开放 `MARKET:SYMBOL` 语法，例如 `CN-SZ:000333`、`HK:00700`、`US-NASDAQ:NVDA`；它不是对某个外部交易所代码标准的声明。A 股仍兼容 `--thscode 000333.SZ`，并自动派生 `security_id`。A 股日历季度可省略 `--latest-report-end`，非 A 股必须显式提供财政报告期结束日；非 A 股中报还要给出最近年度 `--latest-annual-report`，避免把自然年季度误当财政季度。

`init`、`status` 不联网；`collect` 是当前计划所选结构化 Provider 的显式网络边界。A 股默认选择 Fuyao，港股和美股默认选择可选 yfinance；可用 `--provider <auto|fuyao|yfinance>` 显式选择。计划无可用结构化适配器时，`provider_operations=[]` 且 Provider gap 保持可见，研究仍可通过正式披露导入推进，不能把“无适配器”误报成“无研究能力”。默认运行目录为 `~/Documents/sixseven/money/<identity>-<company>/<as_of>/.research/<run-id>/`；`MONEY_CRAFT_OUTPUT_ROOT` 或 `--output-root` 可覆盖。必须复用 `init` 返回的 workspace。`.research` 是私有可变研究态，不是正式 revision；正式报告仍须经独立投资账本、审计、离线 verifier 和 seal 门禁进入 `revisions/rNNNN/`。`plan.json` 不可改写，`case.json` 必须从 plan 派生，capture 和正式来源默认不覆盖。`S11/S12/S13` 是必需来源；`S18/S19/S20` 分别用于被触发的重大交易或资本事项、官方管理层问答、报告期后重大事项。`import-official` 只导入并哈希绑定本地 PDF/HTML，不自动下载。`finalize` 只有在来源齐备、report/thesis 四项 audit 和 reconciliation audit 全部通过时才写完成收据。

## 不可省略的合同

1. 记录当前日期、研究 `as_of`、数据截止时间和最新正式报告期。
2. 将对象解析为唯一 `security_id`，并记录市场、交易币种、报告币种、工具类型和 share class；同名、多地上市或存托凭证有歧义时列出候选并停止。
3. 当地监管机构、交易所、发行人/基金管理人正式披露和法定文件是主真源。Fuyao 和 yfinance 都只是结构化数据适配器。
4. 关键财务数据必须绑定 `[S01]` 形式的来源；推算值同时写出公式、输入、单位和计算回执。
5. 区分 `OBSERVED`、`INFERRED`、`HYPOTHESIZED`、`UNVERIFIED`。资料不足时降低置信度，不补齐看似完整的数字。
6. 明确给出结论、反方证据、证伪条件和下一次需要验证的事实。筛选通过不等于建议买入。
7. 任何账户访问、下单、发布、消息或外部写操作都需要当前明确授权；本 Skill 本身不执行交易。

## 确定性工具

先把包含本文件的目录解析为绝对路径 `MONEY_CRAFT_SKILL_DIR`；下面的命令路径均相对于该目录，不假设当前工作目录就是 Skill 目录。

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" doctor --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data search --query <名称或代码>
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data observations --series-id <FRED_SERIES_ID> --start <YYYY-MM-DD> --end <YYYY-MM-DD>
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" audit report <报告.md> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" audit financial <报告.md> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" audit reconciliation <financial-reconciliation.json> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research status --workspace <local-workspace> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" thesis prepare-update --previous <旧论文.md> --as-of <YYYY-MM-DD> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" thesis diff --previous <旧论文.md> --current <新论文.md> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track init --tracking-root <公司目录>/tracking --previous <旧论文.md> --as-of <YYYY-MM-DD> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track check --workspace <init返回的workspace> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track status --tracking-root <公司目录>/tracking --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track verify --tracking-root <公司目录>/tracking --json
"${MONEY_CRAFT_REPORT_PYTHON:-${MONEY_CRAFT_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/money-craft}/venvs/report/bin/python}" \
  "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" report render \
  --source <report.md> --output-dir <repo-external-rendition-dir> --json
"${MONEY_CRAFT_REPORT_PYTHON:-${MONEY_CRAFT_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/money-craft}/venvs/report/bin/python}" \
  "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" report verify \
  --source <report.md> --html <report.html> --pdf <report.pdf> --json
```

`data` 子命令用 `--provider fuyao|yfinance|fred` 选择适配器；`series`、`observations`、`vintages` 是 FRED 专用宏观操作。Fuyao 读取 `FUYAO_API_KEY` 或权限受限的 `~/.config/money-craft/fuyao-api-key`；FRED 读取 `FRED_API_KEY` 或同样受限的 `~/.config/money-craft/fred-api-key`；两者都禁止命令行 key。配置、持久运行数据和缓存分别遵循 `~/.config/money-craft`、`~/.local/share/money-craft`、`~/.cache/money-craft`，并可用 `MONEY_CRAFT_CONFIG_HOME`、`MONEY_CRAFT_DATA_HOME`、`MONEY_CRAFT_CACHE_HOME` 或对应 XDG 变量覆盖；覆盖路径必须是绝对路径。源码开发可用 `MONEY_CRAFT_ENV_FILE` 显式选择权限受限的 dotenv 文件，但运行时不搜索 cwd 或父目录。yfinance 是 `requirements-yfinance.txt` 中锁定的可选依赖，默认持久数据解释器为 `~/.local/share/money-craft/venvs/data/bin/python`；旧 `~/.config/money-craft/data-venv/bin/python` 只在新环境不存在且未显式覆盖路径时作为迁移兼容回退。系统 `python3` 启动主入口时会在首选环境存在时透明切换。FRED/ALFRED 用于宏观时间序列和历史 vintage，不替代公司正式披露；历史复盘和回测优先使用 as-known-on 数据，防止未来信息污染。凭据、依赖缺失或目标不受支持时必须明确失败并形成 Provider gap；若没有任何当前来源，停止事实型判断。`doctor --json` 不联网、不创建目录。

报告可从 [templates/report.md](templates/report.md) 或 [templates/thesis.md](templates/thesis.md) 开始。完整公司研究和财报精读还必须完成 plan 生成的 reconciliation artifact：明确本期/比较期是原披露、重述还是可比估算，校验资产负债式和现金余额勾稽，Q2-Q4 还要校验累计值推导单季，并处理会计列报到经营实质、期后事项。任一 audit 失败都不得宣称报告已准出。

最终 HTML/PDF 必须按 `report-rendering.md` 从已审计 Markdown 派生：输出目标显式、SHA-256 绑定、离线可读、外部来源可见但不可点击，并完成真实浏览器宽屏/窄屏和 PDF 视觉验收。渲染器不能改写 sealed revision 或研究结论。

更新投资论文时必须先生成 `thesis-update-plan.v1`，逐项评估原有假设和红线；新版完成后运行 `thesis diff`。结构化 diff 会阻断 `security_id` 或基础币种变化、时间倒退、旧更新记录改写、缺少本期更新记录或任一版本审计失败。只有 diff `valid=true` 才可讨论论文发生了什么变化；`signal` 是复核优先级，不是交易指令。

需要把更新沉淀到 `~/Documents/sixseven/money/<identity>-<company>/tracking/` 时，使用 `track init/check/status/verify`，不要手工拼装 revision。`init`、`status`、`verify` 和 `check` 都离线、无模型、无账户访问；`check` 只在论文、状态、跟踪卡、append-only diff 与两项 audit 全部通过后创建只读 `tNNNN` 并原子切换 `current.json`。未完成占位符、健康度不一致或可写 revision 都必须失败。
