# 项目协作约定

先读 README.md、STATUS.md 和最新联合设计。当前用户要求优先于历史稿。重要判断应核查原始论文、官方代码或实际日志，不能仅凭对话记忆推断。

- 当前研究为固定基础 LLM 权重下的形式规划与符号发现；具体方法和任务子集尚未冻结。
- 当前服务器数据为 Spanner（400 问题+域文件）与 LLM-SR 原始四任务（12 CSV，先用 oscillator1/2）。后者按用户要求替代受限 LLM-SRBench，输出在最后一列；看 docs/operations/task-data.md 和最新 symbolic-public-data 协议。旧 phys_osc 清单保留作历史，不继续作为当前下载目标。
- vendor/ 与 data/ 不直接挂载给候选进程；上游源码含参考解与缓存。rsi_eval 的候选执行已有 Bubblewrap/seccomp 隔离与资源限制，43 项测试通过；后续研究 Agent 只配置受控评价工具，不可直接读取整个项目。当前无正式模型实验。
- 官方 Canvas 1.28.1 已部署；`scripts/canvas.py` 管理网页服务，状态与依赖分别在被忽略的 `.canvas-state/`、`.canvas-runtime/`。网页后端的 SDK 1.56.0 与实验 `.venv` 1.55.1 分开；不要因网页版本改变实验依赖。入口通过 SSH 隧道访问回环 18080；MiniMax-M3 已配置；详见 docs/operations/minimax.md。
- 服务器 `.venv` 为 OpenHands SDK/tools 1.55.1，`.task-runtime/python` 独立提供系统 Python 3.10 的 NumPy 1.26.4/SciPy 1.13.1。两套开发执行器及 SDK 专用工具已通过离线往返；看 docs/operations/task-executors.md。普通 TerminalExecutor 和现有 Canvas 通用会话仍不具备本执行器的受控数据边界。
- 区分研究建议、静态核查、部署、运行和结果。没有实验就不能填写性能或简历成果。
- 历史研究快照保留原日期与内容；新结论另建带日期/版本的文档并更新入口。
- 用户已要求在工作过程中同步到这个私有 GitHub 仓库。每个有意义的工作单元完成后，检查 diff 与敏感内容，提交并推送，报告同步结果；无需反复请求相同授权。纯问答无文件变化时不创建空提交。
- 开始修改前检查本地、远端和服务器 Git 状态；只快进同步，不自动 force push、reset --hard 或覆盖另一处未提交修改。
- 不提交 .env、私钥、令牌、主机地址、个人申报材料、受限数据、虚拟环境、大型模型或未脱敏的原始运行日志。配置以不含密钥的模板提交。
- 后续代码、配置模板、任务清单、评价协议和经过检查的结果摘要在此仓库维护；上级文献工作区保留导航和历史来源，不自动整库上传。
- 服务器使用同一 Git 历史。未核验服务器 GitHub 认证时，通过本机的已认证 Git 和 SSH 传输提交，不复制私人密钥。
- 用户已明确授权复用指定 MiniMax-M3 凭据并完成连接配置；这不自动授权申请受限数据或启动正式实验。人民币 300 元项目预算仍有效，目前没有自动硬限额。

- 实验依赖 LiteLLM 固定 1.105.1，不能无检查升级到 1.106+（与 MCP 1.x 冲突）。configs/models/minimax-m3.json 不含密钥；config.local.json 仅记录服务器密钥来源路径且不提交。源密钥轮换后重新运行配置脚本更新 Canvas 的加密副本。
