# Proposal: add-default-sects-and-sect-growth

## Why

现有宗门系统是纯玩家自建的骨架实现：仅创建/加入/捐献/随机任务/职位/排行可用，`sects` 表预留的洞天、丹房、镇派功法字段全部未接线，与功法/悬赏/秘境/历练等核心系统零联动，也没有任何系统势力或剧情载体。本 change 引入**配置驱动的默认宗门**（系统势力，兼作新手出身地），并落地宗门建设、师承任务线、职阶晋升三个新机制，让宗门成为串联玩法与叙事的枢纽。全部内容走 JSON 配置，供策划后续调整。

设计基线文档：`design_docs/sect-system-design.md`（含已拍板决策与策划配置速查表）。

## What Changes

- **默认宗门**：新增 `config/sect_factions.json` 定义系统宗门（一期示例 2 个）；启动时幂等播种进 `sects` 表（新增 `is_system`/`faction_id` 等列）。玩家可拜入（按境界区间校验）、自由出师；「加入宗门」指令合并为统一入口按宗门类型分流。
- **宗门绑定物**：传承功法/心法（`sect_bound`）具有"只可传予本宗之人"的固有属性（不可交易/赠予/抄录），离宗后本人已习得的仍可正常使用；宗门之宝（`treasure` 武器/防具）仅授予使用权，离宗时回收归还宗门。
- **宗门建设**：接线 `sect_fairyland`（全员修炼加成）、`elixir_room_level`（丹房解锁，接线 `sect_elixir_get`）、`mainbuff/secbuff`（镇派功法 buff）；升级消耗资材+建设度；接线现有死配置 `scale_ratio`。
- **师承任务线**：新增 `config/sect_tasks.json`，默认宗门按境界段提供多阶段引导任务链（复用现有行为计数），奖励贡献点与宗门功法领悟机会，文案以 `elders` 署名。
- **职阶晋升**：`sect_config.json` 职位扩展 `promotion`（贡献+境界双门槛）与 `benefits`（每日灵石并入签到、商店折扣、传承解锁）；新增「宗门晋升」指令。
- **内容联动**：`skills.json` 新增宗门功法池、`heart_methods.json`/`weapons.json` 增加宗门归属字段、`bounty_templates.json`/`rift_config.json`/`adventure_config.json` 增加 `sect_id` 过滤。
- **二期预留**：`sects` 表毁灭状态列、faction 配置 `destruction` 结构、NPC `elders` 槽位一并定型，本期不实现毁灭/NPC 行为。

## Capabilities

### New Capabilities

- `sect-system`: 默认宗门（系统势力）的播种/拜入/出师、宗门绑定物归属与回收、宗门建设（洞天/丹房/镇派功法）、师承任务链、职阶晋升与福利、宗门内容联动（悬赏/秘境/历练/商店折扣过滤）。

### Modified Capabilities

- `skill-system`: 「领悟随机池与来源规则」扩展——领悟池按玩家所属宗门注入宗门专属功法池；宗门功法的 `sect_bound` 固有属性标记（只可传予本宗之人，不可转让，离宗后本人仍可用）。

## Impact

- **数据库**：`data/migration.py` 新迁移版本（`sects` 加列、`player_skills` 加归属列）；`models_extended.py`/`models.py` 模型同步。
- **配置**：新增 `sect_factions.json`、`sect_tasks.json`；扩展 `sect_config.json`、`skills.json`、`heart_methods.json`、`weapons.json`、`bounty_templates.json`、`rift_config.json`、`adventure_config.json`；`config_manager.py` 与 `data/default_configs.py` 注册加载与默认值。
- **代码**：`managers/sect_manager.py`（重构+新机制）、`core/skill_manager.py`、`core/shop_manager.py`（折扣）、`managers/bounty_manager.py`、`managers/rift_manager.py`、`managers/adventure_manager.py`、`handlers/sect_handlers.py`、`handlers/misc_handler.py`（签到福利、帮助文本）、`main.py`（新指令、播种调用）。
- **测试**：`tests/` 新增宗门单测；功能测试由配套 change `add-sect-functional-tests` 覆盖。
- **文档**：`design_docs/current-design-report.md` §4.8 重写、`api-overview.md`、`project-architecture.md`、`README.md` 更新日志、`metadata.yaml` 版本。
- **非目标（二期/三期）**：宗门毁灭与重建玩法、Boss 配置化、世界事件调度抽象、NPC 人格化、分宗、正魔阵营、宗门大比。
