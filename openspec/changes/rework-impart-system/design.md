## Context

现状（参见 proposal.md - Why）：传承值仅通过传承 PK 胜利随机 +1~5 累积；传承为单条（`impart_info` 表，user_id UNIQUE）；奖励 id 空转；配置为单套 5 阶阈值。关键存量事实：

- `managers/impart_manager.py`：`add_impart_value()` 是唯一加值入口，含 tier 自动发放（`_grant_pending_rewards`）；面板 `_build_panel`。
- `managers/impart_pk_manager.py::challenge_impart()`：走 `CombatEngine(combat_type="impart_pk")`（combat_manager.py:188 无特殊分支）。
- 修炼出关：`handlers/player_handler.py::handle_end_cultivation()` 已计算 `effective_minutes`（上限 base 1440min + 每大境界 360min），是本设计传承值累积的天然挂钩点。
- PvE 统一入口 `managers/pve_combat_manager.py::trigger_pve_combat(scene, difficulty)`——内部依次做：概率触发判定（`_should_trigger_combat`，读 `encounter_rates[scene][difficulty]`，scene 仅支持 adventure/rift）→ 类别抽取（normal/elite/boss）→ spawn → 战斗 → 写回 player.hp → 通用奖励结算（`_calculate_rewards`，不按 scene 分支：敌胜 exp×0.3+安慰金币+hp_penalty；玩家胜 exp×1.2）；掉落分支在调用方（adventure_manager.py / rift_manager.py）。
- `EnemyManager.spawn_enemy(player_level, category)` 的分组由 `_get_group_by_level` 按**玩家等级匹配首个 level_range 命中的组**选出，category 仅为 normal/elite/boss——**无法按组名定向生成敌人**，新组若 level_range 与现有组重叠还会劫持普通 PvE 生成。
- 宗门宝库：`sect_manager.py` `get_treasury`/`claim_treasure`（读 `sect_factions.json` treasures，kind=treasure|heart_method，"每人限领一次，离宗归还"）；离宗回收钩子 `reclaim_sect_treasures`（L211）与退宗/被踢（L780）。
- 迁移当前 `LATEST_DB_VERSION = 31`。
- 配置加载走 `config_manager.py::_load_config_with_default`，改配置需重启生效。

## Goals / Non-Goals

**Goals:**
- 传承值累积完全由修炼驱动（每 15 分钟 1 点，出关结算一次性入账），PK 仅夺取传承整体所有权。
- 一人多传承实例的数据模型与迁移路径；宗门传承不可夺 + 离宗回收。
- 三类获取途径（宗门/历练/秘境）均经守护 NPC 挑战，概率进各自模块配置。
- 修复奖励发放空转（奖励 id 经 content-design + sync 管道落地）。

**Non-Goals:**
- 历练传承事件化抽取、特定秘境专属传承、各类型独立数值调参——留后续（配置结构已预留）。
- 传承值参与 PK 战力或任何战斗数值。
- 守护 NPC 专属战斗机制（完全复用 CombatEngine）。

## Decisions

**D1. 数据模型：两张新表而非扩展玩家行。**
`legacy_instances`（id PK, owner_id, legacy_type, impart_value, claimed_tiers JSON, sect_id NULL, acquired_at）+ `impart_pk_cooldown`（challenger_id, target_id PK, failed_at）。
备选：在 player 行存 JSON 数组——不利于排行查询、转移原子性与宗门回收过滤；独立行表是自然选择。冷却独立表而非 `user_cd`/`UserStatus`：冷却语义是"挑战者-目标"二元键 + 5 天绝对时长，与忙碌状态枚举无关，且 user_cd 会被忙碌清理逻辑误伤。

**D2. 修炼累积挂钩出关结算，而非定时任务。**
在 `handle_end_cultivation` 末尾对持有实例 `add_impart_value(effective_minutes // 15)`，一次事务完成。备选：后台定时任务逐条+1——复杂度高、与"修炼时长"语义不一致、重启丢失。出关一次性结算与闭关时长强绑定，且天然处理上限（effective_minutes 封顶）。

**D3. 守护 NPC 挑战：新增组定向生成 API + 独立挑战函数（不复用 trigger_pve_combat）。**
两个现状约束决定了不能简单复用 PvE 入口（见 Context）：① `spawn_enemy` 无法按组名生成；② `trigger_pve_combat` 自带概率 roll、类别抽取与修为/金币结算，均非传承场景所需。因此：
- `EnemyManager` 新增 `spawn_enemy_from_group(group_key, player_level)`：按组 key 取组（无 level_range 依赖），由玩家境界在组内 templates 选取匹配模板；`enemies.json` 增加 `legacy_guardian` 组（**不带 level_range**，仅经新 API 触达，避免劫持普通 PvE 生成）。
- 守护挑战为独立函数（放 `pve_combat_manager.py`）：`spawn_enemy_from_group` → `build_fighter` → `CombatEngine.resolve` → 写回 player.hp → 仅返回胜负与战报；**无概率 roll、无修为/金币/掉落结算**。
- HP 语义：战斗 HP 损耗照常写回（与所有战斗一致），挑战失败设 HP 下限不死（不低于 1）；无 hp_penalty 修为惩罚——失败的代价即触发机会消耗。
备选：直接复用 trigger_pve_combat 加 scene 分支——会触发二次概率 roll、错误类别映射与不需要的修为/金币结算，副作用面过大；新写整套战斗则重复且易漂移。

