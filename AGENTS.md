# AGENTS.md — AstrBot 修仙插件开发指引

## 项目类型
AstrBot 插件（文字修仙游戏），Python 插件，无构建系统。

## 架构速览
```
main.py              # 插件入口：命令路由、定时任务初始化（文件名必须为 main.py）
handlers/            # 指令处理器（按系统分类）
managers/            # 业务逻辑管理器（战斗、宗门、Boss 等）
core/                # 通用工具管理器（修炼、丹药、装备、储物戒）
data/                # 数据库封装 + 迁移
config/              # JSON 静态配置（境界、物品、配方等）
models.py            # Player 数据模型
models_extended.py   # UserStatus 等扩展模型
config_manager.py    # 配置加载器（自动创建默认配置）
metadata.yaml        # 插件元数据（AstrBot 识别插件依赖此文件）
_conf_schema.json    # AstrBot 可视化配置 Schema
requirements.txt     # 插件依赖（pip 格式）
logo.png             # 插件 Logo（可选，推荐 256x256）
```

## AstrBot 官方开发原则（必须遵守）

> 以下规则来自 AstrBot 官方文档，违反会导致插件无法正常运行或被拒收。

1. **所有 Handler 必须在插件类（`Star` 子类）中定义**，文件名 **必须** 为 `main.py`
2. **Handler 前两个参数必须为 `self` 和 `event`**（`AstrMessageEvent` 类型）
3. **持久化数据必须存储在 `data/plugin_data/{plugin_name}/` 下**，绝不能存在插件自身目录，否则更新/重装时数据被覆盖
4. **不要使用 `requests` 库进行网络请求**，必须使用异步库（`aiohttp`, `httpx`）
5. **提交前使用 `ruff` 格式化代码**
6. **良好的错误处理**，不要让插件因单个错误而崩溃
7. **功能需经过测试**，需包含注释

## 关键开发规范

### 1. 新增指令的正确位置
- **命令注册**：`main.py` 中定义 `CMD_XXX` 常量 + `@filter.command(CMD_XXX)` 方法
- **方法必须加 `@require_whitelist`**（已在 main.py 定义的装饰器）
- **业务逻辑**：优先写在 `handlers/xxx_handler.py`，复杂逻辑委托给 `managers/` 或 `core/`
- **处理器必须在 `handlers/__init__.py` 导出**，并在 `main.py` 顶部 import
- **指令名不能带空格**，否则 AstrBot 会将空格后内容解析为参数。本项目使用纯中文指令（如 "闭关"），天然无空格问题；若新增带空格的英文指令，请改用指令组或自行解析参数

### 2. 状态检查是双层的（极易踩坑）
玩家忙碌状态由两个独立系统维护，修改时必须同步：
- `player.state` 字段（字符串）："空闲"、"修炼中"、"历练中" 等
- `user_cd` 表（数据库）：`type` 字段对应 `UserStatus` 枚举

- 处理器方法应使用 **`@player_required`** 装饰器（在 `handlers/utils.py`），它会同时检查两者
- 白名单命令在 `BUSY_STATE_ALLOWED_COMMANDS`（`handlers/utils.py`），忙碌时只允许查看类指令
- 若新增"进行中"的状态（如新的活动系统），必须：
  1. 在 `models_extended.py` 的 `UserStatus` 添加枚举值
  2. 更新 `BUSY_STATE_ALLOWED_COMMANDS`（如需要）
  3. 在操作开始时写入 `user_cd` 表，结束时清除
  4. 同步更新 `player.state`

### 3. 数据库操作规范
- 使用 **aiosqlite**，所有操作都是 async
- **事务保护**：并发敏感操作（购买、存取、战斗结算）必须使用 `await db.conn.execute("BEGIN IMMEDIATE")` + `commit/rollback`
- **自动重连**：定时任务中调用 `await db.ensure_connection()` 后再操作（Boss生成、贷款检查等已做示范）
- 数据库路径由 `StarTools.get_data_dir("astrbot_plugin_monixiuxian2")` 决定，不要写死路径
- 新增表需在 `data/migration.py` 中写迁移脚本，`migrate()` 会自动按版本执行

### 4. 数据存储规范（AstrBot 官方要求）
- **简单 KV 存储**（v4.9.2+）：使用 `self.put_kv_data()`, `self.get_kv_data()`, `self.delete_kv_data()`，每个插件有独立命名空间
- **大文件/自定义数据**：必须存到 `data/plugin_data/astrbot_plugin_monixiuxian2/` 下，可通过以下方式获取路径：
  ```python
  from astrbot.core.utils.astrbot_path import get_astrbot_data_path
  plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_monixiuxian2"
  ```
- **严禁** 在插件自身目录存放用户数据或运行时状态（如数据库、用户配置文件、缓存等）

