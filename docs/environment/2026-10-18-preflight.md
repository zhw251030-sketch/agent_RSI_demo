# OpenHands 安装前环境记录

检查日期：2026-10-18。本文整理已执行的只读检查，非安装结果；2026-10-20 纳入项目仓库。连接信息和绝对用户路径保留在本地管理记录。

| 检查项 | 当时观察 |
|---|---|
| 项目目录 | 可通过既有 SSH 连接进入，临时文件写入/回读/清理成功；当时为空 |
| 系统 Python | 3.10.12 |
| Anaconda base Python | 3.14.6 |
| 现有 evo 环境 Python | 3.12.14 |
| SDK 配套包 | 上述三个解释器均未检出 openhands-sdk、openhands-tools、openhands-workspace、openhands-agent-server |
| Docker | CLI 28.3.0 已有；当前账号访问 daemon 被拒绝，非交互 sudo 需要密码 |
| 旧项目配置 | compose 声明 agent-canvas-local:1.17.0；未验证镜像或运行中容器，也不能据此推断 SDK 版本 |

用户希望使用 OpenHands。当前建议将 **OpenHands SDK 作为 Agent 执行底座**，由项目明确管理任务适配、修订策略、数据隔离和评价。框架提供 Agent 运行能力，不自动构成本项目的改进机制或有效性证据。

2026-10-18 核查的官方配套发布版为 1.55.1，Python 要求 >=3.12；SDK/tools 应匹配版本。此处是当日记录，正式安装前仍需核查和锁定版本。

建议后续步骤：在项目目录建立独立 Python 3.12 环境，安装匹配版本的 SDK/tools；先检查导入和固定脚本执行，再准备生成代码的隔离执行环境；然后配置模型、接入任务并保存调用日志。本次同步未执行这些步骤，未修改系统权限或旧环境。

来源：

- [OpenHands SDK getting started](https://docs.openhands.dev/sdk/getting-started)
- [openhands-sdk 1.55.1](https://pypi.org/project/openhands-sdk/1.55.1/)
- [Workspace 架构](https://docs.openhands.dev/sdk/arch/workspace)