**D4. PK 目标选择：默认取对方最近获取（acquired_at DESC）的一条非 sect 实例；支持可选类型参数过滤。**
挑战指令 `传承挑战 <@某人> [类型]`：指定类型则过滤目标实例（无匹配提示），未指定取最近一条**非 sect** 实例（跳过宗门传承）；若被挑战者没有任何可夺取实例（无传承或全部为 sect），拒绝并提示。转移实现 `transfer_legacy(instance_id, new_owner)`：owner 改写 + impart_value=0 + claimed_tiers=[] 单事务。平局（draw）：无夺取、不计失败冷却（视为未分胜负）。

**D5. 配置按类型分表 + 首版共享默认阈值。**
`impart_config.json` 重构为 `{ cultivation_points_every_minutes: 15, types: { common/sect/adventure/rift: { name, tiers: [{tier, impart_value_required, rewards}] } }, guardian: { enemy_group } }`。首版各类型复用原 20/40/60/80/100 五阶，结构独立、数值后续微调。旧配置缺失时 `_load_config_with_default` 给默认（`data/default_configs.py` 需补默认，否则空配置 → 全部跳过）。
备选：每类型独立文件——过度拆分；单文件 types 分组已满足。

**D5a. `common` 类型为迁移遗留类型。**
三类获取途径仅产出 sect/adventure/rift，`common` 仅来自 v32 旧数据迁移，无新增获取途径。面板与帮助文案需向新玩家说明首条传承来自三类途径，避免出现无人可达的类型入口。

**D5b. 术语消歧：新系统语境限定为「个人传承」。**
「传承」一词已被占用：`sect-system/spec.md` 的「传承功法」（sect_bound 功法）、宝库领取 prompt「请指定要领取的传承」、`misc_handler.py` 帮助「查看本宗传承」、秘境事件文案「前辈留下的传承」。本系统的面板/帮助/战报文案统一使用「传承」指个人传承实例，与宗门语境区分（如宝库侧保留「宗门传承」限定词）；不在本次改动中全局重命名，仅约定新文案不制造歧义。

**D6. 奖励 id 落地走既有 content 管道。**
在 `design_docs/content-design/heart_methods.csv`、`skills.csv` 补传承奖励条目（传承心法·吐纳/归元、传承功法×2），`scripts/sync_content_to_config.py` 同步进 `heart_methods.json`/`skills.json`，保持内容单一来源。备选：直接手改 JSON——会与 content-design 漂移，违反项目内容管线约定。
（注意：奖励配置变更同其他静态配置，需重启生效——写入设计文档与实现备注。）

**D7. 宗门传承通过宝库 kind=legacy 接入，回收挂既有离宗钩子。**
`claim_treasure` 扩展 kind=legacy 分支：先守护挑战 → 成功创建 `legacy_instances`（type=sect, sect_id 绑定）+ 占"每人限领一次"名额；失败不占。`reclaim_sect_treasures`（退出/被踢两条路径）扩展删除该玩家该宗的 sect 实例。

**D8. 迁移 v32 单向转换。**
建两张新表 → `INSERT INTO legacy_instances ... SELECT`（type=common，保留 value/claimed）→ DROP `impart_info` → 更新 `db_info.version=32`。迁移测试覆盖幂等性与数据保全。回滚：代码/配置可回退，新表数据不回滚（单向，接受）。

## Risks / Trade-offs

- **奖励 id 再次空转** → 实现阶段加配置存在性校验测试（tier 配置引用的心法/功法 id 必须存在于对应 JSON），并在重载后冒烟验证实际入包/入技能。
- **迁移破坏现有玩家进度** → v32 迁移测试断言值/claimed 完整迁移；DROP 前先完成拷贝（同事务），测试覆盖重复启动幂等。
- **守护挑战引入 HP 副作用** → 独立函数写回 HP 但设下限不死（≥1）；功能测试断言触发传承时无修为/金币/掉落异常。
- **多条传承同时累积导致数值膨胀** → 已记录为假设（用户知悉）；阈值可按类型独立调参作为后续缓解手段。
- **并发转移/累积竞态**（PK 胜转移与出关累积同一实例）→ 实例更新走 `BEGIN IMMEDIATE` 事务（项目既有并发规范）。
- **配置缺失时行为退化**（impart_config.json 空/缺字段）→ `_load_config_with_default` 提供完整默认值；守护组缺失时获取途径静默跳过并告警日志。
- **连胜剥光（griefing 面）** → 挑战成功无冷却，同一玩家可被连胜多次夺走全部传承——忠实于需求（PK 只负责夺取），记录为**已接受风险**；后续如需缓解可加"同一目标每日被夺上限"。
- **重复领奖刷副本** → 转移后 claimed_tiers 清零，新主人重练会再次领取同批心法/功法奖励，与 D6 奖励落地叠加后影响放大；首版接受（奖励本身绑定玩家），后续可考虑实例级"已发放奖励历史"防刷。

## Migration Plan

1. 代码 + 配置 + 迁移 v32 一并发布；插件加载时 `migrate()` 自动执行：建表 → 拷贝 → DROP 旧表。
2. 旧玩家传承进度自动转为 `common` 实例（保留值/已领等阶），无需玩家操作。
3. 配置类变更（impart/adventure/rift/sect_factions/enemies）需重启生效；文档标注。
4. 回滚：整体回退代码与配置版本即可；数据已在新表（单向迁移，旧表已删）。

## Open Questions

- 各类型 `legacy_chance` 具体默认概率值与各类型独立阈值数值（实现时可定，均可配置，不影响本设计）。
- 守护 NPC 挑战失败后的安抚文案与下次触发节奏（体验层细节，实现时定）。
- 挑战者失败的 1% 修为惩罚长期是否保留（本次保留现状，后续平衡调整时复审）。
