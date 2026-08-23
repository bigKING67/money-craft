# 投资论文跟踪工作流

公司跟踪层位于该公司所有日期研究目录的同级，而不是某一次研究日期内部：

```text
<money-root>/
└── <ticker>-<company>/
    ├── <YYYY-MM-DD>/revisions/rNNNN/  # 某次正式研究档案
    └── tracking/
        ├── current.json               # 可变指针
        ├── .working/<run-id>/         # 单次可编辑跟踪工作区
        └── revisions/tNNNN/           # 只读、哈希绑定的论文跟踪历史
```

## 创建工作区

第一次建立跟踪层时显式绑定一份已通过审计的旧论文：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track init \
  --tracking-root <company-dir>/tracking \
  --previous <audited-thesis.md> \
  --source-revision <formal-revision-dir-or-REVISION.json> \
  --as-of <YYYY-MM-DD> --json
```

后续更新可以省略 `--previous`；命令从 `tracking/current.json` 解析上一版论文。`--source-revision` 是可选的正式研究档案绑定，不会复制原始证据。

`track init` 离线且不调用模型。它生成不可改写的 `previous-thesis.md`、`update-plan.json`、`run-state.json`，以及需要研究者或 Agent 根据新证据完成的 `thesis.md`、`card.md`、`state.json`。未完成的 `{{...}}` 占位符会阻断准出。

## 完成与封存

在工作区内完成三份可编辑文件后运行：

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track check \
  --workspace <track-init-returned-workspace> --json
```

`track check` 会验证：

1. 旧论文和更新计划仍与初始化回执一致。
2. 新论文同时通过 report 和 financial audit。
3. 证券身份、时间、数据截止时间和历史更新记录满足 append-only 合同。
4. `state.json` 的假设、红线和健康度与论文逐项一致。
5. `card.md`、`state.json` 不再有占位符。

全部通过后，命令在锁内原子创建下一版 `revisions/tNNNN/`，写入 `TRACKING.json` 和 `SHA256SUMS`，将 revision 文件与目录改为只读，再原子切换 `current.json`。只有成功切换指针后，才清理工具自己创建的 `.working/<run-id>/`。

健康度公式固定为：

```text
max(1, 10 - BROKEN*3 - DAMAGED*2 - WEAKENED*1 - TRIGGERED_RED_LINE*5)
```

该分数与 diff signal 只表示研究复核优先级，不是买卖信号。

## 读取与离线验证

```bash
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track status \
  --tracking-root <company-dir>/tracking --json
python3 "$MONEY_CRAFT_SKILL_DIR/scripts/money_craft.py" track verify \
  --tracking-root <company-dir>/tracking --json
```

`status` 只读取当前指针、revision 列表和未完成工作区。`verify` 重算文件哈希、审计结果、状态映射和 current 指针，并默认要求所有 `tNNNN` 文件与目录不可写。两者都不联网、不读取账户、不执行交易。

## 触发路由

- 价格越过已有估值边界，但没有新经营证据：只刷新估值，不自动改写核心论文。
- 新定期报告：先做 earnings review，再执行 `track init -> 填写 -> track check`。
- 任一红线变为 `TRIGGERED`、核心假设变为 `BROKEN`、关键来源冲突改变估值或结论，或发生重大并购、减值、融资、治理、资本配置事件：升级为完整公司研究。

Provider 原始响应、正式报告和浏览器抓取仍属于私有证据层，不进入 tracking revision；revision 只保存论文、跟踪卡、状态、差异、审计和哈希清单。
