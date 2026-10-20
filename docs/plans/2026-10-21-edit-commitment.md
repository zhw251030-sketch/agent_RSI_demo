# 编辑承诺与共享草稿对照实施计划

**目标：** 完成新协议的受控OpenHands流程、最小真实开发对照及可追溯审计。

**架构：** 新控制器保存草稿且零执行，冻结后生成静态反馈；新SDK动作承载必填枚举；新运行器分阶段预算/冻结，仅评价两臂终稿。复用旧数据装载、隔离执行和账本，不改历史模块或原档。

**协议：** [edit-commitment-v0.1](../protocols/2026-10-21-edit-commitment-v0.1.md)。两臂只差checker_feedback，4共享草稿/8复查，最大12请求、48sandbox、5元，无恢复。

- [ ] 控制器与检查投影：新增rsi_eval/commitment_core.py、tests/test_commitment_core.py，先失败测试，再验证不可执行草稿、承诺/源码绑定、unknown不挡评价与原承诺单列。
- [ ] SDK适配：新增rsi_eval/commitment_agent.py、tests/test_commitment_agent.py，验证严格动作、前置归档、固定工具与真实SDK假响应往返，无付费调用。
- [ ] 运行与审计：新增scripts/run_edit_commitment.py、scripts/analyze_edit_commitment.py及对应tests，测试全部草稿先冻结、输入配对、预算停止/缺失、原始响应/SDK参数绑定。
- [ ] 固定配置并独立审查。相关测试通过后提交实现、同步服务器，离线预检；运行一次新协议，不恢复或按结果补样。
- [ ] 双端审计与负例、完整原文件归档、中文结果/操作说明、项目状态更新及GitHub/服务器同步。
