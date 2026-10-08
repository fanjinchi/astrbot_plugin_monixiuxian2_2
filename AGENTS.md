# AGENTS.md — AstrBot 修仙插件开发指引

## 项目类型

AstrBot 插件（文字修仙游戏），Python 插件。作为 AstrBot 的子目录运行，依赖 AstrBot 提供的运行环境与 API，无独立构建系统。

## 开发环境

- **插件目录**：`~/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2/`
- **宿主项目**：AstrBot 本体位于 `~/code/AstrBot/`，用 **uv** 管理虚拟环境与依赖（Python >=3.12）；依赖在 AstrBot 根目录执行 `uv sync`（本插件无额外依赖，无需安装任何包）
- **命令前缀**：本目录未配置独立解释器，一律使用 AstrBot 的 uv 环境：

  ```bash
  uv run python -m pytest tests/ -v
  uv run ruff format .
  uv run ruff check .
  ```

  也可在 AstrBot 根目录针对插件路径执行：`uv run ruff format data/plugins/astrbot_plugin_monixiuxian2_2/`

## 架构速览

- `main.py` — 插件入口：命令路由、定时任务初始化；core 服务由 `_wire_core_services()` 装配段统一注入（文件名必须为 main.py）
- `handlers/` — 指令处理器（按系统分类）；`managers/` — 业务逻辑（战斗、宗门、Boss 等）；`core/` — 通用工具（修炼、丹药、装备、储物戒）
- `data/` — 数据库封装 + 迁移；`config/` — JSON 静态配置；`config_manager.py` — 配置加载器（自动创建默认配置）
- `models.py` / `models_extended.py` — Player 数据模型 / UserStatus 等扩展模型
- `metadata.yaml` — 插件元数据；`_conf_schema.json` — WebUI 可视化配置 Schema；`logo.png` — 插件 Logo（可选）
- 完整目录索引与指令→handler→manager→core→data 全链路见 `design_docs/api-overview.md`

## AstrBot 官方开发原则（必须遵守）

> 违反会导致插件无法正常运行或被拒收。

1. 所有 Handler 必须定义在插件类（`Star` 子类）中，文件名必须为 `main.py`
2. Handler 前两个参数必须为 `self` 和 `event`（`AstrMessageEvent` 类型）
3. 持久化数据必须存储在 `data/plugin_data/{plugin_name}/` 下，绝不能存在插件自身目录
4. 禁止使用 `requests`，必须用异步库（`aiohttp`、`httpx`）
5. 提交前用 `uv run ruff format . && uv run ruff check .` 格式化并检查
6. 良好的错误处理，不让插件因单个错误崩溃
7. 功能需经过测试，需包含注释

## 关键开发规范

### 1. 新增指令的正确位置

- `main.py` 定义 `CMD_XXX` 常量 + `@filter.command(CMD_XXX)` 方法，方法必须加 `@require_whitelist`（已在 main.py 定义）
- 业务逻辑优先写在 `handlers/xxx_handler.py`，复杂逻辑委托 `managers/` 或 `core/`；处理器在 `handlers/__init__.py` 导出，并在 `main.py` 顶部 import
- 指令名不能带空格（AstrBot 将空格后内容解析为参数）；本项目用纯中文指令（如 "闭关"）
- 装饰器顺序：`@filter.command(...)` 在外层，`@require_whitelist` 在内层

### 2. 状态检查是双层的（由 BusyState 统一承接，勿手动同步）

玩家忙碌状态的读写一律由 `BusyState`（`core/busy_state.py`）承接，禁止绕过它手动写任意一层：

- `player.state`（字符串："空闲"、"修炼中" 等）——内存镜像（仅展示/快进选择器用）
- `user_cd` 表（数据库，`type` 对应 `UserStatus` 枚举）——唯一真相（busy 判定一律以 user_cd 为准）

