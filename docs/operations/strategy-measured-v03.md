# 单步工具修复与 measured-v03 操作说明

本轮完成接口修复后冻结实现 `0065d8c`，完成同版本的完整模拟，再独立启动 `measured-v03`。真实轮已于北京时间 2026-10-22 完成 36 请求和 716 条测量，终态审计 passed_complete；r1 保留 S0，r2 晋升新策略，后续四对有两项收益、两项持平。完整解释见[结果报告](../analysis/2026-10-21-strategy-measured-v03-results.md)，机器证据见[核验文件](../environment/2026-10-21-strategy-measured-v03-verification.json)。

上一轮第七个响应同时返回 `submit_candidate` 和 `finish`。这仍只有一份业务候选，但接收器要求整个响应只有一个工具调用。我们公布了一个单步流程不需要的结束工具，造成提示、工具表与接收规则之间的歧义。

本轮在 `rsi_eval/strategy_pair_agent.py` 使用 OpenHands SDK 1.55.1 的 `include_default_tools=[]`：策略提案仅公布 `submit_policy`，候选修订仅公布 `submit_candidate`；系统提示明确要求一次业务调用，由宿主结束步骤。请求捕获和发送前也核对单工具表，保持 `tool_choice=None`。原始响应仍严格拒绝 finish、两项调用、错误工具及非法元数据，不能先接受候选再忽略其余调用。

新接口标识为 `strategy-pair-agent-v0.2`。`rsi_eval/strategy_pair_audit.py` 默认由宿主要求这一版本，同时核对发送记录、SDK 事件、接受凭据和源码。旧双工具记录只有调用者明确指定历史 v0.1 时才能只读回放；不能通过修改记录中的版本字段自行降级。共用旧执行器、模型权重、学习包、规则目录和任务划分保持冻结。

验证分三层。`tests/test_strategy_single_tool.py` 先在旧代码上复现失败，再验证策略提案和候选提交接口的合法接受与非法提交零部分接受；原第七响应仍拒绝，不追认。整组 199 个不同相关测试在服务器全部通过，本机 175 通过、24 项因依赖环境跳过。随后 `sdk-preflight-v03` 使用实际 SDK、假 provider 和人工测量完成 36 个位置、716 条记录、2 次选择回放，审计为 `passed_complete`；最大请求预算为 89,856 字节，低于 98,304 上限。模拟调用与人工成绩不计研究请求、费用或机制效果；readiness 只认证同一运行版本的已覆盖流程。

在服务器工作目录 `/home/hanwen/Project/project/agent_RSI_demo`，运行期间可只读查看计数：

```bash
.venv/bin/python tmp/strategy_v03_progress.py measured-v03
```

该脚本读取账本和事件，显示已预留/结算请求、测量数、已冻结策略数与最后事件；运行结束后才显示最终状态和费用估算。一次快照不是完整审计。原始记录分别保存在 `budget-ledger.json`、`experiment/events/` 和 `experiment/sessions/<slot>/requests/`；终态以运行目录的 `result.json`、`audit.json` 和 `experiment/summary.json` 为准。

运行完成或停止、上述终态文件已生成后，可核对记录而不重新调用模型或执行候选：

```bash
.venv/bin/python tmp/replay_strategy_v03.py measured-v03
```

回放检查原文件哈希、请求/用量绑定、准备包和阶段审计，只将报告写入 `tmp/strategy-measured-v03-replay.json`。它依赖当前仍与冻结清单一致的运行文件；不能把哈希不一致当成继续运行的理由。

本轮采用新目录、新账本，每位置一次，180 秒、零重试，最多 36 请求，保守费用预留上限 12 元。先完成策略提案与选择，两个 S* 都冻结后才开放后续评价基线与评分。异常停止后保留已发生记录，不补抽、不继续旧轮，不追加另一真实后继轮。`measured-v01/v02` 均保持停止，历史失败解释不加入学习包。本轮已结束，不重新启动该 run-id 或追加模型请求。工程验收通过和本次正向配对不等于稳定策略优势或普适性成立。

## 归档与离线查看

[真实档案](../../artifacts/strategy-measured/2026-10-21/v03/README.md)的 raw/ 保存请求、响应、源码、选择决定与终态；executions/ 保存 716 次任务执行记录；verification/ 保存分析脚本、双端回放与只读核查。manifest.json 提供原路径映射与哈希。原路径未改写，因此从全新克隆回放时，须先按清单恢复被忽略的 runs/ 原文件，不能覆盖内容不同的已有文件。当前本机与服务器已保留原目录，文中的 tmp 回放脚本也已存在。

[模拟档案](../../artifacts/strategy-pair/2026-10-21/sdk-preflight-v03/README.md)与真实档案分开。检查这些文件无需模型密钥，不会新增付费调用。源码核对使用解析或文本比较，不能直接把候选当宿主代码执行。

原 SSH 通道在终态完成后滞留，已核实服务器实验进程不存在再关闭对应本机客户端。客户端退出码 1 是连接清理的结果；真实 CLI 退出码未恢复。完成状态以终态及双端回放为准，清理后原始文件仍逐字节相同。
