# 冷启动来源生成：中止轮原始归档

运行版本 `cb40fee10a6f1f589328f8e3f8cbcc926b644c0d`，run ID `20261021-state-generation-v01`。计划8槽，实际发出3请求。第三槽P-eval-1发生HTTP408/LLMTimeoutError，用量未知，按冻结规则停止。两份源码已保存，其余一槽失败、五槽未开始；不恢复、不补抽。

43份原始文件从服务器逐字节复制，[manifest.json](manifest.json)记录文件与整树SHA256。README与manifest是归档附加说明，不计入原始43份。

- [输入冻结](input-freeze.json)：完整8槽分配、匿名任务包、公开来源与配置绑定。
- [源码冻结](source-freeze.json)：停止后冻结的34份会话记录、全部槽位状态。
- [运行汇总](summary.json)与[预算账本](budget-ledger.json)：包括未知usage，不能把已知费用当实际总账单。
- [规划源码](sessions/P-select-1/source.py)与[符号源码](sessions/S-select-1/source.py)：模型实际工具提交，未执行、未拟合。
- [第三槽错误](sessions/P-eval-1/session-summary.json)：保存错误类型与状态，不保存密钥或原始异常文本。
- [静态分析](static-analysis.json)：两份均语法可解析、入口匹配，与149个历史源码文件未发现字节或AST重复；不证明正确、适用或语义独立。

审计结果为 `record_consistent_incomplete`：[机器报告](../../../../docs/analysis/2026-10-21-state-generation-audit.json)。完整说明见[操作说明](../../../../docs/operations/state-generation.md)和[结果分析](../../../../docs/analysis/2026-10-21-state-generation-results.md)。AST哈希使用Python3.12，复核应使用服务器`.venv/bin/python`。
