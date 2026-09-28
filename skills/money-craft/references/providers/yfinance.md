# yfinance 港美股 Provider

官方项目与 API 参考：

- https://pypi.org/project/yfinance/
- https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html
- https://ranaroussi.github.io/yfinance/reference/api/yfinance.Search.html

Money Craft 将 `yfinance==1.7.0` 作为可选的港股和美股二级数据适配器。它不属于核心标准库运行时，也不替代 SEC、港交所、发行人 IR、法定财报或其他正式披露。PyPI 页面明确说明：yfinance 与 Yahoo 无隶属或背书关系，使用公开 API，面向研究和教育用途；Yahoo Finance 数据的实际使用权需服从 Yahoo 条款，接口面向 personal use（个人使用）。不得将它当成可自由再分发的数据授权。

在专用 Python 环境中安装：

```bash
MONEY_CRAFT_DATA_HOME="${MONEY_CRAFT_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/money-craft}"
python3 -m venv "$MONEY_CRAFT_DATA_HOME/venvs/data"
"$MONEY_CRAFT_DATA_HOME/venvs/data/bin/python" -m pip install \
  -r "$MONEY_CRAFT_SKILL_DIR/requirements-yfinance.txt"
"$MONEY_CRAFT_DATA_HOME/venvs/data/bin/python" \
  "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" doctor --json
```

不要因为当前宿主的系统 Python 未安装 yfinance 就改写全局环境；使用同一专用解释器执行 `research plan/init/collect`。`doctor` 只检查包是否可导入和版本，不联网。

系统 `python3` 启动 Money Craft 主入口时，只要首选数据环境存在，入口会透明切换到 `~/.local/share/money-craft/venvs/data/bin/python`；在报告 venv 或其他显式受控解释器中运行时不会抢占解释器。旧 `~/.config/money-craft/data-venv/bin/python` 仅在新环境不存在且未显式覆盖数据根时作为迁移兼容回退。可用 `MONEY_CRAFT_DATA_HOME`、`XDG_DATA_HOME` 或 `MONEY_CRAFT_DATA_PYTHON` 选择受控位置，不要恢复 cwd 搜索或全局安装。共享 XDG、显式 dotenv、Provider gap 和当前来源边界见 [财务数据与证据](../financial-data-and-evidence.md)。

## 身份映射

Money Craft 的 `security_id` 仍是研究身份真源，Yahoo symbol 只是 Provider identifier：

| `security_id` | yfinance symbol | 规则 |
|---|---|---|
| `HK:00700` | `0700.HK` | 去除多余前导零后至少保留四位，并追加 `.HK` |
| `US-NASDAQ:NVDA` | `NVDA` | 美股使用 ticker；类别股的 `.` 转为 Yahoo 的 `-` |
| `US-NYSE:BRK.B` | `BRK-B` | 只改变 Provider identifier，不改 canonical identity |

检索必须唯一命中该 Provider symbol；返回币种若与计划基础币种冲突，或资产类型不是 equity/stock，采集失败。公司法定名称、share class、财政期和证券权利仍以交易所、监管披露和发行人文件确认。

## 有界能力

使用 `--provider yfinance`：

| CLI | yfinance 调用 | 约束 |
|---|---|---|
| `data search` | `Search(...).quotes` | 只作 symbol 消歧，不采纳新闻或研究报告 |
| `data snapshot` | `Ticker.fast_info` | 行情/市值为二级快照；允许缺失字段 |
| `data history` | `Ticker.history` | 当前只开放 `1d`、最长 10 年；`auto` 为 yfinance 自动调整，Money Craft 的 inclusive end 会转换为 yfinance exclusive end + 1 日 |
| `data valuations` | `Ticker.get_valuation_measures` | 固定季度频率、当前值加最多 5 个期间 |
| `data financials` | `get_income_stmt` / `get_balance_sheet` / `get_cash_flow` | 年度或季度，最多保留请求的列数；字段、币种和财政期必须与正式报告对账 |
| `data corporate-actions` | `Ticker.get_actions` | 本地按日期过滤；只作拆股/分红交叉核对 |

`calendar`、Fuyao `indicators`、盘中流式行情、期权、分析师评级、新闻、筛选器和自动交易不在本适配器范围内。接口存在不等于 Money Craft 应暴露。

## 输出与证据边界

yfinance 返回 pandas 对象而不是稳定的 REST wire envelope。Money Craft 将表格转成 `index + columns + rows` 的版本化 `money-craft.yfinance-adapter-export.v1`，Decimal 字符串化后写入私有 capture；该文件必须标为 `adapter-export`，不得谎称 Yahoo 原始 HTTP 响应。

所有 yfinance normalized response、adapter export 和 capture receipt 只保存在 repo 外或已忽略的 `local/evidence/`。公开产物只能包含来源元数据、哈希、派生计算和正式披露链接，不分发抓取的数据集。缺字段、空表、限流、接口变化或标的冲突都形成 Provider gap；不能用旧缓存或模型记忆补齐。

## 缺失数据准入（2026-09-19）

search 每条结果须为对象且有非空字符串 symbol，不静默丢弃坏行。snapshot 的行情/市值/股数等字段至少一个非缺失，只有 currency/exchange 等元信息不算行情数据；history、valuations、financials 至少一个非缺失单元格。完全缺失返回 transient_provider_error，最多三次尝试，失败不写成功 capture。非有限 Decimal 与 float 均归缺失，零值保留；其他字段仍允许缺失。

