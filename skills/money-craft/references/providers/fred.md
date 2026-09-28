# FRED / ALFRED 宏观数据 Provider

官方合同：

- https://fred.stlouisfed.org/docs/api/api_key.html
- https://fred.stlouisfed.org/docs/api/fred/series_search.html
- https://fred.stlouisfed.org/docs/api/fred/series.html
- https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- https://fred.stlouisfed.org/docs/api/terms_of_use.html

FRED 用于宏观、利率、通胀、就业、增长、流动性和信用环境的结构化时间序列；ALFRED 用于读取历史时点当时已知的版本。它们是宏观研究基础设施，不是公司法定披露、证券行情或交易信号 Provider。

> This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.

## 凭据与运行边界

每个请求都需要 32 位小写字母数字 API key。运行时依次读取 `FRED_API_KEY` 和权限为 `0600` 或更严格的 `~/.config/money-craft/fred-api-key`；密钥文件必须由当前用户拥有、是普通文件且不能是符号链接。配置路径可由绝对 `MONEY_CRAFT_CONFIG_HOME` 或 `XDG_CONFIG_HOME` 覆盖；持久数据与缓存分别可由绝对 `MONEY_CRAFT_DATA_HOME`/`XDG_DATA_HOME` 和 `MONEY_CRAFT_CACHE_HOME`/`XDG_CACHE_HOME` 覆盖。源码开发只能用 `MONEY_CRAFT_ENV_FILE` 显式选择权限受限的 dotenv 文件，运行时不搜索 cwd 或父目录。FRED 把 key 放在查询参数中，因此客户端不得记录完整请求 URL、把 key 写进 capture、错误文本、报告或 shell 参数。

如果 key 曾出现在聊天、截图、日志或命令历史中，先在 FRED Account 撤销并创建新 key，再通过无回显输入保存：

```bash
install -d -m 700 ~/.config/money-craft
read -rs 'FRED_API_KEY?FRED API key: '; printf '%s\n' "$FRED_API_KEY" > ~/.config/money-craft/fred-api-key; unset FRED_API_KEY
chmod 600 ~/.config/money-craft/fred-api-key
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" doctor --json
```

Money Craft 的持久数据运行时默认位于 `~/.local/share/money-craft/venvs/data`，可用 `MONEY_CRAFT_DATA_HOME` 或 `XDG_DATA_HOME` 改变数据根目录。直接用系统 `python3` 启动 `money_craft.py` 时，只要首选环境存在，入口会透明切换到它；在报告 venv 或其他显式 venv 中运行时不会抢占解释器。旧 `~/.config/money-craft/data-venv` 仅在新环境不存在且路径未显式覆盖时作为迁移兼容回退；可用 `MONEY_CRAFT_DATA_PYTHON` 直接指定另一个受控解释器。

## 有界 CLI

```bash
# 搜索 series id，不把自然语言搜索结果直接写进投资结论
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data search \
  --provider fred --query "10-year breakeven inflation" --limit 10

# 读取 series 元数据：标题、来源、单位、频率、季调、更新时间和 notes
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data series \
  --series-id T10YIE

# 当前最新修订口径
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data observations \
  --series-id T10YIE --start 2020-01-01 --end 2026-09-01 --units lin

# 2024-12-31 当时能够看到的历史版本，防止未来信息污染
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data observations \
  --series-id GDPC1 --start 2019-01-01 --end 2024-12-31 \
  --as-known-on 2024-12-31 --units lin

# 列出发生新增或修订的 vintage dates
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" data vintages \
  --series-id GDPC1 --start 2020-01-01 --end 2026-09-01
```

`--units` 只开放官方的 `lin`、`chg`、`ch1`、`pch`、`pc1`、`pca`、`cch`、`cca`、`log` 变换。若投资论文依赖变换值，必须保留原始 series id、原单位、变换代码、观测区间与 real-time/as-known-on 日期。返回值 `.` 表示缺失，不能补零。

## 建议的宏观仪表盘

