# 编辑承诺 v0.1 完整原始档案

运行：`20261021-edit-commitment-v01`；运行代码：`6d6e36851479bae6d5a0e0276fb448a537cfa970`。

服务器 `runs/edit-commitment/20261021-edit-commitment-v01` 的全部 **217 个原文件**逐字节复制。文件清单与哈希见 [manifest.json](manifest.json)，原文件树 SHA-256 为 `88f518db634e050c4f51a616d66845ff3bd3849c845c3f9f02e4b4f8c0fd147d`。此 README 和 manifest 是归档时新增的索引，不计入217原文件。

- [summary.json](summary.json)：12 次请求、4 草稿、8 终稿和全部结果分配。
- [draft-freeze.json](draft-freeze.json)：所有草稿先冻结，没有草稿执行成绩。
- [feedback-freeze.json](feedback-freeze.json)：冻结后计算的声明检查。
- [预算账本](budget-ledger.json)与[执行账本](execution-ledger.json)：模型和任务执行分开计数。
- [P-format 草稿](drafts/P-format/draft.py)、[self 终稿](reviews/P-format-self/candidate.py)、[checked 终稿](reviews/P-format-checked/candidate.py)：可直接看到真实修补与改声明的区别。
- [P-format self 提交及核对](reviews/P-format-self/final-commitment.json)、[checked 提交及核对](reviews/P-format-checked/final-commitment.json)：同时保存原声明与最终声明的履行情况。

每个会话文件夹保存实际请求/响应、SDK 接收字段、源码、理由及控制器记录；终稿文件夹还保存所有任务评价。未挑选成功案例，未修改末尾换行等原始字节。

解释入口：[操作说明](../../../../docs/operations/edit-commitment.md)、[逐例结果](../../../../docs/analysis/2026-10-21-edit-commitment-results.md)。四个基准状态均研究者已见，新增草稿不等于新增独立任务。没有持久策略 S 更新或跨任务泛化结论。
