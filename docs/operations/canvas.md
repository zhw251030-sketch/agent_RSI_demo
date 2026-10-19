# OpenHands 网页入口：访问与维护

当前模型已配置为 **MiniMax-M3**，详见 [模型配置与验收](minimax.md)。以下安装步骤中的“跳过模型配置”用于新环境初始化。

## 它在项目中的作用

Agent Canvas 是官方交互界面，用于打开工作目录、浏览项目、配置模型和观察交互。正式研究仍使用 `.venv` 中的 SDK 与固定协议运行，避免把手工对话与可重复的对照实验混在一起。

当前部署分为两套环境：

| 用途 | 固定版本 | 存放位置 |
|---|---|---|
| 实验 SDK | SDK/tools 1.55.1，Python 3.12.14 | `.venv/` |
| 网页入口 | Agent Canvas 1.28.1 | `.canvas-runtime/npm/` |
| 网页后台 | Agent Server 1.56.0、Automation 1.22.0 | `.canvas-runtime/uv-cache/` |
| 启动工具 | uv 0.13.1；复用 Node.js 24 | `.canvas-runtime/tools/` 与已有 Node |
| 网页私有状态 | 认证/加密文件、设置、数据库、日志 | `.canvas-state/` |

网页及 uv 运行目录均被 Git 忽略。不要提交这些目录、网页运行时 HTML、浏览器存储或原始日志；其中可能含本地认证信息。选定工作目录决定默认操作位置，并不限制后端的系统权限。生成代码的隔离运行仍待实现。

## 平时怎么打开

若 http://127.0.0.1:18080/ 已能访问，直接打开即可，无需重复启动服务或创建隧道；重复 SSH 转发会因本机端口已占用而退出。

1. 在服务器项目根目录执行：

   ```bash
   .venv/bin/python scripts/canvas.py start
   .venv/bin/python scripts/canvas.py status
   ```

   `start` 后依赖准备可能需要时间。`status` 应显示一个管理中的 PID，以及 page、agent、ready、automation 四项 HTTP 200；ready 在初始化期间可能返回 503。

2. 在本机 PowerShell 建立隧道（将 `<SSH别名>` 替换为已配置的实验服务器别名）：

   ```powershell
   ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:18080:127.0.0.1:18080 <SSH别名>
   ```

   保持这个窗口开启。SSH 隧道将本机 18080 转发到服务器回环端口，不需要在服务器开放公网端口。

3. 浏览器打开 **<http://127.0.0.1:18080/>**。查看本地后端连接状态及工作目录；首次向导的模型与自动化步骤可以跳过。尚未配置模型时，不会得到 Agent 回复。此 npm 部署的首页是 `/`；不要套用 Docker 文档中的 `/canvas`，后者会落到前端的 Page not found。

服务器后台进程可在 SSH 退出后继续运行，但没有安装开机自启。电脑重启或网络断开后需重新建立隧道；服务器重启后还需重新 `start`。

## 如何停止与定位问题

服务器项目根目录：

```bash
.venv/bin/python scripts/canvas.py stop
.venv/bin/python scripts/canvas.py status
```

`stop` 先核验 PID、启动时间与官方启动器路径，再请求终止该实例的进程组；不使用全局 `pkill node/python`。本机前台 SSH 隧道按 Ctrl+C 关闭。若本轮由助手创建了隐藏隧道，其 PID 记录在上级工作区的本地部署记录中，可按该记录停止对应 SSH 进程。

- 页面完全打不开：先核对隧道是否运行，再检查服务器 `status`。
- 页面可见但 backend 未连接：检查 agent HTTP 状态；首次 uv 依赖安装可能晚于页面准备完成。
- 端口被占用：脚本会拒绝启动，不会停止其他程序。内部固定端口为 18100、18101、18102，编辑器保留 19100；入口为 18080。
- 日志在服务器 `.canvas-state/launcher.log`；仅本地检查，分享前脱敏。
- 模型选择：当前已激活 `minimax-m3`。若在新环境看到未配置提示，按 [MiniMax 配置说明](minimax.md) 接入。网页尚未发送 Agent 对话、未创建自动化。

## 在新环境重建

在 Linux 项目根目录准备 Python ≥3.12 与 Node ≥24，并先按 [SDK 安装说明](../environment/2026-10-20-setup-and-verification.md) 建好实验 `.venv`；下列命令依赖它。`CANVAS_NODE` 可指定 Node 可执行文件；脚本也检查 PATH 和用户已有 nvm 版本。

```bash
.venv/bin/python -m venv .canvas-runtime/tools
.canvas-runtime/tools/bin/python -m pip install --index-url https://pypi.org/simple uv==0.13.1
# 先确保当前 shell 的 node/npm 是 Node 24 对应版本。
npm install --prefix .canvas-runtime/npm --cache .canvas-runtime/npm-cache --registry https://registry.npmjs.org --save-exact --no-audit --no-fund @openhands/agent-canvas@1.28.1
.venv/bin/python scripts/canvas.py start
```

主包版本固定；本次 npm 实际依赖锁保存在 `deploy/canvas/package-lock.json`。需要重现该依赖解算时，将该锁和同目录 `package.json` 复制到 `.canvas-runtime/npm/`，再用 `npm ci --prefix .canvas-runtime/npm`。Python 后端由官方 uvx 启动，固定主包版本；传递依赖完整版本另存部署证据，不应把它称为跨机器完全一致的环境。

## 配置依据

- [官方安装说明](https://docs.openhands.dev/openhands/usage/agent-canvas/setup)：npm 安装、端口、后端与工作目录。
- [官方首次设置](https://docs.openhands.dev/openhands/usage/agent-canvas/first-time-setup)：向导可跳过模型与工作流。
- [本次官方包的默认版本](https://github.com/OpenHands/OpenHands/blob/eeb11425ed87c5e83c5069797b706727834f9e46/config/defaults.json)。
- [本次官方目录与密钥配置源码](https://github.com/OpenHands/OpenHands/blob/eeb11425ed87c5e83c5069797b706727834f9e46/scripts/dev-safe.mjs)：使用 `OH_CANVAS_SAFE_STATE_DIR`、两个密钥路径变量及 `VITE_WORKING_DIR`，未修改 HOME。

部署验收与证据见 [本轮部署记录](../environment/2026-10-20-canvas-deployment.md)。
