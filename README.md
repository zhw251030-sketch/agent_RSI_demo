# agent_RSI_demo

固定基础 LLM 权重，研究 Agent 如何利用执行反馈更新修订策略，并在**形式规划与符号发现**两个环境中检验同一更新机制。

**已完成诊断模块、168 项不同测试、旧候选离线干预和一次真实 A/B/C 开发对照尝试。规划 A 达到 10/10，规划 B 为 0/10；符号 C 最佳 train NMSE 0.09577。B 的第四次输入超预设上限 72 字节，后三组未启动，因此比较尚不完整，没有方法有效性或泛化结论。** 仓库名 RSI 不代表已实现策略自改写。

网页入口：完成本机 SSH 转发后打开 **http://127.0.0.1:18080/**。MiniMax-M3 已配置并通过两套 SDK 的工具往返检查。启动、访问和停止方式见 [网页使用说明](docs/operations/canvas.md)，实际结果见 [部署验收](docs/environment/2026-10-20-canvas-deployment.md)。

## 当前选择

| 层次 | 当前状态 |
|---|---|
| 研究路线 | 已选择形式规划与符号发现一起推进；基础 LLM 权重固定 |
| 规划任务 | Spanner 的 400 问题与域文件已下载到服务器，完整性检查和固定 prompt 的 VAL 验收通过；seed0 的 2/8/30 仍为准备稿 |
| 符号任务 | 按用户要求替换受限数据，已下载 LLM-SR 原论文四任务的 12 个 CSV（89,341 行），先用 oscillator1/2；结构检查通过，正式协议待冻结 |
| 更新对象 | 建议区分产物 P（程序/公式）与修订策略 S，重点检验策略对新搜索状态的作用 |
| 方法参照 | GEPA 式策略优化为共同候选，llm-genplan、LLM-SR、LaSR 等为任务参照；最终规则未选定 |
| Agent 框架 | OpenHands SDK/tools 1.55.1 已安装；MiniMax-M3 连接已验证；受控真实会话已运行；168 项不同测试通过，调用/候选/数据范围受限 |
| 任务执行层 | 规划解析/VAL 与符号拟合/评分已接通；Bubblewrap/seccomp 限制候选文件、网络、进程和资源；当前只开放开发反馈 |
| 交互网页 | Agent Canvas 1.28.1 已部署，工作区已选中；独立后端 SDK 1.56.0，MiniMax-M3 配置已启用 |

模型配置与验收：[MiniMax-M3 使用说明](docs/operations/minimax.md)。连接检查与开发小试分开计数。小试 8 次请求含 1 次服务错误，7 次有响应；费用仍有一笔未知用量，详见 [真实小试说明](docs/operations/agent-pilot.md)。

## 阅读入口

1. [项目状态与下一步](STATUS.md)
2. [形式规划与符号发现联合设计](docs/research/planning-symbolic-design-2026-10-17/形式规划与符号发现_联合研究设计_v0.1.md)
3. [研究资料及导入来源](docs/research/README.md)
4. [OpenHands 安装与检查结果](docs/environment/2026-10-20-setup-and-verification.md)
5. [两类任务的共用研究契约](docs/protocols/2026-10-20-shared-contract.md)
6. [GitHub 与服务器同步约定](docs/operations/git-sync.md)
7. [两类任务下载、替代选型与验收说明](docs/operations/task-data.md)
8. [当前符号数据接口：LLM-SR 公开原始任务](docs/protocols/2026-10-20-symbolic-public-data.md)
9. [任务执行器、隔离与 OpenHands 工具使用说明](docs/operations/task-executors.md)
10. [首轮真实 Agent 小试：操作、结果与限制](docs/operations/agent-pilot.md)
11. [首轮全部候选源码与开发成绩](artifacts/pilot/2026-10-20/README.md)
12. [最新诊断对照：操作、部分结果与下一步](docs/operations/diagnostic-comparison.md)
13. [诊断对照全部候选与反馈](artifacts/diagnostic-comparison/2026-10-20/README.md)
14. [观测、理由与代码逐条核对](docs/analysis/2026-10-20-diagnostic-comparison-analysis.md)

## 仓库边界

研究资料保留日期、来源链接与证据限制；较早稿件中的任务排序以当前联合设计和后续明确决定为准。新研究稿、实现、配置模板及经过检查的实验摘要在本仓库继续维护。论文全文、第三方源码镜像、受限数据、模型、虚拟环境、凭据和原始运行目录不直接纳入 Git。

当前包含文献比较、设计、安装证据、离线检查脚本和任务清单草案。安装环境、拿到数据、运行基线与验证新机制分别记录，不互相替代。