| 研究维度 | 常用 series id | 能回答什么 | 不能直接推出什么 |
|---|---|---|---|
| 政策与短端利率 | `DFF`、`FEDFUNDS`、`SOFR` | 实际政策约束和美元短端资金价格 | 下一次会议必然加息或降息 |
| 国债曲线 | `DGS2`、`DGS10`、`DGS30`、`T10Y2Y`、`T10Y3M` | 无风险利率、期限结构、曲线倒挂 | 单独预测衰退日期或股市方向 |
| 已实现通胀 | `CPIAUCSL`、`CPILFESL`、`PCEPI`、`PCEPILFE` | 总体/核心 CPI 与 PCE 的变化 | 市场未来通胀定价 |
| 通胀预期/补偿 | `T5YIE`、`T10YIE`、`T5YIFR`、`MICH` | 市场隐含和调查型通胀预期的方向 | 纯粹、无风险溢价的真实预期 |
| 增长与生产 | `GDPC1`、`INDPRO` | 实际增长和工业周期 | 高频实时增长结论 |
| 就业 | `UNRATE`、`PAYEMS`、`ICSA` | 失业、非农和初请的趋势 | 未经修订的实时劳动力全貌 |
| 美联储与财政流动性 | `WALCL`、`RRPONTSYD`、`WTREGEN` | 美联储资产负债表、逆回购和财政部现金余额 | 机械等同于股票市场净流动性 |
| 信用与金融条件 | `BAMLH0A0HYM2`、`NFCI` | 高收益利差和综合金融条件 | 单指标择时或信用事件概率 |

series id 只是入口。任何正式使用都先读取 `data series` 元数据，确认来源、单位、频率、季调、更新时间和 notes；同名指标不得仅凭 ticker 猜口径。通胀保值债券 breakeven 同时包含通胀预期、风险溢价和流动性影响，流动性代理也不是可直接加减得到的“股市资金净流入”。这些解释属于 `INFERRED`，不是 FRED 原始观测。

## FRED 与 ALFRED 的选择

- 回答“截至今天最新修订后的历史是多少”：不传 `--as-known-on`，使用 FRED mode。
- 回答“在某个历史决策日，当时能看到什么”：传 `--as-known-on YYYY-MM-DD`，使用同日闭区间 real-time period。
- 判断修订风险：先用 `data vintages` 找修订日期，再比较两个或更多 as-known-on capture。
- 回测、历史论文复盘和预测评估默认使用 ALFRED vintage；不得拿今天修订后的 GDP/CPI 历史回填过去模型并称为实时结果。

观测日期不是发布日期。月度或季度 series 的 `date` 是观测期标签，是否在决策时已发布由 real-time period、vintage 和 series 更新时间共同判断。

## 证据、权利与失败语义

FRED 汇集许多来源，部分 series 由第三方拥有并带有版权或使用限制；FRED API 的可访问性不覆盖原数据所有者的权利。正式报告保留 series 元数据、原来源/notes、抓取时间、查询口径和 capture 哈希，不批量再分发原始数据集。

官方条款没有承诺固定不变的速率上限，只说明可能限流和调整额度。客户端对 `429`、`5xx` 和短暂网络错误最多尝试三次，尊重并限制 `Retry-After`；仍失败就形成 `PROVIDER_GAP`，不能用旧值或模型记忆补齐。没有适用于结论的当前正式或可追溯来源时停止事实型判断；FRED 的可用性不能替代公司正式披露。

### 观测响应准入（2026-09-19）

当前 CLI 使用默认 `output_type=1`；适配器对该格式逐行核对对象、规范 ISO 日期及字符串数值，数值须可解析为有限 Decimal，缺失标记 `.` 原样保留，不转零。其他输出形态拒绝为 malformed_response，不假装已支持。响应出现错误字段时先核对错误信封，非法/缺失错误码不会因同时存在数据数组而当作成功；这些错误不写入成功 capture。

