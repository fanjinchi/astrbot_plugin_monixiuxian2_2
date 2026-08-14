# 网页端测试平台（testplatform_plugin/）— 设计文档

> 类型：本项目 · 配套工具（非游戏玩法系统）
> 创建：2026-08-15 · 对应 OpenSpec change：`add-web-test-platform`（openspec/changes/add-web-test-platform/，specs/web-test-platform/spec.md）
> 状态：v0.1.0 已实现（32 项单元测试 + 56 项独立端到端冒烟通过，主树零改动隔离验收通过）

## 定位与目标

为修仙插件搭建**尽可能贴近真实运行环境**的网页端测试平台：

- 以 AstrBot **平台适配器**身份接入真实消息管线——玩家消息从注入到回复，经过与真实平台完全相同的 filter → Handler → 白名单 → 数据库 → 定时任务全链路；
- 网页端消息流**用户与 AI 同时可见**：AI 可经 CLI/API 持续发起功能测试，用户在网页看到输出并**批注**，AI 按批注修改后重跑，形成「运行 → 批注 → 修改 → 重跑」闭环；
- 自动化：测试**用例**（JSON 定义步骤 send/expect/sleep）可一键运行、批量运行（`--tag`），每次运行留**完整轨迹**（全部消息交换快照 + 逐步骤结果 + 用例版本快照）。

## 目录结构与交付形态

```
testplatform_plugin/                 # 唯一新增目录（项目本体零改动）
├── metadata.yaml                    # AstrBot 插件元数据（astrbot_plugin_testplatform）
├── requirements.txt                 # aiohttp>=3.9（AstrBot 加载时自动安装）
├── _conf_schema.json                # 可视化配置：host/port/access_token/default_players
├── main.py                          # Star 子类：初始化数据目录 + app_state
├── adapter/
│   └── webtest_adapter.py           # webtest 平台适配器（@register_platform_adapter）
├── storage/db.py                    # aiosqlite 持久化（5 表）
├── cases/
│   ├── loader.py                    # 用例校验/读写（description/scenario 必填，缺则拒收）
│   └── runner.py                    # 用例运行器（不 import AstrBot，注入器由调用方提供）
├── server/
│   ├── app_state.py                 # 全局状态单例：配置合并/注入/出站捕获/WS 广播/用例运行
│   └── app.py                       # aiohttp 应用：REST + WebSocket + 静态前端
├── webui/                           # 原生 JS 前端（无构建链、无 CDN）
├── scripts/test_platform_cli.py     # CLI：conversations/send/feed/wait/annotations/annotate/case/runs
└── tests/                           # 32 项 pytest（storage/loader/runner）
```

## 真实管线接入（核心机制）

### 入站：消息注入

```
REST POST /api/conversations/{id}/messages {sender, text}
  → app_state.inject_message()：校验会话/玩家 → 持久化 in 消息 → 触发平台回调
  → adapter.build_abm(conversation, player, text) 构造 AstrBotMessage
      · 私聊：MessageType.FRIEND_MESSAGE，session_id = webtest!{user_id}!{conversation_id}
      · 群聊：MessageType.GROUP_MESSAGE，session_id = webtest!group!{group_id}，Group.members 填会话玩家
      · sender = MessageMember(user_id, nickname) —— 玩家键语义与真实平台一致
  → adapter.create_event(abm) → WebTestMessageEvent
  → commit_event() 入事件队列 → AstrBot respond 管线正常处理
```

修仙插件身份语义自动成立：玩家键 = `get_sender_id()` → `sender.user_id`；白名单 = `get_group_id()` → `group_id` 与 `whitelist_groups` 比对（require_whitelist 拦截行为与真实群聊一致）。

### 出站：双向捕获

| 路径 | 捕获点 | 说明 |
|---|---|---|
| Handler 回复 | `WebTestMessageEvent.send()/send_streaming()` | respond 管线最终调用 event.send；重写后先落库+广播再调基类 |
| 主动消息/定时广播 | `WebTestAdapter.send_by_session()` | StarContext.send_message 按 `platform_id:type:session_id` 路由到平台；未知会话自动创建（system-created），出站消息在网页可见 |

消息体处理：Plain 拼接为纯文本；Image/File/Record/Json 转为描述段写入 `rich` 字段（前端展示占位，不丢信息）。

### 会话与身份

- **私聊** `webtest!{user_id}!{conversation_id}`：一个会话绑定一个玩家；注入时按会话内玩家发消息。
- **群聊** `webtest!group!{group_id}`：group_id 取自 `conversation.group_id`；消息发送者必须是会话成员。
- **玩家身份**：网页/CLI 手动会话用 `default_players`（可配置）；用例运行默认生成**唯一身份** `case_{用例名}_{run序号}_{player}`（每次运行从零状态，可反复跑不污染），`pin_players` 可钉住固定 user_id（测 GM/管理员路径）。

## 测试用例引擎

用例为 JSON 文件，存放在 `data/plugin_data/astrbot_plugin_testplatform/cases/<name>.json`（AstrBot 插件数据目录，非插件自身目录）；**编辑即生效**（每次运行从磁盘重读）。

```json
{
  "name": "cultivate-basic-flow",
  "description": "验证闭关→修炼状态→出关完整流程",          // 必填：说明测什么
  "scenario": "新玩家私聊指令 闭关，确认状态进入修炼中，出关后获得修为",  // 必填：场景描述
  "tags": ["cultivation"],
  "conversation": { "kind": "private", "pin_players": {} },
  "steps": [
    { "type": "send",   "player": "player1", "text": "闭关", "note": "进入修炼" },
    { "type": "expect", "match": "修炼中", "timeout": 30, "note": "状态应切换" },
    { "type": "sleep",  "seconds": 3, "note": "等修炼完成" },
    { "type": "expect", "match": "出关", "timeout": 30 }
  ]
}
```

