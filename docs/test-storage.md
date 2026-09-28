# 本地测试与资料存储

研究报告、来源 PDF/音频、case、manifest 和验收回执是资料；venv、依赖缓存和
临时渲染文件是执行环境。不要将整个 `local/` 或某次验收工作区作为缓存删除。

## 新验收任务使用临时环境

在仓库根目录运行，输出目录必须尚不存在：

```bash
python3 scripts/test_environment.py --runtime report \
  --output-dir local/acceptance/report-storage-check -- \
  '{python}' scripts/report_smoke.py
```

`report` 根据 `requirements-report.txt` 创建临时 venv 并安装依赖；`data` 使用
`requirements-yfinance.txt`。安装会联网，版本范围沿用现有 requirements，不声称
锁定版本的完全复现。`empty` 只创建 venv；默认 `none` 使用当前解释器，不安装依赖。
日常反复开发继续复用已有用户专用环境，无须每次新建或下载。

被运行的命令通过 `MONEY_CRAFT_TEST_OUTPUT` 或参数中的 `{output}` 获取永久输出目录，
通过 `{python}` 使用选定解释器。需要留下的报告/来源/结果必须写到该输出目录。
包装器不自动复制研究资料，也不是文件系统沙箱，不能阻止命令主动写其他位置。

包装器将 `MONEY_CRAFT_DATA_HOME`、`MONEY_CRAFT_CACHE_HOME`、pip 缓存和 `TMPDIR`
指向本次系统临时目录。成功、非零退出、超时、SIGINT/SIGTERM 都会先停止命令的
进程组，再清理临时目录。默认总时限 900 秒，包含安装，可用 `--timeout` 调整。
不允许任务用 daemon/新会话脱离受管理进程组。SIGKILL、断电、宿主崩溃无法保证收尾；
残留需先核对运行情况，不能按前缀批量删除。目前支持 macOS/Linux。

输出目录保留 `test-environment-receipt.json`，只记录退出状态、环境清理结果等，
不记录参数、环境变量或原始日志。`COMMAND_SUCCEEDED` 仅代表进程成功，
不表示研究或验收语义通过。stdout/stderr 继续由调用方/CI 管理。

报告 CI 已使用此入口，测试断言与 report smoke 保持不变。其他已有 smoke 使用
`TemporaryDirectory`，不再重复增加清理层。手工验收需使用此入口才有这些保证；
已有用户 venv、已安装 Skill 和历史研究归档不受影响。

## 只读盘点与历史保留

```bash
python3 scripts/storage_check.py
```

统计 `local/` 各类别占用，不跟随目录符号链接；只将 `skill-evals/` 和
`acceptance/` 中名称日期超过 30 天的目录列为人工复核项。日期不代表最后使用时间，
复核项不等于可删除项。研究目录不参与按时间列候选。

- 正式报告、关键来源和正式验收结论继续保留。
- 旧调试资料先核对文档/验收引用，再确定精确清理范围。
- 运行中任务、`.keep`、未知目录应保留；此工具不提供历史自动删除。
- 不根据 `pyvenv.cfg` 扫描并删除存量环境；只清理由新入口本次创建的临时目录。
- 不增加后台服务，不改 Pi 的打包保留机制或 Server 编译缓存策略。
