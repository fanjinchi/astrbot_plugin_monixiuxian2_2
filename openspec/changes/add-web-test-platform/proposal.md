## Why

模拟修仙 v2 是强环境依赖的聊天游戏插件：白名单、群聊语义、定时任务（Boss 生成、闭关结算等）、数据库与消息广播都与 AstrBot 运行环境深度耦合。目前验证功能只能依赖真实聊天平台（QQ/Telegram 等），没有一条**开发者和 AI 都能实时看到**的互动通道，测试输出也无法就地批注，导致迭代验证成本高、反馈链路断裂。需要一个贴近真实运行环境的网页端测试平台：模拟玩家发消息 → 插件真实响应 → 双方可见 → 可批注。

## What Changes

- 新增一个独立 AstrBot 插件 `astrbot_plugin_testplatform`（代码放在**单独文件夹** `testplatform_plugin/`，与项目本体目录完全隔离；本变更不改动项目本体任何文件），通过 `astrbot.api.platform` 注册自定义平台适配器 `webtest`，使测试消息**走 AstrBot 真实事件管线**（平台适配器 → EventBus → 插件 filter/Handler → 真实数据库与定时任务），而非模拟器直调。测试平台仅作为**调用方**：调用 AstrBot 公开 API、经消息管线调用修仙插件；为简化实现可 import 修仙插件/AstrBot 模块复用代码，但不得反向修改或影响插件本体。
- 提供网页端界面：展示模拟玩家与机器人之间的完整消息流（双向可见），支持模拟私聊与群聊会话、多模拟玩家。
- 提供 REST API + CLI 工具：AI（或用户）可通过命令行/HTTP 注入玩家消息、读取消息流与测试结果，供 AI 在平台上持续运行各功能测试。
- 提供批注能力：用户可在任意消息上添加/编辑批注，AI 可读取批注作为修改反馈；批注持久化于 `data/plugin_data/`。
- 提供测试辅助设施：会话/场景管理（新建、切换、归档测试会话）、消息历史持久化、主动消息（定时任务广播）在 Web UI 上的呈现。
- 提供**测试用例统一管理**：结构化用例脚本（步骤 = 注入消息 / 期望回复匹配（子串或正则，含超时）/ 等待时长；功能域标签），支持一键/批量运行、每次运行从零会话执行、结果持久化与失败定位（附实际回复），使后续新增或修改功能时可在此快捷增删用例并回归验证。测试可由 AI 经 CLI/API 发起（自动化），每次运行留下**完整测试轨迹**——运行期全部消息交换快照、逐步骤结果、用例版本快照——用户随时回看轨迹并就地批注，形成 运行 → 批注 → 修改 → 重跑 的反馈闭环。

## Capabilities

### New Capabilities

- `web-test-platform`: 网页端测试平台能力——自定义平台适配器、双向消息流可见性、消息注入（REST + CLI）、批注、会话管理、与真实 AstrBot 管线的集成行为。

### Modified Capabilities

（无。本变更不修改既有玩法规格；游戏插件的既有 spec（skill-system、combat-core 等）行为不变。）

## Impact

- **新增代码**：`testplatform_plugin/`（新 AstrBot 插件，含 `main.py`、`metadata.yaml`、`_conf_schema.json`、平台适配器、Web 服务、前端静态资源、CLI 脚本）。
- **既有代码**：**零改动**——本变更不修改项目本体（修仙插件）任何代码/配置/数据/文档，也不修改 AstrBot 核心；测试平台仅作为调用方与之交互，允许 import 复用其代码（简化实现）但禁止任何反向修改（详见 specs 隔离需求）。
- **依赖**：复用 AstrBot 提供的 `astrbot.api.platform`（`Platform`、`PlatformMetadata`、`AstrBotMessage`、`AstrMessageEvent`、`MessageMember`、`MessageType`、`register_platform_adapter`）与 `context.send_message`；Web 服务用 `aiohttp`（遵守"不使用 requests"的插件规范）。
- **运行环境**：需在一个运行中的 AstrBot 实例内加载本插件与被测的修仙插件；建议使用独立数据目录的专用测试实例，避免污染正式玩家数据（插件本身与实例无关，同一实例亦可）。
- **文档**：`README.md`、`design_docs/` 新增测试平台说明（不影响游戏玩法数值，不触发 design_docs 数值同步义务）。

**记录的设计假设**（供评审时修正）：
1. 测试平台代码置于本仓库顶层独立目录 `testplatform_plugin/`（单独文件夹，与插件本体隔离）；该目录自包含、可整体搬移至独立 git 仓库而不改动任何设计（隔离性更强，作为可选部署方式）。
2. AI 侧交互接口 = CLI（bash 可调）+ REST API；用户侧 = 网页 UI；两侧看到同一消息流。
3. Web 服务默认绑定 localhost，支持可选访问令牌；不引入账号系统。
4. 消息注入优先以"模拟群聊"为主场景（游戏以群为主），同时支持私聊。
