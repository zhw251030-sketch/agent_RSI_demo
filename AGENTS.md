# 项目协作约定

先读 README.md、STATUS.md 和最新联合设计。当前用户要求优先于历史稿。重要判断应核查原始论文、官方代码或实际日志，不能仅凭对话记忆推断。

- 当前研究为固定基础 LLM 权重下的形式规划与符号发现；开发子集已固定运行；正式机制、独立选择/评价子集和协议尚未冻结。
- 当前服务器数据为 Spanner（400 问题+域文件）与 LLM-SR 原始四任务（12 CSV，先用 oscillator1/2）。后者按用户要求替代受限 LLM-SRBench，输出在最后一列；看 docs/operations/task-data.md 和最新 symbolic-public-data 协议。旧 phys_osc 清单保留作历史，不继续作为当前下载目标。
- vendor/ 与 data/ 不直接挂载给候选进程；上游源码含参考解与缓存。rsi_eval 的候选执行已有 Bubblewrap/seccomp 隔离与资源限制，v0.2运行前247项不同测试通过；受控研究 Agent 仅有 submit_candidate/finish，已完成首轮开发小试，不可直接读取整个项目。已有一次诊断开发对照的部分结果，尚无完整独立机制对照。
- 官方 Canvas 1.28.1 已部署；`scripts/canvas.py` 管理网页服务，状态与依赖分别在被忽略的 `.canvas-state/`、`.canvas-runtime/`。网页后端的 SDK 1.56.0 与实验 `.venv` 1.55.1 分开；不要因网页版本改变实验依赖。入口通过 SSH 隧道访问回环 18080；MiniMax-M3 已配置；详见 docs/operations/minimax.md。
- 服务器 `.venv` 为 OpenHands SDK/tools 1.55.1，`.task-runtime/python` 独立提供系统 Python 3.10 的 NumPy 1.26.4/SciPy 1.13.1。两套开发执行器及 SDK 专用工具已通过离线往返；看 docs/operations/task-executors.md。普通 TerminalExecutor 和现有 Canvas 通用会话仍不具备本执行器的受控数据边界。
- 区分研究建议、静态核查、部署、运行和结果。没有实验就不能填写性能或简历成果。
- 历史研究快照保留原日期与内容；新结论另建带日期/版本的文档并更新入口。
- 用户已要求在工作过程中同步到这个私有 GitHub 仓库。每个有意义的工作单元完成后，检查 diff 与敏感内容，提交并推送，报告同步结果；无需反复请求相同授权。纯问答无文件变化时不创建空提交。
- 开始修改前检查本地、远端和服务器 Git 状态；只快进同步，不自动 force push、reset --hard 或覆盖另一处未提交修改。
- 不提交 .env、私钥、令牌、主机地址、个人申报材料、受限数据、虚拟环境、大型模型或未脱敏的原始运行日志。配置以不含密钥的模板提交。
- 后续代码、配置模板、任务清单、评价协议和经过检查的结果摘要在此仓库维护；上级文献工作区保留导航和历史来源，不自动整库上传。
- 服务器使用同一 Git 历史。未核验服务器 GitHub 认证时，通过本机的已认证 Git 和 SSH 传输提交，不复制私人密钥。
- 用户已明确授权复用指定 MiniMax-M3 凭据并完成连接配置；这不自动授权申请受限数据或启动正式实验。人民币 300 元项目预算仍有效。首轮小试 ledger 限定 8 请求/每会话4、3候选/每会话、5元保守预留；不控制账户或其他进程花费。失败与恢复共用原 ledger，不重置预算；首轮额度已耗尽。后续诊断对照另设 24 请求/每会话4、3候选/每会话、10元预留，实际11请求后因输入超过96KiB停止，后三组未启动。该轮协议无恢复入口，不能事后放宽上限或补跑来改写同一轮；未来新版本需明确范围与预算。

- 实验依赖 LiteLLM 固定 1.105.1，不能无检查升级到 1.106+（与 MCP 1.x 冲突）。configs/models/minimax-m3.json 不含密钥；config.local.json 仅记录服务器密钥来源路径且不提交。源密钥轮换后重新运行配置脚本更新 Canvas 的加密副本。

- 最新真实小试见 docs/operations/agent-pilot.md、docs/environment/2026-10-20-agent-pilot-verification.json 和 artifacts/pilot/2026-10-20/。固定策略 S，改动的是程序/公式 P；模型自述不等于实测失败归因，训练误差不等于泛化。原始运行与请求日志留在被忽略的 runs/，审阅快照保留全部候选。

- 最新诊断开发对照见 docs/operations/diagnostic-comparison.md 与对应核验/轨迹分析。planning_A 10/10、planning_B 0/10、symbolic_C NMSE0.09577；其余三个会话未启动，不能把初始分数当方法结果。候选修补属于人工干预，不计入模型成果；证据引用不等于推断成立。这些是上一轮历史结果，最新检查轮见下项。

- 最新继续工作见 docs/operations/checked-feedback.md、docs/analysis/2026-10-20-checked-feedback-v02-analysis.md 和对应verification。已完成全请求摘要与窄范围主张/事前预测检查。v0.1因SDK审查缺陷8请求后停止；修复轮v0.2在e298713运行13请求，6个实际执行的新候选，12主张(8支持4格式错)、6预测(4支持2矛盾)。planning_checked首个候选即10/10，不能归因于后续反馈；symbolic_hidden无真实工具调用但SDK结束，0候选不能给方法分数。两轮21请求估算0.545706元、预留2.1317184元，均不可恢复或改旧日志；事后响应契约防护未用于产生v0.2结果。下一步先离线稳定接口/证据绑定，再固定修订状态做配对；无S更新、无封存集评分、无新方法或泛化结论。
