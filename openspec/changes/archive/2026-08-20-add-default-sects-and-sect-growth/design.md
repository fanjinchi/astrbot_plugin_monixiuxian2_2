# Design: add-default-sects-and-sect-growth

## Context

现状约束（详见 `design_docs/sect-system-design.md` 与 proposal.md）：

- 宗门仅玩家自建，`sects` 表无系统标记；`sect_fairyland`/`elixir_room_level`/`mainbuff/secbuff` 为未接线预留字段。
- 职位权限有两套互不消费的 definition（`sect_manager.py` `POSITION_PERMISSIONS` 死定义 + `sect_config.json` permission 数值）；`scale_ratio` 配置未接线（硬编码于 `sect_manager.py:229`、`database_extended.py:148`）。
- 功法领悟池已有分组先例（通用/灵修/体修/传承 4 池，`config/skills.json`）；心法/武器配置为平铺列表。
- 物品存储惯例：玩家物品走储物戒 JSON 字段，功法走 `player_skills` 表（v25）。
- 配置通道惯例：`config/*.json` + `config_manager.py` 加载 + `data/default_configs.py` 播种默认值，重启生效。

## Goals / Non-Goals

**Goals:**

- 默认宗门与玩家宗门统一存储、统一建设/晋升机制，差异仅由配置与 `is_system` 标记表达。
- 所有宗门内容（宗门定义、任务、晋升门槛、福利、联动内容）JSON 可配，策划改配置不改代码。
- 二期（毁灭重建）与三期（NPC）的配置结构与存储字段一次定型，一期不实现其行为。

**Non-Goals:**

- 不实现毁灭触发/散落/重建玩法、Boss 配置化、世界事件调度抽象（二期）。
- 不实现 NPC 人格化、分宗、正魔阵营、宗门大比（三期）。
- 不抽象通用"世界事件调度器"——一期无定时事件需求，避免过度设计。

## Decisions

### D1: 默认宗门复用 `sects` 表 + `is_system` 标记，而非独立表

默认宗门与玩家宗门共享建设度/资材/建筑字段与成员关系，独立表会迫使所有宗门逻辑写两遍。加 `is_system`、`faction_id`（关联 `sect_factions.json`）、`status`、`destruction_tier`（后两者二期消费）四列。
**备选**：独立 `system_sects` 表——否决，成员加入/贡献/排行逻辑无法复用。

### D2: faction 播种为"启动时幂等 upsert"

`sect_manager.ensure_system_sects()` 在 `main.py` 初始化时调用：按 `faction_id` 查找，不存在则创建（`is_system=1`，`sect_owner` 置空约定值），存在则仅同步文案字段（name/description 派生字段），不覆盖运营数据（建设度/资材）。
**备选**：migration 里静态插入——否决，配置新增宗门需再写迁移，违背"策划只改配置"原则。

### D3: 绑定物标记落在既有存储，不入新表

- 功法：`player_skills` 加 `origin_sect_id`、`sect_bound` 两列。`sect_bound` 表达"只可传予本宗之人"的**固有属性**：仅拦截抄录/赠予/交易路径，不影响本人使用；**无封印状态**——离宗后已习得功法保留可用。
- 宗门之宝：储物戒物品 JSON 增加可选 `sect_id`/`treasure` 键，沿用现有 JSON 字段惯例，不建新表。
- 离宗钩子只负责**宝物回收**（功法不回收），收拢为 `sect_manager` 单一方法，「退出宗门」「踢出成员」「弃道重修」三条路径都走它。

### D4: 「加入宗门」单入口分流（已拍板）

handler 层按目标宗门 `is_system` 分流：默认宗门校验 `join_level_range`，玩家宗门走现有逻辑。不新增「拜入宗门」指令，指令面不膨胀。

### D5: 领悟池注入放在 `skill_manager` 池组装点

领悟池组装处追加一步：按 `player.sect_id` → faction `skill_pool` 注入。宗门池对所有渠道生效（与通用池的"仅突破"不同），因为在职弟子闭关/突破都应能领悟本门功法。来源功法在获得时打 `origin_sect_id`+`sect_bound`。

### D6: 两套职位权限定义合并到配置

`sect_config.json` 的 `positions` 扩展为唯一事实源（name/permission/promotion/benefits），删除 `sect_manager.py` 硬编码 `POSITION_PERMISSIONS`，权限判断读配置。同时接线 `scale_ratio`。

### D7: 职阶福利发放点

- 每日灵石：并入「签到」结算（已拍板），签到 handler 读玩家职阶 `benefits.daily_stones` 加发。
- 折扣：`shop_manager` 结算时读 `benefits.shop_discount`，一期仅作用于全局商店购买（宗门宝库货架二期）。
- 传承解锁：`benefits.unlocks` 列表作为获取资格校验（师承奖励/丹房领取/宝物发放时检查 `min_position` 或 unlocks）。

### D8: 师承任务进度复用悬赏式行为计数

任务链阶段目标类型（win_pve / adventure_complete / breakthrough / donate 等）映射到现有行为挂钩点，进度存玩家 JSON 字段（当前链 id + 阶段 + 计数）。不引入新事件总线——一期任务类型有限，switch 式分拨即可；二期世界事件再评估抽象。

### D9: 联动过滤为"配置可选字段 + 查询时过滤"

悬赏/秘境/历练三系统各自加 `sect_id` 可选配置与过滤参数，无该字段的内容行为完全不变（向后兼容零风险）。历练事件组过滤在抽取时追加，悬赏在榜单查询与接取校验两处过滤。

## Risks / Trade-offs

- [离宗回收遗漏路径] → 宝物回收逻辑收拢为单一钩子函数，「退出/被逐/弃道重修」均调用；单测覆盖三条路径，并验证功法离宗后保留可用。
- [默认宗门播种与玩家改名冲突：玩家宗门与默认宗门重名] → 播种的默认宗门名加入建宗禁用名校验，播种时若 `sect_name` 冲突按 `faction_id` 兜底识别。
- [宗门功法流入满星折算修为的经济漏洞] → 宗门池功法参与现有满星折算规则，不另开补偿路径。
- [一期范围膨胀] → 毁灭/NPC 只落配置结构与存储字段，行为一律二期；设计文档（§4.5、§5.7）是唯一事实源，防范围蔓延。
- [配置字段拼写错误导致内容静默失效] → `config_manager` 加载后对 `sect_factions.json`/`sect_tasks.json` 做结构校验（必填字段、引用的心法/功法 id 存在性），启动日志报警。

## Migration Plan

1. `data/migration.py` 新版本：`sects` 加 `is_system`/`faction_id`/`status`/`destruction_tier`；`player_skills` 加 `origin_sect_id`/`sect_bound`。存量行默认值（`is_system=0`、无绑定）保证零行为变化。
2. 配置默认值进 `data/default_configs.py`，`config_manager` 注册两个新文件。
3. 功能分步上线无开关需求：新指令与新区块对无宗门玩家不可见/不触发，向后兼容。
4. 回滚：配置删除即可停用内容；DB 新列可保留（无消费方时无副作用）。

## Open Questions

- 宗门之宝「发放」的具体指令形态（师承奖励自动入包 vs 宗门宝库领取页）可在实施时按指令面最小原则定，不影响 spec 契约。
