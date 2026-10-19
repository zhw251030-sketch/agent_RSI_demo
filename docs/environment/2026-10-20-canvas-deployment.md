# 2026-10-20 OpenHands 网页部署与验收

## 已交付

在当前服务器项目目录部署官方 **Agent Canvas 1.28.1**，本机通过 SSH 隧道访问 **http://127.0.0.1:18080/**。已实际打开浏览器，选择默认 OpenHands 智能体，登记并选中 `agent_RSI_demo` 工作区。首页明确提示尚未配置 LLM；未提交对话或创建自动化。

这是交互入口的部署结果，不是 RSI 研究结果。模型、任务执行器和生成代码隔离仍待接入。

## 做了什么，为什么这样做

| 文件/目录 | 本轮工作 | 原因 |
|---|---|---|
| `scripts/canvas.py` | 提供 start、status、stop；管理进程登记与端口检查 | 让以后打开网页不依赖临时命令，停止时不误伤其他项目 |
| `docs/operations/canvas.md` | 写清访问、隧道、重启、停止、安装与排错 | 服务器服务与本机浏览器之间需要 SSH 转发；服务启动与模型可用是两回事 |
| `deploy/canvas/package.json`、`package-lock.json` | 固定网页主包 1.28.1 并保存实际 npm 解算结果 | 防止后续安装随 latest 漂移；锁内包含具体包版本、来源和完整性信息 |
| `deploy/canvas/backend-dependencies.json` | 导出两个 uvx 环境实际安装的 195/172 项版本 | 官方后台主包固定并不等于传递依赖也固定；保留运行时证据，便于后续复核 |
| `.gitignore` | 排除 `.canvas-runtime/` 与 `.canvas-state/` | 程序依赖、认证材料、设置、数据库和日志不应上传 GitHub |
| `docs/environment/2026-10-20-canvas-verification.json` | 保存端口、HTTP、版本、权限与脚本哈希的脱敏验收记录 | 用实际结果区分“配置写好了”与“服务确实可用” |

已有实验 `.venv` 保留 SDK/tools **1.55.1**，复核版本未改变。网页采用官方 1.28.1 对应的 Agent Server **1.56.0** 和 Automation **1.22.0**，由独立 uvx 环境运行；不混装到实验环境。服务器已有 Node **24.16.0**，只为本项目安装 uv **0.13.1**。

没有使用 Docker，因为此前已经确认当前账户无法访问 Docker daemon；本次使用官方支持的 npm 本地后端方式。该方式具有当前用户的文件权限，不构成生成代码沙箱。

## 访问与状态隔离

入口 18080、Agent Server 18100、Automation 18101、前端 18102 的实际监听地址均为 **127.0.0.1**；编辑器预留 19100，验收时未启动编辑器。已有 8000、3000 服务不受本项目管理。

本机 SSH 隧道只转发回环地址。未开放公网端口、修改防火墙或设置开机自启。服务器进程在启动 SSH 会话结束后仍可运行；电脑断线需重连隧道，服务器重启需重新启动服务。

官方源码显示 `OH_CANVAS_SAFE_STATE_DIR` 不会自动改变两类密钥文件的位置，因此同时设置 `OH_SESSION_API_KEY_PATH` 与 `OH_SECRET_KEY_PATH`。状态父目录为 `.canvas-state/`，权限 0700；两类自动生成的本地认证/加密文件权限均为 0600。这些不是模型 API 密钥，没有上传到仓库。模型凭据与其他项目的 OpenHands 环境变量不从父环境传入。

## 实际验收

- 浏览器进入首页，工作区按钮显示 `agent_RSI_demo`；模型未配置提示可见。
- `/`、`/server_info`、`/ready`、`/api/automation/health` 均返回 **200**。`/ready` 用于确认后台初始化完成，而非仅能响应请求。
- `/server_info` 报告 Agent Server/SDK 1.56.0；实验环境仍为 SDK/tools 1.55.1。
- 重复启动返回同一管理 PID；执行停止后，本实例四个监听端口均消失；重新启动后四项 HTTP 检查恢复 200。
- 核验状态路径和密钥文件权限，导出实际依赖版本。
- 本轮提交的模型请求、Agent 对话及自动化创建均为 **0**；未配置模型凭据。

验收中修正了启动登记的短暂时序窗口，并增加已有进程检测与管理锁。重启检查也发现 Linux `TIME_WAIT` 会被简单 bind 检查误判为占用，现用与正常服务一致的 `SO_REUSEADDR` 加 listen 检查；真实监听仍会阻止重复启动。网页还确认 npm 首页为 `/`，而不是 Docker 示例中的 `/canvas`。这些结果说明仅看 HTTP 200 或安装成功不足以验收整条访问链路。

## 与研究的关系及下一步

网页让后续交互调试、配置和查看项目更方便。正式实验应继续通过脚本固定模型、任务、预算与反馈协议，保存每轮轨迹并形成可复核对照。不能把手工网页对话当成已完成的算法实验。

下一步仍是准备两类任务执行器、生成代码隔离和数据访问：规划侧验收 PDDL/VAL 的成功、失败与超时；符号侧取得合法数据访问后核对方程与结构族，再冻结共同评价协议。模型配置与费用安排按用户要求继续后置。

## 来源

- [官方安装与访问说明](https://docs.openhands.dev/openhands/usage/agent-canvas/setup)
- [官方首次设置](https://docs.openhands.dev/openhands/usage/agent-canvas/first-time-setup)
- [1.28.1 默认版本组合](https://github.com/OpenHands/OpenHands/blob/eeb11425ed87c5e83c5069797b706727834f9e46/config/defaults.json)
- [隔离目录与密钥路径源码](https://github.com/OpenHands/OpenHands/blob/eeb11425ed87c5e83c5069797b706727834f9e46/scripts/dev-safe.mjs)
- [启动器与端口源码](https://github.com/OpenHands/OpenHands/blob/eeb11425ed87c5e83c5069797b706727834f9e46/scripts/dev-with-automation.mjs)

官方 npm tarball SHA-256：`11067e714733a0ddccb316d8621261f58b4e6acc22a493cad91cc8e9bb12ccda`；npm integrity 同时保存在依赖锁中。安装的是官方发布包，未修改其源码。