- 步骤类型：`send`（注入玩家消息）/ `expect`（轮询新出站消息匹配，`re:` 前缀为正则；超时记失败并保留窗口内全部实际回复）/ `sleep`（真实等待）。
- **自解释要求**：`description`/`scenario` 必填、每个步骤可带 `note`——用例缺失必填说明时校验拒收（保存/运行时都会报错），保证用例可读、可审计。
- 校验规则（`loader.validate_case`）：name/description/scenario 非空；tags 字符串数组；group 用例必须给 group_id；steps 非空；send 需 player+text；expect 需 match 且 timeout>0；sleep 需 seconds>0。
- 每次运行：新建 `[用例] {name} #{run_index}` 临时会话（system-created，保留供人工批注）；写 `case_runs` 表：status / 逐步骤结果（含实际回复）/ `case_snapshot`（用例内容快照，可对比用例版本）/ `run_messages`（运行期全量消息交换快照）——**轨迹独立于会话持久化，删除会话不丢轨迹**。
- 运行入口：网页「运行」按钮、CLI `case run <name>` / `case run-all --tag <tag>`、REST `POST /api/cases/{name}/runs`（AI 自动化走此通道，留相同轨迹）。

## REST API 与 CLI 速查

| 用途 | REST | CLI |
|---|---|---|
| 会话 CRUD | `/api/conversations` GET/POST/PATCH/DELETE | `conversations list/create --kind private|group --member uid:nick/archive --id/delete --id` |
| 注入消息 | `POST /api/conversations/{id}/messages {sender,text}` | `send --conversation N --sender uid --text "闭关"` |
| 拉取消息 | `GET /api/conversations/{id}/messages?after=&limit=` | `feed --conversation N [--after N] [--json]` |
| 断言等待 | — | `wait --conversation N --expect "修炼中" --timeout 30 --after N`（命中退出码 0，超时 1，供脚本断言） |
| 批注 | `GET/POST/PATCH/DELETE /api/messages/{mid}/annotation` | `annotations --conversation N` / `annotate --message N --text "..."` |
| 用例 | `/api/cases` GET/POST、`/api/cases/{name}` GET/PUT/DELETE | `case list/new/show/run/run-all` |
| 运行记录 | `GET /api/cases/{name}/runs`、`GET /api/runs/{id}` | `runs list/show` |
| 状态 | `GET /api/status` | — |

- 认证：配置 `access_token` 后，`/api/*` 与 `/ws` 需 `Authorization: Bearer <token>`（或 `?token=` / `X-Access-Token`），否则 401。CLI 读 `WEBTEST_URL`（默认 http://127.0.0.1:8765）与 `WEBTEST_TOKEN`。
- WebSocket `/ws`：连接推快照（会话+玩家），`{type:"open", conversation_id}` 拉历史，消息/批注/会话/用例运行实时推送。

## 前端页面

- **会话页**：左侧会话列表（含归档标记），右侧消息流（玩家 in / 机器人 out 分色），底部输入框（选择发送者）；消息 hover 出现「批注」按钮，批注以黄色侧边条显示、可删除；新会话/归档在列表头操作。
- **用例页**：用例列表（标签徽标、按标签筛选）；详情含 description/scenario/会话类型/步数；「运行」按钮一键执行；运行记录列表按次查看：逐步骤结果（含期望/实际回复对比、note）、完整轨迹快照、一键跳转到该次运行会话（可继续人工批注）；「编辑 JSON」直接改用例文件。

## 配置项（_conf_schema.json，WebUI 可改）

| 键 | 默认 | 说明 |
|---|---|---|
| `host` | `127.0.0.1` | Web 服务监听地址（对外访问改 0.0.0.0） |
| `port` | `8765` | 监听端口 |
| `access_token` | `""` | 访问令牌；为空不鉴权 |
| `default_players` | 测试玩家1/2 | 新建私聊会话的默认玩家（`test_player_001/002`） |

配置优先级：Dashboard 平台配置（webtest 平台页）> 插件配置 > 默认值。

## 隔离性保证（对项目本体）

- 唯一新增目录 `testplatform_plugin/`；**不修改项目任何文件**（git diff 主树为空）。
- 允许 import 修仙插件/AstrBot 模块以复用逻辑（如构造与真实一致的消息对象），但**绝不反向修改**：不写插件数据、不改配置文件、不 patch 模块。
- 平台数据只存 `data/plugin_data/astrbot_plugin_testplatform/`；卸载插件后平台数据目录可整体删除。
- 验收方式：`git status` 主树零改动 + 插件目录既有 pytest 全绿（404 项）+ 本平台 32 项单测。

## 使用步骤（真实 AstrBot 环境）

1. 将 `testplatform_plugin/` 复制到 `~/code/AstrBot/data/plugins/` 下（AstrBot 插件市场/手动安装亦可）。
2. AstrBot Dashboard → 插件管理 → 重载插件；平台管理 → 启用「网页测试平台 (webtest)」，可改端口/令牌。
3. 浏览器打开 `http://127.0.0.1:8765/`：新建会话 → 发送「闭关」等指令，观察机器人回复；hover 消息写批注。
4. AI 侧：`python testplatform_plugin/scripts/test_platform_cli.py case run cultivate-basic-flow` 跑用例；`wait --expect` 做断言式交互测试。
5. 关闭平台：Dashboard 平台管理禁用 webtest，或卸载插件。
