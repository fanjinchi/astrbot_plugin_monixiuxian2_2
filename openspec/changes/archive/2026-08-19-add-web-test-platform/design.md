## Context

动机见 proposal.md。关键约束与技术事实（来自对 AstrBot v4 源码的核查）：

- AstrBot 支持**插件注册平台适配器**：`astrbot.api.platform` 导出 `Platform`、`PlatformMetadata`、`AstrBotMessage`、`AstrMessageEvent`、`MessageMember`、`MessageType`、`register_platform_adapter`；插件热重载时会按模块路径注销插件注册的适配器（`unregister_platform_adapters_by_module`），说明这是官方扩展点。
- 消息入站：适配器构造 `AstrBotMessage` → `commit_event(create_event(abm))` 进 AstrBot 事件队列，走真实管线（EventBus → 插件 filter/Handler → 数据库/定时任务）。`webchat` 适配器（`astrbot/core/platform/sources/webchat/`）是最近的参照实现。
- 消息出站有两条路：
  1. **Handler 回复**：respond 管线最终调用 `event.send(chain)`；基类 `AstrMessageEvent.send()` 只记埋点，实际投递由各平台自定义事件子类重写 `send()`（如 `WebChatMessageEvent._send`）。→ 测试平台需自定义事件子类。
  2. **主动消息/广播**：`StarContext.send_message(umo, chain)` 按 `{platform_id}:{MessageType}:{session_id}` 解析后调用 `platform.send_by_session(session, chain)`（`astrbot/core/star/context.py`）。→ 适配器重写 `send_by_session()` 捕获。
- 被测试插件的关键身份语义（`main.py` 已核实）：玩家唯一标识 = `event.get_sender_id()` → `message_obj.sender.user_id`（玩家 DB 以它为键）；群白名单 = `event.get_group_id()` → `message_obj.group_id`（`require_whitelist` 用 `str(group_id) in self.whitelist_groups` 判定）。模拟身份必须落在这两个字段上，白名单/状态/数据库才能真实生效。
- AstrBot 规范：持久化数据必须在 `data/plugin_data/{plugin_name}/`；禁用 `requests`，用 aiohttp/httpx；`uv` 环境、ruff 门禁。

## Goals / Non-Goals

**Goals:**
- 最大化管线真实性：注入消息与真实平台消息在 AstrBot 内无差别处理。
- 双向可见 + 批注：网页与 CLI/API 看到同一消息流；批注作为 AI 反馈输入。
- AI 可编程驱动测试：CLI 注入、读流、等待期望回复。
- 零侵入被测插件：不修改修仙插件（项目本体）任何文件——代码、配置、数据、文档——也不修改 AstrBot 核心；测试平台仅以调用方身份交互，允许 import 修仙插件/AstrBot 模块复用代码（简化实现），但不做任何反向修改。

**Non-Goals:**
- 不实现 LLM 流式聊天体验（修仙为规则游戏；未处理消息若路由到 LLM，仅尽力呈现，见风险节）。
- 不做时间加速/时间旅行（保持真实壁钟，贴近真实环境；依赖时间的测试用 sleep 步骤真实等待）。
- 不做编程式断言语言（无变量/条件/循环/多分支，仅 send/expect/sleep 三类步骤 + 子串/正则匹配，够用即止）。
- 不做账号体系、多人协作权限（localhost + 可选令牌即可）。
- 不修改 AstrBot 本体（不改 core，避免升级维护成本）。

## Decisions

### D1: 交付形态 = 新 AstrBot 插件 `astrbot_plugin_testplatform`（单独文件夹 `testplatform_plugin/`，与项目本体隔离）

通过 `@register_platform_adapter("webtest", ...)` 注册适配器，插件加载即注册，在 AstrBot Dashboard 平台列表中像 webchat 一样启用。目录内：`main.py`（Star 子类，声明适配器模块 + 启动 Web 服务）、`metadata.yaml`、`_conf_schema.json`（端口/令牌/默认模拟玩家）、`adapter/`、`webui/`（静态前端）、`scripts/test_platform_cli.py`、`requirements.txt`（aiohttp）。

