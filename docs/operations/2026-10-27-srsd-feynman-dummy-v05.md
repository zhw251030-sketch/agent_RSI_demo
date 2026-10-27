# SRSD-Feynman Easy-Dummy v05 操作记录

本轮先同步 `f0159a88` 的 Dummy 数据/协议脚本，再执行下载、train-only manifest、自然域报告和 FakeProvider 预演。Fake 证书确认 4 个槽、12 条 gate、0 次真实模型调用后，才用 real mode 发送 4 次 MiniMax-M3 请求。真实候选在 val 上回放并由固定双门槛决定动作；test 在 val action 写入后才一次性读取。

关键文件：

- `docs/environment/2026-10-27-srsd-feynman-dummy-source.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-dev-v05.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-val-domain-v05.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-v05-preflight.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-real-v01-verification.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-real-v01-val-replay.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-real-v01-test-holdout.json`

运行目录 `runs/` 和原始数据按仓库忽略规则保留在服务器，不通过 Git 提交；可用上述报告中的 SHA-256 与运行摘要复核。Dummy holdout 允许 0 个部署动作；如果未来某轮出现超过 1 个 allow，脚本会在读取 test 前停止，避免把多重部署混入一次性描述性复核。