- 处理器默认用 `@player_required` 装饰器（`handlers/utils.py`；白名单命令在 `BUSY_STATE_ALLOWED_COMMANDS`）；自定义守卫用 `BusyState.assert_idle(user_id, template=...)`，不要手写 user_cd/state 判断
- 新增"进行中"活动系统：`UserStatus` 加枚举值 → 按需更新 `BUSY_STATE_ALLOWED_COMMANDS` → 开始/结束走 `BusyState.set_busy(player, status, scheduled_time, extra_data=...)` / `clear(player)`，双写（user_cd + 待落库 player 字段）包在调用方同一 `async with db.transaction():` 内
- 例外：GM force-settle（`core/gm_manager.py` 的 `update_user_cd` 直写）仅 bump `scheduled_time`、非常态忙碌写入，保留直连
- 新增**等待类冷却域**（任何参与到期/冷却判定的时间戳字段，如新的周期活动、冷却表、system_config 到期键）必须登记 GM「时间快进」字段覆盖清单（`core/time_skip_registry.py` 注册表：属主模块声明 `TIME_SKIP_ENTRIES` 并在 `_PROVIDER_MODULES` 登记，见 openspec change gm-time-skip-registry）——否则新冷却不被快进覆盖，冷却类测试会隐性失败。覆盖域字符串由注册表 label 去重自动生成，新增域无需手改 GM 帮助

### 3. 数据库操作规范

- 使用 **aiosqlite**，所有操作都是 async
- 多语句事务（unit-of-work）统一使用 `async with db.transaction() as txn:`（`DataBase.transaction()`，seam 在 data/data_manager.py 返回 `_TransactionCM`）；BEGIN/COMMIT/ROLLBACK 由 CM 管理，业务模块不自管事务；单语句写操作可直接 `await db.execute(...)`（叶子 helper 按 `conn._txn_depth` 门控自动提交）
- 任何手工提交点未来包进 CM 时，必须删除块内裸 `conn.commit()`（残留 = 提前提交 bug）；CM 不得进入 raw `BEGIN IMMEDIATE` 块内部
- 并发语义：同任务嵌套 = no-op join（仅 owner 提交）；跨任务互斥——事务归属 `conn._txn_owner_task`，后到者等待串行，禁止静默共享事务（详见 design D1.2）
- 定时任务中先 `await db.ensure_connection()` 再操作
- 数据库路径由 `StarTools.get_data_dir("astrbot_plugin_monixiuxian2_2")` 决定，不要写死；新增表在 `data/migration.py` 写迁移脚本（`migrate()` 自动按版本执行）

### 4. 数据存储规范（AstrBot 官方要求）

- 简单 KV 存储（v4.9.2+）：`self.put_kv_data()` / `get_kv_data()` / `delete_kv_data()`
- 大文件/自定义数据：必须存到 `data/plugin_data/astrbot_plugin_monixiuxian2_2/` 下

  ```python
  from astrbot.core.utils.astrbot_path import get_astrbot_data_path
  plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_monixiuxian2_2"
  ```

- 严禁在插件自身目录存放用户数据或运行时状态

### 5. 配置系统

- **静态配置**：`config/*.json`（境界、物品、武器、丹药、配方等），修改后需重启 AstrBot 生效；`config_manager.py` 自动加载，文件缺失时从 `data/default_configs.py` 创建默认值
- `config/narrative_config.json` 是同步脚本生成物：同步域场景（CSV 有行）以 `design_docs/content-design/copy_variants.csv` 为准（§15 流程），手改 FORBIDDEN；非同步域场景（`legacy_encounter` 等）手改保留现值
- **动态配置**：经 `_conf_schema.json` 暴露给 AstrBot WebUI，运行时经 `AstrBotConfig` 传入 `__init__`；支持高级字段（`type: "dict"` + `template_schema`、`"template_list"`、`"file"` 等）

### 6. metadata.yaml 规范

- `display_name`：插件在市场中显示的友好名称
- `support_platforms`：声明支持的平台适配器列表（如 `aiocqhttp`, `telegram`, `discord`）
- `astrbot_version`：声明要求的 AstrBot 版本范围（如 `">=4.16,<5"`，不加 `v` 前缀）

### 7. 版本更新 checklist（必须做）

任何功能更新或 Bug 修复后，同步更新：

1. `metadata.yaml` 中的 `version`
2. `README.md` 的更新日志（末尾追加）
3. `handlers/misc_handler.py` 中的 `/修仙帮助` 文本
4. 涉及数据库变更时，在 `data/migration.py` 添加迁移版本
5. 影响游戏玩法时，同步 `design_docs/` 中涉及的设计资料（见 §14）

### 8. 代码风格

