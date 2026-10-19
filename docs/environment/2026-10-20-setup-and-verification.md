# OpenHands 安装、无模型验证与使用说明

完成日期：2026-10-20（Asia/Shanghai）。部署位置为指定 Linux 服务器的项目根目录，独立环境是 `.venv/`；本机 Windows 仓库保存版本文件和证据，不是另一个已安装的 Linux 环境。

## 已做的事与结果

| 工作 | 实际结果 | 为什么做 |
|---|---|---|
| 建立独立环境 | 基于已有 Python 3.12.14 创建项目 `.venv` | 避免改变系统 Python 和旧 conda 环境，便于回溯依赖 |
| 安装配套包 | openhands-sdk 与 openhands-tools 均为 1.55.1 | 官方将二者作为同版本配套发布；分开漂移可能造成导入不兼容 |
| 保存依赖状态 | 191 项安装依赖的版本及下载来源/哈希已记录 | 下次安装不靠当时的最新版本猜测本次环境 |
| 检查依赖 | `pip check` 返回 `No broken requirements found.` | 排除已声明的依赖约束冲突；不等于所有功能已验证 |
| 导入检查 | SDK 主要类型和终端工具导入通过 | 确认安装路径和运行时导入实际可用 |
| 正常工具执行 | 固定 Python 命令得到退出码 0，写入并读回 `sum=10`，工作目录正确 | 验证工具从命令到观察结果的完整路径 |
| 失败工具执行 | 固定失败命令返回退出码 7，无超时 | 后续实验必须保留失败信息，不能把所有结束都视为成功 |
| 模型使用 | 未构造 LLM 对象，模型调用和 Agent rollout 均为 0 | 本阶段先验证基础运行链，模型和计费继续后置 |

这里安装的是 **OpenHands SDK**。它适合由脚本编排、固定工具、保存轨迹并接入自定义执行器。本次没有启动 Agent Canvas 网页服务，也没有迁移旧 OpenHands 项目。

## 文件如何配合使用

- [直接依赖](../../requirements/openhands.in)：只写本项目明确选择的两个顶层包及固定版本。
- [完整版本清单](../../requirements/openhands-linux-py312.lock)：191 项实际安装版本，适用此次 Linux/Python 3.12 环境；不是跨平台锁文件，也不直接等价于 `--require-hashes` 安装。
- [安装来源记录](2026-10-20-installed-artifacts.json)：来自 pip 安装报告，保存官方包源、下载文件与 SHA-256。`func-timeout` 从官方源码归档构建了 wheel；记录源码哈希不等于证明构建完全可重现。
- [可重跑检查脚本](../../scripts/check_openhands_offline.py)：通过官方 TerminalExecutor 执行人工固定命令，不启动模型对话。
- [本次检查结果](2026-10-20-offline-check.json)：保存版本、脚本哈希、成功/失败退出码、文件结果和检查范围。JSON 时间是 UTC，对应本地日期 2026-10-20。

安装日志与原始 pip 报告保留在服务器 `tmp/install-2026-10-20/`，包缓存位于项目 `tmp/pip-cache/`，均被 Git 忽略。它们未混入提交；可审查的结果已单独导出。

## 如何复查或重建

在服务器项目根目录运行：

```bash
.venv/bin/python -m pip check
.venv/bin/python scripts/check_openhands_offline.py \
  --output tmp/openhands-offline-check.json
```

在新的兼容 Linux 环境中，可用已准备好的 Python 3.12 创建环境，再安装版本清单：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/openhands-linux-py312.lock
```

第二段是重建方式，不是已经在另一台机器验证的可移植性结论。不要在现有项目 `.venv` 上盲目覆盖重建。

脚本在导入前设置 `LITELLM_LOCAL_MODEL_COST_MAP=True`，使用 LiteLLM 包内的元数据，避免已知的导入时下载；当前 Python 进程的网络调用还由 audit hook 拒绝。本次未观察到该进程的网络尝试。该检查不覆盖任意子进程的网络能力，也不构成操作系统沙箱。

终端使用官方 subprocess 后端，无需 tmux；一个临时 shell wrapper 禁用常规个人 profile 和 bashrc，减少个人配置对检查的影响。工作结束后关闭终端并清理临时目录。

## 现在可以做什么，哪些还未就绪

已经可以在这个固定环境里继续开发任务适配与受控工具检查。后续的输入输出规范见[共用研究契约](../protocols/2026-10-20-shared-contract.md)、[规划接口](../protocols/2026-10-20-planning-interface.md)、[符号接口](../protocols/2026-10-20-symbolic-interface.md)。

尚不能称为完整 Agent/RSI 实验系统：未配置模型、未运行 Agent 对话；PDDL/VAL 和符号评价器未安装联调；LLM-SRBench 受限数据未取得；共同更新机制和正式评价协议尚未冻结。

此外，Python 虚拟环境只隔离依赖。当前 TerminalExecutor 直接以宿主账号运行，Docker 权限问题没有被本轮解决，模型生成程序的文件/网络/资源隔离也尚未实现。此次仅执行人工固定的检查脚本，不把成功结果推广成“可以安全执行任意生成代码”。

## 一手依据

- [OpenHands 官方安装说明](https://docs.openhands.dev/sdk/getting-started)：SDK/tools 配套安装，2026-10-20 核查。
- [SDK 1.55.1 发布记录](https://pypi.org/project/openhands-sdk/1.55.1/)与 [Tools 1.55.1 发布记录](https://pypi.org/project/openhands-tools/1.55.1/)：发行版与 Python 要求。
- [固定版本 TerminalExecutor 源码](https://github.com/OpenHands/software-agent-sdk/blob/v1.55.1/openhands-tools/openhands/tools/terminal/impl.py)：直接工具调用与关闭接口。官方 tag 对应 `5fa4dea24c52fe3ac53fa4e3e67a1376b72189e2`。
- [固定版本 subprocess 后端](https://github.com/OpenHands/software-agent-sdk/blob/v1.55.1/openhands-tools/openhands/tools/terminal/terminal/subprocess_terminal.py)：宿主进程、PTY 和交互 shell 行为。
