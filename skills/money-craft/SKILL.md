---
name: money-craft
description: 对 A 股上市公司做证据优先的基本面筛选、公司研究、财报精读、情景估值和投资论文追踪；不用于短线信号、自动交易或账户操作。
---

# Money Craft

以可核验事实、精确计算和反方证据形成 A 股基本面判断。不要把结构化数据平台、搜索摘要或模型记忆当作正式公告的替代品。

## 路由

先读 [references/routing.md](references/routing.md)，只加载当前模式需要的参考：

- 快速排雷或质量筛选：[references/screening.md](references/screening.md)
- 完整公司研究：[references/company-research.md](references/company-research.md)
- 财报或业绩解读：[references/earnings-review.md](references/earnings-review.md)
- 估值、建立或更新投资论文：[references/valuation-and-thesis.md](references/valuation-and-thesis.md)
- 涉及任何财务、行情或估值数字：[references/financial-data-and-evidence.md](references/financial-data-and-evidence.md)
- 使用 Fuyao 数据客户端：[references/providers/fuyao.md](references/providers/fuyao.md)

完整公司研究在身份和最新正式报告期明确后，先运行确定性的统一入口：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research plan \
  --security <公司全称> --thscode <000000.SH|SZ|BJ> \
  --as-of <YYYY-MM-DD> --latest-report <YYYY-1..4> \
  --provider-mode <auto|required|disabled> --json
```

该命令只生成研究阶段、官方证据、Provider 操作和 artifact 准出合同，不联网、不代写报告，也不把“计划存在”描述成研究完成。

需要实际推进研究时，从同一份计划创建本地可恢复运行；不要手工复制 Provider 操作矩阵：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research init \
  --security <公司全称> --thscode <000000.SH|SZ|BJ> \
  --as-of <YYYY-MM-DD> --latest-report <YYYY-1..4> \
  --provider-mode <auto|required|disabled> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research collect \
  --workspace <init返回的workspace> --resume --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research import-official \
  --workspace <init返回的workspace> --source-id <S11|S12|S13> \
  --file <正式来源文件> --url <HTTPS正式来源> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research status \
  --workspace <init返回的workspace> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research finalize \
  --workspace <init返回的workspace> --json
```

`init`、`status` 不联网；`collect` 是显式 Provider 网络边界。`init` 未传 `--workspace` 时，默认在 `~/Documents/sixseven/money/<ticker>-<company>/<as_of>/.research/<run-id>/` 创建唯一运行目录；`MONEY_CRAFT_OUTPUT_ROOT` 或 `--output-root` 可覆盖根目录。必须复用 `init` 返回的 workspace。`.research` 是私有可变研究态，不是正式 revision；正式报告仍须经独立投资账本、审计、离线 verifier 和 seal 门禁进入 `revisions/rNNNN/`。运行目录中的 `plan.json` 不可改写，`case.json` 必须从 plan 派生，capture 和正式来源默认不覆盖。`import-official` 只导入并哈希绑定本地 PDF/HTML，不自动下载或把 Fuyao 当作公告。`finalize` 只有在来源齐备且 report/thesis 的四项 audit 全部通过时才写完成收据。Provider gap 必须保持可见并写入报告限制，不能包装为完整数据。

## 不可省略的合同

1. 记录当前日期、研究 `as_of`、数据截止时间和最新正式报告期。
2. 将名称或纯代码解析为唯一的完整 `thscode`。多义时列出候选并停止，不替用户猜。
3. 正式公告、交易所披露和公司 IR 是财务事实的主真源。Fuyao 是可选的结构化数据层，不是唯一真源。
4. 关键财务数据必须绑定 `[S01]` 形式的来源；推算值同时写出公式、输入、单位和计算回执。
5. 区分 `OBSERVED`、`INFERRED`、`HYPOTHESIZED`、`UNVERIFIED`。资料不足时降低置信度，不补齐看似完整的数字。
6. 明确给出结论、反方证据、证伪条件和下一次需要验证的事实。筛选通过不等于建议买入。
7. 任何账户访问、下单、发布、消息或外部写操作都需要当前明确授权；本 Skill 本身不执行交易。

## 确定性工具

先把包含本文件的目录解析为绝对路径 `MONEY_CRAFT_SKILL_DIR`；下面的命令路径均相对于该目录，不假设当前工作目录就是 Skill 目录。

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" doctor --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data search --query <名称或代码>
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" audit report <报告.md> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" audit financial <报告.md> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" research status --workspace <local-workspace> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" thesis prepare-update --previous <旧论文.md> --as-of <YYYY-MM-DD> --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" thesis diff --previous <旧论文.md> --current <新论文.md> --json
```

数据命令按顺序读取 `FUYAO_API_KEY` 和权限受限的 `~/.config/money-craft/fuyao-api-key`。两者都没有时必须明确失败；研究可改用宿主可用的官方 Web/文件来源，并在报告中标记结构化 Provider 未启用。若没有任何当前来源，停止事实型判断。`doctor --json` 同时报告凭据状态和当前 research output root，但不联网、不创建目录。

报告可从 [templates/report.md](templates/report.md) 或 [templates/thesis.md](templates/thesis.md) 开始。交付前同时通过 report 和 financial audit；任一失败都不得宣称报告已准出。

更新投资论文时必须先生成 `thesis-update-plan.v1`，逐项评估原有假设和红线；新版完成后运行 `thesis diff`。结构化 diff 会阻断证券身份变化、时间倒退、旧更新记录改写、缺少本期更新记录或任一版本审计失败。只有 diff `valid=true` 才可讨论论文发生了什么变化；`signal` 是复核优先级，不是交易指令。