- 所有用户可见输出与命令字符串用中文（如 "闭关"、"突破"）
- 消息状态符（❌/✅/⚠️/🎯 等）一律由 manager/core 服务层自带完整文案，handler 裸渲染 `msg`、禁止再包 ✅/❌ 前缀：同一服务方法常被多个入口（全局指令/宗门子命令）消费，只有服务层自带 emoji 才能保证各入口输出一致；handler 仅对自身的参数/入口校验文案负责（参考实现 bounty/bank/储物戒/装备/丹药 域）
- 服务层消息嵌入自己的包装头（如「❌ 结算失败：{msg}」「✅ 已卸下…：{msg}」）时，内嵌 msg 须先 `removeprefix('❌ ')`/`removeprefix('✅ ')` 去重（按包装头的符号选择对应前缀），保证整条消息以单一状态符开头
- 例外：返回 `\n` 或 `\n\n` 开头、供调用方拼接到主消息尾部的片段（如 📜 进度提示、`f"\n{unequipped_item_name} 已自动存入储物戒"`）自带内容符号，由调用方原样拼接、不再加状态头
- 战力公式单一实现在 `Player.combat_power`（models.py）；公式文本以 `design_docs/current-design-report.md` 为权威，改动须同步 design_docs（§14）

### 9. 消息发送注意事项

- 群聊广播：`self.context.send_message(umo, message_chain)`，`umo` 格式 `{platform}:GroupMessage:{group_id}`
- aiocqhttp 陷阱：`plain` 消息发送时会自动 `strip()` 首尾空白；需保留空白时在消息前后加零宽空格 `\u200b`
- 事件钩子中不能 `yield` 发送消息，必须用 `event.send()`（适用于 `on_llm_request`、`on_decorating_result` 等）
- `event.stop_event()` 可阻止后续插件和 LLM 请求执行

### 10. 定时任务

- `main.py` 的 `initialize()` 启动全部后台任务（Boss生成、贷款检查、灵眼生成、悬赏过期检查）
- 所有定时任务必须包含指数退避重试（参考 `_schedule_boss_spawn`）

### 11. 调试与热重载

- AstrBot 采用运行时注入，改代码后不自动生效：WebUI 插件管理 → 本插件 → 右上角 `...` → 重载插件；加载失败可点"尝试一键重载修复"

### 12. 文转图（可选）

- `await self.text_to_image(text)` — 简单文本转图片
- `await self.html_render(TMPL, data, options=options)` — HTML + Jinja2 模板渲染图片（选项参考 Playwright screenshot API）

### 13. 新增系统的标准接入点

新增子系统（如"灵兽系统"）按此模板：

1. `core/beast_manager.py` — 核心逻辑
2. `managers/beast_manager.py` — 业务封装（如需）
3. `handlers/beast_handlers.py` — 指令处理
4. `handlers/__init__.py` — 导出 Handler
5. `main.py` — 在 `_wire_core_services()` 装配段实例化服务/Manager 并注入 Handler、注册命令；**禁止在 handler/manager 内自构造核心服务**（core 单例一律由装配段注入）
6. 如有数据库表 → `data/migration.py` 添加迁移

### 14. 玩法变更必须同步 design_docs（必做）

任何影响游戏玩法的改动（数值、机制、平衡、战斗、技能、成长曲线、掉落/概率等）都必须在 `design_docs/` 记录或修正，使设计资料与代码实现保持一致：

- 内容设计（武器/功法/心法数值、品级、触发技等）→ `design_docs/content-design/` 对应 CSV/MD
- 数值框架（属性成长、镜像战 TTK、加成、经验曲线）→ `design_docs/attribute-growth/`、`design_docs/level-exp-curve/`
- 整体架构/数值基线 → `design_docs/current-design-report.md`
- 相关描述过时则直接修正；新增资料登记到 `design_docs/README.md` 资料清单
- 纯 bug 修复（行为与设计意图不变）不要求；拿不准按"影响玩法"处理
- 正式变更提案仍走 OpenSpec 流程（`openspec/changes/`），design_docs 只负责保持"设计事实"与实现同步

### 15. 内容设计先行：剧情/数值内容必须先进 design_docs（必做）

一切可配置的游戏内容（剧情文案、武器/功法/心法/丹药/材料数值、事件、悬赏、秘境、敌人等）一律先在 `design_docs/` 完成设计，禁止直接改 `config/*.json`：

