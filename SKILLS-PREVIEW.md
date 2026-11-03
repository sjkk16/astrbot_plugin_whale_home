# 技能与工具 · v0.3.1 个人预览版

本功能现已随 v0.3.1 个人安装包交付，源码与 `views/home/` 正式页面同步构建。旧 v0.3.0 ZIP 不包含技能工具功能，仍原样保留。角色、背景、12 张差分和原有玩法保持不变。安装与本次重新验证范围见 `RELEASE-V031.md`；下面也保留独立开发预览的启动方式。

## 启动独立预览（Windows PowerShell）

在项目根目录执行：

```powershell
Push-Location frontend
npm.cmd run build:skills-preview
Pop-Location
.venv/Scripts/python.exe tools/dev_server.py --port 18842 --data-dir .local/skills-preview --static-dir artifacts/skills-preview/preview-site --interaction-preview
```

打开 http://127.0.0.1:18842 。服务只监听本机。`--interaction-preview` 仅为全新的独立演示存档选择本地演示模型，不修改已有存档，不启用主动搭话或自主生活。

- 页面输出：`artifacts/skills-preview/preview-site/`。
- 演示数据：`.local/skills-preview/`，与 AstrBot 的插件存档独立。
- 设置 → 技能与工具：默认启用、限制访问、两个白名单为空。
- 勾选 `demo_weather` 和 `demo_companion`，保存技能权限后，在聊天中发送“请用技能查询天气”。先读模拟指引，再调用模拟天气工具。
- 勾选 `demo_slow` 后发送“运行慢速演示”，可验证执行中的停止、权限撤销及跨页面同步。
- 上述工具完全是本地脚本演示：固定天气不是实时天气，慢速工具只是等待，不联网、不写个人文件。

## AstrBot 接入与权限

支持当前已验证的 AstrBot 4.29.3 SDK。真实宿主中，目录来自工具注册表及 SkillManager；模型、插件、MCP 服务和 Computer Use 环境仍由 AstrBot 管理，本插件不安装技能、不保存密钥、不自动连接新的服务。

- **限制访问**：只暴露勾选且宿主可用的能力，白名单内自动执行，不逐次确认。已移除的能力仍显示为不可用，允许撤销旧授权。
- **完全访问**：启用时需要确认一次风险，自动开放宿主已启用且兼容的能力。白名单选择保留，切回限制访问后继续生效。
- 两种模式均遵守宿主工具权限、启用状态、插件配置和沙箱。不伪造管理员、真实私聊或群聊身份；独立会话标识为 `whale_home:OtherMessage:home`，成员身份为 `whale_home_owner`，默认 role 为 member。
- 白名单限制“选择哪些工具”，不是额外的文件或脚本沙箱。允许命令执行或第三方工具后，其内部能力仍取决于宿主权限与工具实现。
- Skills 先提供名称和摘要，再通过只接受技能名称的读取入口加载完整指引；读取指引不授予其他工具权限。本机只读登记目录中的 SKILL.md，最多 64 KiB；沙箱专属指引使用宿主文件读取能力。指引过大、环境缺失或权限不足均失败，不自动扩权。
- 四类已有模型场景均接入同一控制器；原有模型选择、互动回应、主动搭话和自主生活开关继续独立生效。Q 版原来不支持的直接触碰与主动搭话不会因此开启。
- 不新增每日或单轮工具次数配额；整轮仍受原有 60 秒超时约束。宿主原有保护、供应商行为和各场景原有频率限制仍有效。多轮工具调用可能增加模型与工具费用。
- 首版不支持子代理转交、独立后台工具任务或已知要求真实平台身份的工具，目录会标注原因。普通工具若内部强依赖平台事件，也可能因小家独立事件而失败；不承诺任意第三方插件都兼容。
- 命令工具不接受后台执行标志；原生本机 shell 返回的受管会话会在当前请求内等待，并在退出时尝试结束，仅管理本次调用产生的会话。工具自身或命令自行启动的外部活动无法被插件完整隔离或撤销。

## 调用状态与数据

