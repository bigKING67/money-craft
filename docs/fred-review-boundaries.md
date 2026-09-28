# FRED 整文件有界审查

2026-09-19，Review Craft bounded fast path；无评分、非 canonical 全仓审查。源码全文已读，直接 CLI 映射和 capture 调用边界已核对；既有测试加本轮回归为证据，不以测试数量代表分支全覆盖。精确源码哈希见 [本轮回执](../acceptance/fred-closeout-review-20260919.json)。

| 范围 | 决定与证据 |
| --- | --- |
| 凭据、路径、文件身份 | KEEP：环境变量优先，安全文件身份/权限/限量读取，已有竞态回归；父目录信任、同 inode 并发内容与 Windows/NFS 保留限制。 |
| 请求与重定向 | KEEP：CLI 负责参数准入；适配器固定端点、HTTPS、同主机跳转；自定义 opener 属可信调用方，不保证任意参数字典。 |
| 响应字节与解析 | FIX：实际长度与 Content-Length 核对；不足转网络重试，超出拒绝。标准库 HTTPResponse 的截断回归通过；深层 JSON 在当前 Python 已结构化拒绝，KEEP。 |
| HTTP 错误、重试、释放 | KEEP：三次上限、退避、状态保留及显式错误响应释放已有离线证据；独立 diff review 和默认 opener 真实网络生命周期证据仍缺。 |
| 身份、日期、转换 | KEEP：series 唯一身份、历史单日有效区间、观测日期范围和显式 units 绑定；不证明经济含义或上游转换算术。 |
| 分页 | DOCUMENT：合法部分页明确提示，缺元数据提示 unverified；保留原始 capture，不自动翻页。 |
| 输出与调用方 | KEEP：原始字节不改写，CLI 区分配置/格式/暂时失败；无自动交易能力。 |

## 保留的收口条件

FRED 继续 PARTIAL。源码全文阅读不等于生命周期高保障验收：仍需独立复核近期 credential/transport/network 改动，以及默认 opener 的受控 HTTPS/重定向/异常关闭证据。真实 FRED/ALFRED 数据连通性单列，不能用测试替代。

任意 realtime 区间、vintages 请求范围响应绑定、自动分页、HTTP 日期型 Retry-After、跨平台/网络文件系统不在已完成行为保证内。当前 CLI 暴露的 vintages start/end 仍需补范围绑定验收；不是把现有入口移出范围。

下一步先完成该现有入口的范围绑定，再做独立复核；不继续用零散补测替代模块收口。yfinance 随后处理，应用仍后置。

## 后续范围绑定结果

2026-09-19：上述 vintages start/end 已完成显式边界回显及逐日期闭区间验证，证据见[范围验收](../acceptance/fred-vintage-range-review-20260919.json)。该项从待办关闭；下一步为独立生命周期复核与默认 HTTPS 路径验收，模块仍 PARTIAL。前述清单保留为整文件审查时点的记录。

## 有界收口结果

2026-09-19：独立复核与默认opener受控TLS验收完成，见[最终回执](../acceptance/fred-https-review-20260919.json)。Decimal解析和重定向体读取/关闭两项发现均已修复，并按最终hash复验无剩余已验证阻断。模块转REVIEWED_BOUNDED，前述PARTIAL属于历史审查时点。真实FRED、其他Python/平台及来源语义不在本次通过声明内。