1. **策划阶段**：基调与规范查 `design_docs/world-bible.md`，季度计划查 `design_docs/season-1-outline.md`；条目登记进 `design_docs/content-design/` 的 canon 表（含数值写全列，无数值写轻量叙事表），数值/玩法类写进对应 CSV（draft 行）；设计期自检 `lint_narrative.py` + `validate_budget.py`
2. **用户确认**：设计就绪后必须等用户手动确认，不由 AI 自行入库
3. **导入阶段**（用户发起导入任务）：经 `scripts/sync_content_to_config.py`（预算 + 叙事 lint 双闸门）导入 config；反向补登记用 `scripts/export_config_to_canon.py`；导入后按 §14 同步文档、跑测试与质量门

唯一例外：**工程性 config 变更**（新增字段、结构调整，如 rift 加 description）走 OpenSpec 工程变更，不算内容填充。

## 测试

- 使用 pytest；因插件的 `managers/__init__.py` 包含相对导入，直接从 AstrBot 根目录运行 pytest 会失败
- 用 `tests/helpers.py` 的 `load_module()` 加载模块，绕过 `__init__.py` 链：

  ```python
  from tests.helpers import load_module
  _mod = load_module("combat_manager", "managers/combat_manager.py")
  CombatManager = _mod.CombatManager
  ```

- 运行：在插件目录执行 `uv run python -m pytest tests/ -v`（本插件无独立解释器，始终用 `uv run python`）

## 网页端测试平台（功能验证与反馈闭环）

贴近真实环境的测试平台：模拟玩家私聊/群聊消息走 AstrBot 真实管线（filter → Handler → 白名单 → 数据库 → 定时任务），消息流双向可见、可批注、可自动化。设计文档：`design_docs/test-platform.md`；插件代码在独立仓库 `~/code/AstrBot/data/plugins/astrbot_plugin_testplatform/`（独立 git 仓库，不在本仓库维护）。

- **操作细节一律以 SKILL.md 为准**：`.agents/skills/testing-astrbot-plugins-via-webtest` 是指向测试平台仓库 `skill/` 的符号链接（由平台「Skill 分发」弹层维护，勿手动编辑链接内文件）；手动探测、JSON 用例编写与回归、热重载、批注读取等见该 SKILL.md。本节只保留项目级约定：
- 启用前提：Dashboard → 平台管理 → 启用「网页测试平台」；入口 `http://127.0.0.1:8765`（或 Dashboard 插件详情嵌入版）；`/api/status` 应返回 `adapter_ready: true`
- 反馈闭环：用户批注 → 按 SKILL.md 工作流 D 拉取 → 改插件代码 → 热重载（`POST /api/ops/plugin-reload`，与 Dashboard 重载同一底层但不走登录态）→ 重跑用例/`wait` 断言确认 → 汇报
- **真实环境功能测试由用户手动发起（2026-08-30 定）**：AI 不主动跑平台用例（含 `test_suite_ctl.py run`、平台 CLI、热重载后回归），写完代码以 `pytest tests/` + ruff 为质量门即可收尾；需要真实环境回归时由用户自行运行或明确指示后才执行
- 改动同步：插件代码改动提交到独立仓库；`design_docs/test-platform.md` 按独立仓库实际代码修正（无自动同步）

## 功能测试套件（项目内用例与结果归档）

统一存放功能测试用例与结果：`functional_tests/`（用例源在 `functional_tests/cases/<domain>/<name>.json`，平台数据目录只保留同步副本）。**所有操作命令、概率效果口径（`--repeat` 非抽样）、fixture profile 清单、并发约束详见 `functional_tests/README.md`**，本节只保留义务：

- 用例 `name` 必须等于文件名且全局唯一；JSON 兼容平台 `loader.validate_case`（必填 `description`/`scenario`/`steps`，`owner` = `astrbot_plugin_monixiuxian2_2`）；可声明 `pre_run_hook`（宗门用例已内嵌 fixture 复位）
- 同步走 `uv run python scripts/test_suite_ctl.py sync-cases`：扫描校验 → 注入缺失 `owner` → 复制到平台目录；无源文件的残留 JSON 逐个告警（不删除），需回填源文件后重新 sync
- 运行/归档：`test_suite_ctl.py run --tag <tag> | --case <name>`（推荐 one-shot：`run --sync --reload astrbot_plugin_monixiuxian2_2 --export <dir> [--quiet]`）、`export --target <target>` 写 `functional_tests/results/<YYYY-MM-DD>_<target>/`；或平台 CLI `test_platform_cli.py case run[-all]`（`WEBTEST_URL`/`WEBTEST_TOKEN`；⚠ 分域子目录源必须走 sync-cases，平台 CLI glob 非递归）
- fixture（兼容保留）：`fixture --profile pvp|sect` 向专用测试实例写入固定测试 ID（`900000001`/`900000002`/`900000003`，sect 另含新建型 `900000004`/`900000005`/`900000006`/`900000008`）基线并清除冷却/忙碌；⚠ 仅限独立测试实例，禁止对正式数据执行
- 新玩法变更后：先查 `functional_tests/` 对应域用例，有则补/改并跑一次 tag；功能 Bug 用 `bd` 登记，不在套件内直接修游戏代码
- 平台能力边界：`functional_tests/platform-gap-report.md`（Supported / Partially supported / Unsupported），新用例优先只依赖 Supported 能力

