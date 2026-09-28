# yfinance 有界审查范围

2026-09-19。范围为 yfinance_adapter.py 全文及其直接 CLI 参数/错误映射；普通独立审查，无 canonical 全仓评分。

| 范围 | 处置 |
| --- | --- |
| 可选依赖与版本化导出 | KEEP：核心无强制 pandas 导入，导出保留 Provider/版本/参数与 Decimal 精度；真实 pandas 缺失单例归 null。 |
| search与snapshot | KEEP：坏搜索行整批拒绝，快照类型/缺失准入；请求 symbol 回填不等于独立证券身份验证。 |
| 表格 | KEEP：按位置导出，先验完整维度/类型再截列；公司行动币种列显式文本例外。 |
| 日期 | KEEP：历史闭区间拒绝越界；公司行动先验再过滤，按时间戳自身日历日比较。 |
| 错误重试 | FIX：补连接超时与builtin TimeoutError；证书和数据格式错误不重试。最多三次不等于总耗时上限。 |
| 序列化 | FIX：UTF-8 JSON失败结构化，损坏Unicode不逃逸CLI；不输出损坏内容。 |

验证使用真实 pandas 3.0.6、NumPy 2.5.3、yfinance 1.7.0 与 Python 3.14.7 的临时环境；Provider 返回由离线夹具控制，不请求 Yahoo。原用户 data venv 的失效 Python 链接未修复。

非空表不证明数据真实完整，研究层仍需证券/币种对账与正式披露。未验证真实网络、交易日完整性、重复日线、交易所时区真实性、财报标签经济语义、全部 dtype/依赖版本及跨平台。未提供交易、账户、自动缓存回填或通用数据修复能力。

最终源码hash、独立复核和状态以[收口回执](../acceptance/yfinance-closeout-review-20260919.json)为准。