### 5. 配置系统
- 静态配置放在 `config/*.json`（境界、物品、武器、丹药、配方等）
- `config_manager.py` 会自动加载 JSON；若文件不存在，会从 `data/default_configs.py` 创建默认值
- 动态/用户可调配置通过 AstrBot 的 `_conf_schema.json` 暴露给控制台，运行时通过 `AstrBotConfig` 传入 `__init__`
- `_conf_schema.json` 支持高级字段：
  - `_special`: `select_provider`, `select_persona`, `select_knowledgebase` 等可视化选择器
  - `type: "file"`（v4.13.0+）：引导用户上传文件
  - `type: "dict"` + `template_schema`：可视化编辑字典配置
  - `type: "template_list"`（v4.10.4+）：模板列表配置
- **修改 `config/*.json` 静态配置后需重启 AstrBot 生效**（`_conf_schema.json` 的动态配置通过 WebUI 修改即时生效）

### 6. metadata.yaml 规范
AstrBot 识别插件元数据依赖此文件，除基础字段外还支持：
- `display_name`: 插件在市场中显示的友好名称
- `support_platforms`: 声明支持的平台适配器列表（如 `aiocqhttp`, `telegram`, `discord`）
- `astrbot_version`: 声明要求的 AstrBot 版本范围（如 `">=4.16,<5"`，不要加 `v` 前缀）

### 7. 版本更新 checklist（必须做）
任何功能更新或 Bug 修复后，同步更新：
1. `metadata.yaml` 中的 `version`
2. `README.md` 的更新日志（末尾追加）
3. `handlers/misc_handler.py` 中的 `/修仙帮助` 文本
4. 若涉及数据库变更，在 `data/migration.py` 添加迁移版本
5. `plugins.json`（如有必要）

### 8. 代码风格
- 所有用户可见输出用中文
- 命令字符串用中文（如 "闭关"、"突破"）
- 装饰器顺序：`@filter.command(...)` 在外层，`@require_whitelist` 在内层（参考现有代码）
- 战力公式统一：`物伤 + 法伤 + 物防 + 法防 + 精神力/10`（已在 `ranking_manager.py` 和 `combat_manager.py` 中统一）

### 9. 消息发送注意事项
- **广播消息到群聊**：使用 `self.context.send_message(umo, message_chain)`，`umo` 格式：`{platform}:GroupMessage:{group_id}`
- **aiocqhttp 适配器陷阱**：`plain` 类型的消息在发送时会自动 `strip()` 去除首尾空格/换行。如需保留空白，在消息前后添加零宽空格 `\u200b`
- **事件钩子中不能使用 `yield` 发送消息**，必须使用 `event.send()`（适用于 `on_llm_request`, `on_decorating_result` 等钩子）
- **停止事件传播**：在 handler 中调用 `event.stop_event()` 可阻止后续插件和 LLM 请求执行

### 10. 定时任务
- `main.py` 中 `initialize()` 启动所有后台任务（Boss生成、贷款检查、灵眼生成、悬赏过期检查）
- 所有定时任务必须包含 **指数退避重试**（参考 `_schedule_boss_spawn`）
- 广播消息到群聊使用 `self.context.send_message(umo, message_chain)`

### 11. 调试与热重载
- AstrBot 采用**运行时注入**机制，代码修改后不会自动生效
- 在 AstrBot WebUI 插件管理处找到本插件 → 点击右上角 `...` → **重载插件**
- 插件加载失败时，可点击 **"尝试一键重载修复"**

### 12. 文转图（可选）
AstrBot 原生支持文转图，本项目已使用 Pillow 生成个人信息卡片。若需更复杂的图片渲染：
- `await self.text_to_image(text)` — 简单文本转图片
- `await self.html_render(TMPL, data, options=options)` — 基于 HTML + Jinja2 模板渲染图片（支持 CSS）
- 渲染选项参考 Playwright screenshot API（`timeout`, `type`, `full_page`, `omit_background` 等）

### 13. 新增系统的标准接入点
若新增一个子系统（如 "灵兽系统"），按此模板：
1. `core/beast_manager.py` — 核心逻辑
2. `managers/beast_manager.py` — 业务封装（如需）
3. `handlers/beast_handlers.py` — 指令处理
4. `handlers/__init__.py` — 导出 Handler
5. `main.py` — 初始化 Manager/Handler、注册命令
6. 如有数据库表 → `data/migration.py` 添加迁移

<!-- BEGIN BEADS INTEGRATION v:1 profile:full hash:0a1bbe8a -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Quality
- Use `--acceptance` and `--design` fields when creating issues
- Use `--validate` to check description completeness

### Lifecycle
- `bd defer <id>` / `bd supersede <id>` for issue management
- `bd stale` / `bd orphans` / `bd lint` for hygiene
- `bd human <id>` to flag for human decisions
- `bd formula list` / `bd mol pour <name>` for structured workflows

### Auto-Sync

bd automatically syncs via Dolt:

- Each write auto-commits to Dolt history
- No manual export/import needed!

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->
