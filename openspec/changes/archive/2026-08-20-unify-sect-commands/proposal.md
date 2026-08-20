# Proposal: unify-sect-commands

## Why

宗门系统在 `add-default-sects-and-sect-growth` 落地后已长成包含 18 个独立指令的大系统（创建/加入/退出/捐献/任务/丹房/建设/镇派功法/晋升/宝库/师承/踢人/传位/职位/排行等），且宗门专属悬赏混在全局「悬赏令」里以分区呈现。指令面分散、与全局系统入口纠缠，玩家难以发现"宗门专属的装备/心法/任务/悬赏"这一系列内容。本 change 将宗门全部功能收敛为 `/宗门` 单指令 + 子命令形式，并把宗门悬赏从全局悬赏中彻底拆出，让宗门拥有一套专属的指令入口。

## What Changes

- **统一指令入口**：新增 `/宗门` 指令，第一个参数为子命令（如 `/宗门 任务`、`/宗门 宝库 名称`）；无参数时输出子命令导航帮助。
- **BREAKING 移除旧独立指令**：删除 `创建宗门`/`加入宗门`/`退出宗门`/`我的宗门`/`宗门列表`/`宗门捐献`/`踢出成员`/`宗主传位`/`职位变更`/`宗门任务`/`宗门丹房`/`宗门建设`/`镇派功法`/`宗门晋升`/`宗门宝库`/`师承任务`/`宗门排行`/`贡献排行` 共 18 个顶层指令，全部迁移为 `/宗门` 子命令（排行两个一并并入），不保留兼容别名。
- **BREAKING 宗门悬赏独立**：宗门专属悬赏（`sect_id` 标记的模板）的查看/接取/进度/完成/放弃全生命周期移到 `/宗门 悬赏` 系列子命令下；全局「悬赏令」「接取悬赏」「悬赏状态」「完成悬赏」「放弃悬赏」只处理无宗门归属的悬赏，`bounty_handlers` 中的"🏯 宗门悬赏"分区移除。
- **BREAKING 宗门秘境仅本宗可见**：宗门专属秘境（`sect_id` + `access: "sect_member"`）在秘境列表中对非本宗成员不再展示（现为 🔒 锁定标注），仅本宗弟子可见可进。
- **宗门专属商店**：新增 `/宗门 商店` 子命令（宗门藏宝阁），商品池独立配置于 `sect_factions.json` 各宗门下，以宗门贡献点结算，可配置职阶解锁门槛；全局商店/阁楼不变，避免宗门商品混入随机池。
- **历练宗门事件显性标记**：触发宗门专属事件组时，结算消息增加「🏯 宗门际遇」标识与事件名（现仅输出 desc 文案，无任何宗门标识）。
- **GM 测试辅助**：新增 GM 子命令「清除悬赏」，清除目标玩家的进行中悬赏记录与放弃冷却（`system_config.bounty_abandon_cd_<uid>`），供功能测试与运营清理悬赏状态（现有「清除CD」不覆盖悬赏存储）。
- **联动行为不变**：秘境准入过滤、历练事件组过滤、领悟池注入、职阶福利（签到加发/商店折扣）、传承绑定与回收等既有联动逻辑保持原语义，仅入口搬迁与上述三点展示/可见性调整。

## Capabilities

### New Capabilities

- `sect-commands`: 宗门统一指令入口（`/宗门` 子命令路由、参数校验与导航帮助）、旧独立指令的移除、宗门悬赏与全局悬赏的入口与数据流分离、宗门秘境仅本宗可见、宗门专属商店、历练宗门事件显性标记。

### Modified Capabilities

- `gm-commands`: 新增 GM 子命令「清除悬赏」（清除进行中悬赏与放弃冷却的测试/运营辅助）。
- 注：`sect-system` 主 spec 尚在未归档 change `add-default-sects-and-sect-growth` 中，其「宗门内容联动」关于悬赏榜呈现的描述由本 change 的 `sect-commands` delta 取代；两个 change 归档时需按顺序应用，详见 design.md。

## Impact

- **代码**：`main.py`（删除 18 个指令常量与路由方法，新增 `/宗门` 路由）、`handlers/sect_handlers.py`（新增子命令分发器与参数解析、悬赏/商店子命令组）、`handlers/bounty_handlers.py`（移除宗门分区）、`managers/bounty_manager.py`（悬赏类型分流）、`managers/rift_manager.py`（专属秘境对非本宗隐藏）、`managers/sect_manager.py`（宗门商店逻辑）、`core/shop_manager.py`（复用职阶折扣）、`core/gm_manager.py`（新增「清除悬赏」）、`managers/adventure_manager.py`（宗门事件结算标记）、`handlers/ranking_handlers.py`（宗门排行入口迁移）、`handlers/misc_handler.py`（`/修仙帮助` 文本重写宗门章节）。
- **数据库/配置**：无 schema 变更；`bounty_templates.json`/`rift_config.json` 的 `sect_id` 语义不变（仅可见性收窄）；`sect_factions.json` 新增各宗门 `shop` 商品池配置。
- **测试**：`tests/` 宗门与悬赏相关单测更新；`functional_tests/cases/` 中宗门域用例的指令步骤需同步改写为 `/宗门` 子命令形式并重跑。
- **文档**：`design_docs/current-design-report.md` §4.8、`design_docs/api-overview.md`（指令→路由索引）、`README.md` 更新日志、`metadata.yaml` 版本。
- **兼容性**：**BREAKING**——旧指令全部失效，玩家需改用 `/宗门` 子命令；`/修仙帮助` 需明确列出新入口。