**隔离契约（用户明确要求，全变更适用）**：`testplatform_plugin/` 是唯一新增目录；项目本体（仓库根：`main.py`、`handlers/`、`managers/`、`core/`、`data/`、`config/`、`models*.py`、`_conf_schema.json`、`metadata.yaml`、`README.md` 等）零改动。测试平台只允许做**调用方**：import 修仙插件或 AstrBot 模块（含 `astrbot.api.*` 公开面）复用代码是允许的（可简化实现，如复用配置加载/工具函数），但 MUST NOT 反向修改或影响项目本体——不写其数据、不改其配置/文件、不 patch 其模块。与修仙插件的交互 = 消息注入/出站（真实管线）+ 用户在 Dashboard 对其配置的手动调整（运行时配置，非文件修改）+ 可选的代码复用 import。数据仅写 `data/plugin_data/astrbot_plugin_testplatform/`。目录自包含，可整体搬移至独立 git 仓库（可选，隔离性更强），搬移不需改任何设计。

- **备选 A**：独立模拟器直调插件 handlers —— 绕过白名单/EventBus/定时任务/数据库，保真度低，违背"贴近真实"诉求。否决。
- **备选 B**：改 AstrBot core 的 webchat 适配器 —— 需要 fork 核心，升级即碎。否决。
- **备选 C**：作为修仙插件自身的一个 manager —— 测试设施混入发行插件，污染交付物。否决（独立插件可只装进测试实例）。

### D2: 入站消息构造（身份真实性的关键）

每条注入消息构造 `AstrBotMessage`：

- `sender = MessageMember(nickname, user_id)`，user_id 为模拟玩家的稳定字符串（默认如 `test_player_001`），可配置；这是玩家 DB 与 GM/管理员判定的键。
- 私聊：`type = FRIEND_MESSAGE`；群聊：`type = GROUP_MESSAGE` 且 `group_id = 会话群 ID`（可配置，建议用户把该 ID 加入修仙插件白名单 `whitelist_groups` 以测白名单行为；不加则测拒绝路径——两种都是真实行为。注意：该白名单调整是用户在 AstrBot Dashboard 对修仙插件的运行时配置，不改动项目本体文件）。
- `session_id` 仿 webchat 风格：私聊 `webtest!{user_id}!{uid}`、群聊 `webtest!group!{group_id}`；`message_id` 用自增/时间戳保证唯一。
- 自定义事件子类 `WebTestMessageEvent(AstrMessageEvent)`，重写 `send()` 与 `send_streaming()` 捕获出站；适配器重写 `send_by_session()` 捕获主动消息，按 umo 的 session 段路由回会话。

### D3: Web 服务 = aiohttp（应用服务器）+ 静态前端 + REST + WebSocket

- aiohttp 是 AstrBot 自用栈、插件规范许可（无 requests）；前端为无构建步骤的单页（原生 JS + 少量 CSS），避免引入 node 工具链。
- 实时性：WebSocket 推送新消息/批注变更到浏览器；REST 提供全部读写接口（同一套 handler 服务 CLI 与 UI）。
- REST 契约（草案，实现时可微调路径但保持行为）：
  - `GET /api/conversations`（列表含类型/成员/消息数/归档状态）
  - `POST /api/conversations`（建会话：类型、群 ID/玩家、成员、归档否）
  - `PATCH /api/conversations/{id}`（归档/改名）
  - `DELETE /api/conversations/{id}`
  - `GET /api/conversations/{id}/messages?after=<id>&limit=`（增量读流，`after` 支持轮询）
  - `POST /api/conversations/{id}/messages`（注入玩家消息，`{"sender": "...", "text": "..."}`）
  - `GET/POST/PATCH/DELETE /api/messages/{mid}/annotation`（批注 CRUD）
  - `GET /api/players`（模拟玩家配置，供注入时选 sender）
- 注入接口同步返回受理结果；机器人回复经事件循环异步产生，调用方用 `after` 轮询或 `--expect` 等待。

### D4: CLI `scripts/test_platform_cli.py`（AI 侧主接口）

`uv run python test_platform_cli.py <cmd>`（在 AstrBot uv 环境运行，与插件测试同款调用方式）。子命令：`conversations`（list/create/archive/delete）、`send <conv> --player <id> --text "..."`、`feed <conv> [--after ID] [--json]`、`wait <conv> --expect "子串" --timeout 30`（阻塞至出现匹配的机器人消息，超时返回非零——AI 写测试脚本的等待原语）、`annotations <conv>`、`annotate <mid> --text "..."`。地址与令牌经 `--url`/`--token` 或环境变量 `WEBTEST_URL`/`WEBTEST_TOKEN`。

