# 固定基函数策略开发轮操作说明

本轮已结束。真实 measured-v01 第1次策略提案因4223字符辅助解释超过2000上限停止，0策略接受、0任务执行。不要重新运行该目录、继续其余12位置、修改原始响应或追认其中规则。见[结果解释](../analysis/2026-10-22-basis-trial-results.md)。

代码入口为 `extensions/basis_trial_v01/run.py`，实现7eeb4c0，执行前冻结提交d76a952。固定输入位于 `docs/experiments/basis-trial-v01-preparation/`，包含设计、完整旧学习包、提案提示和165文件冻结清单。

在服务器 `/home/hanwen/Project/project/agent_RSI_demo` 可执行只读核验：

```bash
.venv/bin/python -m extensions.basis_trial_v01.run verify --preparation docs/experiments/basis-trial-v01-preparation --output runs/basis-trial/measured-v01
.venv/bin/python analysis/basis-trial-v01/archive.py verify
.venv/bin/python -m unittest discover -s analysis/basis-trial-v01 -p test_failure.py -q
```

前者应返回 record_consistent_incomplete、1请求、0接受、0测量；该状态说明停止记录一致，不表示对照完成。后两项核对原文件归档和停止原因，不调用模型、不拟合。

从全新克隆回放时，按各 `artifacts/basis-trial/2026-10-22/*/manifest.json` 将raw文件恢复到其source相对路径；已存在且哈希不同的文件不能覆盖。归档中的SDK引用保留原runs路径，因此不应直接把artifact目录当作原运行目录传给verify。

实际SDK失败回放材料单独保存在failure-replay-v01，完整预演保存在sdk-preflight-v01；两者的usage和拟合计数都是模拟数据，不能计入累计研究费用。未将调试日志、凭据或真实CSV纳入仓库。

后继需要新的解释解耦契约、冻结版本、完整预演和新目录；当前v01冻结文件保持原样。真实凭据仍沿用已授权的服务器来源，不在运行命令或仓库中暴露。