- 每次实际执行前重新检查宿主状态、白名单及取消标志，不依赖模型遵守提示词来实现权限控制。
- 调用记录包括名称、来源、触发场景、状态、时间、耗时和安全错误码；保留最近 5000 条。插件审计不保存完整参数、工具返回内容或宿主异常正文。工具主动发到当前会话的文本只在当前进程的界面中展示。
- 注意：以上是**插件审计表**的行为。AstrBot 原生运行器及第三方工具可能自行记录参数、结果或日志，本插件不改写宿主日志配置。
- “停止本轮技能”、关闭总开关、修改权限或插件关闭会停止后续调用；已经开始的外部操作不能保证撤销。
- 执行中超时、进程退出或异常不能证明操作没有发生，因此记为“结果未确认”，不会写成未执行。明确的工具错误显示失败。
- 请求去重和持久化执行标识防止浏览器重连、重复请求和进程恢复自动重放。MCP 接入保留宿主权限校验，但绕开会重连重放的封装，对一次调用只发送一次。
- 权限和审计使用独立本机表，房间与导出存档仍为 v2。导入存档后恢复启用的限制访问、清空白名单，调用记录与既有本机请求记录不清空。
- 工具执行不持有长时间房间锁；世界版本变化仍会拒绝过期房间动作，互动模型回应不会再次消耗库存。

接口：`GET skills/catalog`、`GET/POST skills/preferences`、`GET skills/calls`、`POST skills/stop`。写入仍使用 `request_id` 和 `expected_version`。进入启用的完全访问时额外提交 `confirm_full_access: true`。状态快照新增 `skills`，沿用现有 SSE。

## 验证命令

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check whale_home main.py tests tools
Push-Location frontend
npm.cmd run build:skills-preview
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_STATIC_DIR='../artifacts/skills-preview/preview-site'
$env:PLAYWRIGHT_OUTPUT_DIR='../artifacts/skills-preview/playwright-final'
$env:PLAYWRIGHT_SCREENSHOTS_DIR='../artifacts/skills-preview/screenshots'
npm.cmd test
Pop-Location
```

实际 AstrBot SDK 的离线适配器验证使用已经准备好的宿主虚拟环境：

```powershell
.runtime/astrbot/AstrBot-4.29.3/.venv/Scripts/python.exe tools/verify_skills_adapter.py
```

脚本在独立 `.local/skills-sdk-*` 目录中构造虚拟模型、插件工具及 MCP 会话，验证原生工具循环、Skills 读取、成员身份、消息输出、MCP 断线不重放、宿主拒绝权限和插件配置过滤。它不调用真实模型或 MCP 服务。

本次还使用独立 `.local/astrbot-skills-verify` 实例验证真实 Dashboard iframe、bridge 序列化、保存权限、完全访问确认、重载、SSE、导入后权限重置及桌面／手机截图，模型调用为 0。验证脚本为 `tools/verify_skills_iframe.mjs`，只允许无模型、无消息平台的本机测试配置。宿主自身启动时会执行元数据查询；不将此宿主验收描述为完全离线。

## 功能开发预览阶段验收记录

以下为先前独立预览阶段记录，不代表本次 ZIP 的重新验收；v0.3.1 安装包结果见 `RELEASE-V031.md`。

- Python 完整回归：320 项通过。
- Vue / TypeScript / Vite 独立预览构建通过；沿用 12 张已校验差分。
- 完整无头 Edge 回归：54 项通过，无跳过、无重试通过。汇总见 `artifacts/skills-preview/verification.json`。
- Ruff、真实 SDK 适配器检查及真实宿主 iframe 检查通过。
- 截图与宿主结果在 `artifacts/skills-preview/`；测试失败排查记录与最终通过记录分目录保留。
- 未使用个人存档、真实在线模型或付费服务；未验证任意第三方工具、远程沙箱服务、Linux/macOS 或其他浏览器的运行质量。
- 原有安装包及校验文件保留；真实对外调用和付费体验需在用户自行配置并授权的环境中另行验收。