### D5: 持久化 = plugin_data 下 aiosqlite

`data/plugin_data/astrbot_plugin_testplatform/test_platform.db`，表：`conversations`（id、kind、group_id、name、archived、created_at）、`players`（id、nickname、user_id）、`messages`（id、conversation_id、direction in/out/system、sender、text、rich(JSON，保存图片等非纯文本段)、created_at）、`annotations`（id、message_id、text、updated_at）。遵循 AstrBot 数据存放规范；aiosqlite 与游戏插件一致。

### D6: 配置与访问控制

`_conf_schema.json`：`port`（默认 8765）、`host`（默认 127.0.0.1）、`access_token`（默认空=本机免令牌，设置后所有 REST/WS 操作校验，失败 401）、`default_players`（template_list：nickname/user_id 对，供建会话选人）。

### D7: 测试用例引擎（统一管理 + 一键验证）

目标：后续新增/修改功能时，写一个用例文件即可回归验证；AI 可经 CLI/API 自动发起测试并留下轨迹供用户回看批注。

- **用例存储**：`data/plugin_data/astrbot_plugin_testplatform/cases/<name>.json`，每文件一个用例，**自带人可读说明**：`{name, description(必填：测试目的与覆盖场景), scenario(必填：前置条件/涉及功能), tags[], conversation{kind: private|group, group_id?, pin_players?}, steps[]}`。步骤类型：`{type: send, player, text, note?}`、`{type: expect, match, timeout, note?}`（对会话内新产生的机器人回复做子串/正则匹配；note 描述预期行为）、`{type: sleep, seconds, note?}`。加载器做结构校验（含必填说明字段），非法用例报错并跳过。用例示例（自解释风格，`cultivation-basic-flow`）：

  ```json
  {
    "name": "cultivation-basic-flow",
    "description": "验证新玩家从零开始的修炼主循环：注册 → 闭关 → 等待结算 → 出关收获。",
    "scenario": "前置条件：无（运行器自动使用全新玩家身份）。覆盖：注册/修炼/结算。",
    "tags": ["cultivation", "smoke"],
    "conversation": { "kind": "private" },
    "steps": [
      { "type": "send", "player": "player_a", "text": "我要修仙", "note": "新玩家注册，期望进入修仙状态" },
      { "type": "expect", "match": "修仙", "timeout": 10, "note": "期望收到注册成功提示" },
      { "type": "send", "player": "player_a", "text": "闭关", "note": "开始闭关" },
      { "type": "expect", "match": "闭关", "timeout": 10, "note": "期望收到闭关开始提示" },
      { "type": "sleep", "seconds": 60, "note": "真实等待一个结算周期" },
      { "type": "send", "player": "player_a", "text": "出关", "note": "结束闭关并结算" },
      { "type": "expect", "match": "修为", "timeout": 10, "note": "期望结算提示包含'修为'收益" }
    ]
  }
  ```

  完整编写规范（命名/说明写法/标签约定）入 README 与 design_docs 用例编写指南。运行器与列表每次从文件系统重读用例文件——服务器端直接编辑 JSON 即时生效，无需重启；网页端编辑经 REST 写回同一文件。
