# SRSD-Feynman Easy replication v05 操作记录

本轮先冻结 `i.12.5` 和 `i.14.3` 的 source/dev/val 报告，再执行 FakeProvider 预演。第一次 real-mode 启动被动态证书计数守卫拒绝，原因是复制脚本仍写死 Easy 轮的 6 请求/18 gate；守卫在第一请求前停止，没有模型调用。修复为按任务定义计算 4 请求/12 gate 后，重新生成 Fake 证书并完成 real-v01。

随后对真实候选做 val replay、real-round audit 和一次性 test holdout。test 读取发生在 val action 冻结后，所有报告保存对应的 source/dev/val/round 哈希。运行目录与原始数据仍按 `.gitignore` 保留在服务器；可提交复核的是 `docs/environment/2026-10-27-srsd-feynman-replication-*.json` 报告。