## 文档地图（必读与维护）

开始任何任务前，先按下表选读对应文档快速定位；完成任务后，按"维护责任"同步文档：

| 文档 | 内容 | 何时读 | 维护责任（何时必须更新） |
|---|---|---|---|
| `design_docs/api-overview.md` | 关键 API 速查：指令→main.py 路由→handlers→managers→core→data 全链路索引与检索路径 | 定位代码、理解调用链 | 新增/重命名公开方法、新增子系统 |
| `design_docs/project-architecture.md` | 架构与系统功能设计总览（分层架构+mermaid 图、20 子系统设计表、openspec 契约、里程碑时间线、bd 对照） | 新增/修改功能、理解系统边界 | 新增子系统、架构变更、openspec spec 增删、里程碑节点 |
| `design_docs/current-design-report.md` | 数值/机制设计活基线（含 `file:line` 引用） | 改数值、改战斗/技能/成长 | 任何影响玩法的修改（同 §14） |
| `design_docs/README.md` | design_docs 全部资料清单与类型标注 | 找专题资料（成长/曲线/内容设计/竞品） | 新增 design_docs 资料时登记 |
| `openspec/specs/` | 行为契约（每篇一目录，当前 16 篇，What/Why 与 Accept 公式） | 改技能/战斗/装备/数值前 | 走 OpenSpec 提案流程（见 §14） |

**注释约定**：

- 运行时代码（main.py、handlers/、managers/、core/、data/、utils/）非 dunder 函数/类均有 docstring（含方法内的嵌套辅助函数；design_docs/ 下的调研脚本除外）；**新代码一律用英文 Google 风格 docstring**（存量中文保留，不强制改写），用户可见输出仍为中文
- main.py 的路由方法（`@filter.command`，当前 93 个）docstring 遵循固定格式：`"""Command 「指令名」- 描述; routes to xxx_handler.handle_yyy."""` — 新指令照此格式写，它是 AI 定位的第一跳
- 修改函数行为时同步更新其 docstring；docstring 与实现不一致视为 bug
- 行内注释解释"为什么"而非复述代码：非显然逻辑必须注释，包括数值公式/阈值的出处（config 键或 design_docs 引用）、平台/框架陷阱的 workaround（如 aiocqhttp strip 用零宽空格）、事务与并发约束、有意为之的取舍；改动涉及的存量过时注释一并修正或删除，过时注释与过时 docstring 同视为 bug

## Issue Tracking with bd (beads)

**IMPORTANT**: 本项目所有 issue 追踪一律用 **bd (beads)**，禁止 markdown TODO 与外部 issue 追踪器。程序化使用一律加 `--json`；关联工作用 `discovered-from` 依赖。

```bash
bd ready --json
bd create "Issue title" --description="Details" -t bug|feature|task -p 0-4 --json
bd update <id> --claim --json
bd close <id> --reason "Done" --json
```

## Session Completion

结束工作会话时，MUST 完成：

1. **为剩余工作建档** — 用 bd 创建待办 issue
2. **质量门** — `uv run ruff format . && uv run ruff check .`；代码变更后运行 `uv run python -m pytest tests/ -v`
3. **更新 issue 状态** — 关闭已完成、更新进行中项
4. **本地 commit** — conventional commit（如 `feat: add new agent for data analysis`、`fix: resolve bug in provider manager`）
5. **验证** — `git status` 干净工作树（本地 commit 即可）

**CRITICAL RULES:**

- push 到远程由用户决定——未经明确要求不 `git push`；报告本地 commit 即可，不阻塞任务完成
<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->