- **运行器** `cases/runner.py`：每次运行创建**临时会话**（system-created）与**唯一玩家身份**（`case_{用例名}_{run序号}_{player}`，修仙插件按 user_id 键控玩家 → 天然从零状态）；需测 GM/管理员等固定身份路径时用 `pin_players` 钉住固定 user_id（承担状态继承，默认不钉）。步骤依次执行：send=注入，expect=轮询该会话新 out 消息匹配（超时失败），sleep=等待；结果与**轨迹**写入 DB `case_runs` 表（case、status、逐步骤结果含实际回复、起止时间、`case_snapshot` 用例内容快照、`run_messages` 运行期全部消息交换快照含时序）；轨迹独立于会话持久化，会话删除不丢轨迹；运行会话保留供人工批注。
- **管理面**：CLI `case list/new/show/run/run-all --tag` + `runs list/show <run_id>`（AI 经 CLI 发起自动化测试并回看轨迹；退出码区分成败）；REST `/api/cases` CRUD（GET/POST 列表与新建、`PUT /api/cases/{name}` 更新内容、`GET/DELETE /api/cases/{name}`、`POST /api/cases/{name}/runs`、`GET /api/cases/{name}/runs` 含轨迹详情）；Web UI 用例面板（**新建/编辑/删除/一键运行**、按标签筛选，编辑提供表单与 JSON 源码两种方式） + **轨迹视图**（运行列表 → 单次运行消息时间线，含步骤结果标注、**步骤说明 note**、用例版本、批注入口）。
- **标签约定**：功能域标签（如 `cultivation`/`combat`/`sect`/`boss`/`gm`），README 维护清单；改某功能 → `case run-all --tag <域>`。
- **与批注闭环**：用户在轨迹/会话消息上批注实际回复，AI 读批注改代码后重跑同一用例；CLI/API 发起与网页发起留同等完整轨迹。
- **录制式生成**（后续可选）：手动操作会话后"另存为用例"，本期不纳入。

## Risks / Trade-offs

- [LLM 流式回复不呈现] respond 管线对 LLM 结果走 `event.send_streaming`，基类默认不投递 → 重写 `send_streaming` 将分片追加进 feed（尽力）；同时在 README 建议测试实例把 `unsupported_streaming_strategy` 配为 `synchronous`，规则游戏主流程不受影响。
- [同实例测试污染正式玩家数据] 修仙插件按 user_id 存玩家 → 文档明确建议测试用独立 AstrBot 实例（独立 `data/` 目录）部署本插件+修仙插件；同一实例可用但需自担数据混用。
- [import 复用引入耦合] 若测试平台 import 修仙插件模块，则依赖其先于本插件加载（插件加载顺序），且修仙插件热重载后已持有的引用可能失效 → import 用 try/except 包裹并给出明确错误提示（"请先加载修仙插件"）；优先复用无状态工具（配置加载、格式化、常量），避免持有长生命周期引用。
- [唯一玩家身份 vs 固定身份路径] 用例默认唯一 user_id 保证从零状态，但 GM/管理员等按固定 user_id 判定的路径测不到 → `pin_players` 钉住固定身份（承担状态继承），README 说明两者取舍。
- [适配器 id 冲突] `webtest` 若被其他插件占用则注册抛错 → 注册失败时插件加载日志明示，改 `_conf_schema` 可换 id（或改名重发版）。
- [主动消息到达未知会话] 定时广播可能指向从未创建的群 → 首次到达自动建会话（标记 system-created），避免丢消息。
- [依赖真实时间的测试慢] 闭关/悬赏等按真实壁钟结算 → 非目标（不做时间加速），AI 测试脚本用 `wait --expect` 超时控制节奏。
- [前端无构建链的局限] 原生 JS 写复杂 UI 较笨 → 平台 UI 保持克制（消息流/输入框/批注/会话栏四块），复杂可视化后续再说。

## Migration Plan

- 部署：`testplatform_plugin/` 随仓库同步到 `~/code/AstrBot/data/plugins/astrbot_plugin_testplatform/`（沿用现有同步机制）→ AstrBot 加载插件（依赖 aiohttp 已在内核环境，requirements.txt 声明兜底）→ Dashboard 平台设置中启用 `webtest` 适配器并配置端口/令牌 → 打开 `http://127.0.0.1:{port}`。
- 建议同时准备独立测试实例（复制 AstrBot 或 `--data-dir` 指向新目录），装入修仙插件与本插件。
- 回滚：Dashboard 停用适配器或移除插件目录并重载；数据文件在 plugin_data 下可整体删除。不影响修仙插件本身。

## Open Questions

- 是否需要 MCP 服务器形态的 AI 接口（免 bash 直调）？——CLI 已覆盖当前需求，MCP 留作后续增量。
- 前端是否需要图片/文件消息段展示（修仙有文转图输出）？——消息表已留 `rich` JSON 列兼容，展示优先级低，见到实际用例再补。
- 录制式生成用例（手动会话一键导出为用例）是否纳入？——用例格式已定，录制器可后续增量实现。