官方格式依据：[observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)、[errors](https://fred.stlouisfed.org/docs/api/fred/errors.html)。本轮仅验证离线注入及 CLI 错误传播，未请求真实 Provider 数据；不证明序列身份、单位、实时修订区间或经济含义已核验，其他端点及 transport/credential 边界仍待审。

### 传输与错误文本（2026-09-19）

FRED client 基础 URL 须为带主机的 HTTPS，不接受用户信息、查询串、fragment 或非法端口；默认重定向处理器只允许 HTTPS 且相同主机/端口，不允许降级。显式注入的 opener 属于调用方信任边界，不以这些检查保证其行为。错误信息先替换完整已知凭据再截断至 500 字符，避免截断留下凭据前缀；不声称识别任意变形、编码或上游已截断的秘密。离线注入与 CLI 传播测试不等于真实网络重定向验收。

### 凭据文件读取（2026-09-19）

安全文件在原路径检查后，以禁止跟随末级符号链接及非阻塞方式打开（平台支持时），通过同一文件描述符复核设备/inode、普通文件类型、所有者与权限，再最多读取上限加一个字节并校验实际长度。检查后替换、权限放宽或超限增长会返回 invalid_configuration，在网络与capture之前停止。文件缺失仍为missing_configuration；环境变量优先逻辑不变。不保证父目录可信性、同inode同时改写字节的一致快照或Windows/NFS语义。

### 序列身份与历史单日响应（2026-09-19）

`series` 必须返回唯一记录，且 id 与请求完全一致；`search` 每条记录必须为对象并有非空字符串 id，允许空结果。`vintages` 逐项校验规范 ISO 日期，不假设升序。`series`/`observations` 的单日 realtime 请求（CLI `--as-known-on`）要求响应顶层两个日期与请求一致，逐行有效区间包含该日；不要求逐行区间端点相等。异常作为 malformed_response 在成功 capture 前拒绝，保留合法原始响应字节。

依据：[series](https://fred.stlouisfed.org/docs/api/fred/series.html)、[vintagedates](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html)、[Real-Time Periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)。observations/vintages 响应自身没有序列 id，本检查不能独立证明这些数值来自请求序列；仍依赖请求、传输与采集关联。任意 realtime 区间、观测日期范围、单位转换、分页完整性与真实 Provider 数据语义尚未闭环。

### 网络失败与响应释放（2026-09-19）

HTTP 错误体只做有界读取，读失败不覆盖已知 HTTP 状态；在重试前显式关闭错误响应。读失败或关闭失败会在结构化错误消息中保留通用诊断，不回显底层秘密。429/5xx 仍按原策略最多尝试三次，400 等不可重试状态直接失败。正常响应读取阶段的 HTTP 协议异常（包括 IncompleteRead）转换为可重试 network_error，context manager 负责退出释放。非有限 Retry-After 值回退默认退避；有限秒数继续限制在 0..10。

离线回归覆盖读取中断、关闭失败、三次重试耗尽及真实 CLI 入口错误传播；失败返回 EXIT_TRANSIENT，不写成功 capture。此处三次上限是尝试次数，不是总耗时保证；不声称真实网络、HTTP 日期形式 Retry-After 或全部协议状态已验收。

### 分页、观测范围与转换口径（2026-09-19）

观测日期须落在请求的 observation_start/end 闭区间内；显式请求 units 时，响应转换标识须完全一致。此处 units 表示 lin/pch 等转换，不是币种，也不证明上游计算正确。分页 count/offset/limit 如出现任一字段，须全部为合法整数、与请求匹配且条数自洽；返回条数不得超过请求 limit。完全缺少分页元数据时保留响应，但 CLI 警告完整性 unverified；合法非完整页则提示 partial page。不会自动遍历分页，不把一次成功采集等同于完整数据集；原始 capture 保留上游分页字段，CLI 警告不另写入原始响应。依据：[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)。

### 响应长度（2026-09-19）

存在 Content-Length 时，读到的字节数须一致；不足视为可重试读取中断，超过则拒绝为 malformed_response。无长度头时仍受响应体大小上限与 JSON 准入约束。已用标准库 HTTPResponse 的截断消息做离线回归，不代表默认 opener 或真实 HTTPS 网络已验收。

### 修订日期查询范围（2026-09-19）

`vintages --start/--end` 映射到 realtime_start/end。显式边界必须由响应顶层原样回显，返回日期不得越过请求闭区间；只指定一侧时只绑定该侧。允许空结果、边界当天及倒序结果，不额外推断未指定边界。异常在成功 capture 前以 malformed_response 拒绝。依据：[vintagedates](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html)。这是请求/响应范围核验，不证明修订历史完整或来源内容真实。

### 默认 HTTPS 路径验收（2026-09-19）

默认 urllib opener 已通过当前 Python/macOS 的本地 TLS 服务验证：同主机跳转成功，跨主机与 HTTPS 降级在目标访问前拒绝；503、最终响应截断和跳转响应截断有界重试，400 不重试。跳转响应体单独有界读取，301/302/303/307/308 复用标准库跳转策略并在异常时关闭原响应。极端 JSON 指数导致的 Decimal InvalidOperation 转为 malformed_response。测试采用临时自签证书与进程内临时 CA 信任，不更改系统信任或用户凭据；不等于真实 FRED/ALFRED 连通性验收。