空 corporate-actions 仍允许成功，表示该次结果没有事件；不能由此证明上游没有漏数。此轮只核验缺失和搜索身份形态，非缺失不代表数值类型、表格维度、日期范围、单位或证券真实身份已经校验；这些另待审。

## 表格位置与维度（2026-09-19）

导出直接按原始 itertuples 位置读取，不再用标签列表经 loc 重选，以免重复标签导致行列扩增或取错值。每行宽度先与完整 columns 比较，行数与 index 比较，通过后再按请求限制列数；不靠切片隐藏维度错误。重复标签原样保留，表示位置数组，不宣称标签唯一。空轴也保持 index/columns/rows 对齐；必需表仍受全缺失准入约束。此轮为表接口离线夹具验证，当前验证环境未安装 pandas，真实 pandas 对象行为仍须另验；数值类型和日期范围未因维度通过而视为已验证。

零列且非空 index 的 pandas 表在 index=False 时不产生 tuple；导出按 index 位置保留空行，避免将合法空数据错判为结构损坏。已按本地 pandas 源码提取行为复核；旧数据运行环境解释器链接失效，仍不视作完整 pandas runtime 验收。

## 快照数值类型（2026-09-19）

snapshot 的价格、市值与股数字段在 scalar 归一化后只接受非 bool 的 int/有限 Decimal 或缺失；不把字符串数字、布尔值、列表/对象转成行情数字。非法字段整条拒绝为不可重试 malformed_response，诊断只含字段名不回显异常值。浮点数归 Decimal、非有限值归缺失、零值保留沿用现有规则。此处不检查价格/市值/股数之间的关系、正负范围或币种，财报及历史表数值类型另待审。

## 表内数值类型（2026-09-19）

历史行情、估值、财报和公司行动使用的表导出，在 scalar 归一化后逐单元格检查：数值列只接受非 bool 的 int/有限 Decimal 或缺失。字符串数字、日期对象、布尔值与容器不作为表内金融数值；标签仍独立保留，不对行列标签应用此检查。先检查完整行，再限制输出列数，不用截列掩盖异常值。有限小数精度、负值、零值和现有缺失规则保留。此处未建立真实 pandas 的 NA/NaT 全部类型覆盖，也不证明日期范围、单位或数值间关系。

固定版本 yfinance 1.7.0 的 corporate-actions 包含 `Dividends FX` 币种列；仅此操作的此列明确允许字符串（含空字符串）或缺失，原样保留。其它操作与数值列不因此允许字符串。该例外依据本地固定版本 get_actions 源码及离线回归，不把币种文本存在当作币种语义已验证。

## 历史与公司行动日期（2026-09-19）

日线 history 的 index 须为规范 YYYY-MM-DD 或完整可解析 ISO 时间戳，且逐项落在请求 start/end 闭区间内；越界拒绝，不静默裁掉。时间戳按其自身日历日期比较，不转 UTC 改变市场日期；这不证明其时区与交易所时区匹配。

corporate-actions 返回全历史再本地过滤，所以先校验全部 index 日期（未指定范围也校验），再保留闭区间日期；坏日期不因位于过滤范围外而隐去。缺少可过滤表接口时明确失败。空表沿用已有准入语义。财报期间标签、交易日完整性、重复日线、时区真实性和真实 pandas 运行另待验。

## 真实 pandas 缺失值与导出验收（2026-09-19）

在独立临时环境 Python 3.14.7、yfinance 1.7.0、pandas 3.0.6 上，以真实 DataFrame 验证重复标签、零列、可空 Int64、时区 index 和可空分红币种；不请求 Yahoo 数据。`pd.NA` 与 `pd.NaT` 按已加载 pandas 的单例身份转为 None，避免导出字面量 `<NA>`/`NaT`。缺失日期 index 仍拒绝；普通同名字符串不被视为缺失。导出保留 JSON null、数值零及既有 Decimal 字符串精度合同。

这补充了先前仅夹具/源码提取的证据，不修复原数据环境失效的 Python 链接，也不证明真实 Provider、所有 pandas 版本或所有 dtype 已兼容。

## 超时分类（2026-09-19）

固定依赖 curl_cffi 的 ConnectTimeout、ReadTimeout 与 Python TimeoutError 纳入现有三次尝试和0.5/1秒退避；不以异常继承自 ConnectionError 为由将 SSLError 等证书失败全部当暂时故障。按实际依赖异常对象离线验证，未执行真实网络故障注入；三次限制不代表总耗时上限。

## 导出失败边界（2026-09-19）

adapter-export 必须可编码为 UTF-8 JSON；孤立 Unicode surrogate 等序列化/编码失败转换为不可重试 malformed_response，错误文本不回显损坏内容，不创建成功 capture。JSON 编码显式禁止非有限裸数值；不通过 ASCII 转义将损坏文本留给后续 CLI。

## CLI 退出码（2026-09-19）

yfinance 缺少可选依赖属于配置问题，CLI 返回 3；malformed_response 返回 6；可重试故障返回 5；其余Provider故障返回4。保留JSON error.kind/retryable及无成功capture行为。此前日期越界和损坏Unicode回执中记载的退出码4属于旧映射，新版本同类格式错误使用6；历史回执不回写。

## 本地缓存锁冲突

多进程同时初始化 yfinance 的 SQLite 缓存可能返回 `OperationalError: database is locked`。适配器仅对这一消息和 `database table is locked` 按既有上限重试三次，间隔0.5/1秒；耗尽仍返回 transient_provider_error，不写成功capture。其他数据库错误不自动重试，不删除缓存或cookie来掩盖失败。
