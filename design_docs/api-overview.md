# 关键 API 速查（API Overview）

> 生成：2026-08-11。用途：给 AI/开发者一份**定位地图**——从玩家指令到数据库，每一层的关键入口函数及其作用。
> 维护约定：新增/重命名公开方法、新增子系统时**必须同步更新本表**；方法用途以源码 docstring 为准，本表只做索引。

## 0. 如何快速定位（给 AI 的检索路径）

1. **玩家指令 → 路由方法**：指令中文字符串在 `main.py` 顶部 `CMD_XXX = "指令名"` 常量；`grep "CMD_XXX" main.py` 找到 `@filter.command` 方法。main.py 每个路由方法都有 docstring：`"""Command 「指令名」; routes to xxx_handler.handle_yyy."""`，直接给出下游 handler。
2. **handler → manager**：handler 只做参数解析、状态检查、调用 manager，方法 docstring 第一行即用途。
3. **manager → core/data**：业务逻辑在 `managers/`，通用可复用逻辑在 `core/`，SQL 全部在 `data/`（`DataBase` 基础玩家表 + `DatabaseExtended` 扩展表，经 `db.ext` 访问）。
4. **玩法契约**：数值/机制的设计事实在 `design_docs/current-design-report.md` 与 `design_docs/<topic>/`；行为契约在 `openspec/specs/`；整体分层见 `design_docs/project-architecture.md`（含 mermaid 架构图）。

调用链总览：

```
群聊指令 → main.py @filter.command（@require_whitelist 白名单）
        → handlers/xxx_handler.py（@player_required 状态检查、参数解析）
        → managers/xxx_manager.py（业务逻辑）
        → core/xxx_manager.py（通用系统：修炼/突破/装备/技能…）
        → data/data_manager.py + data/database_extended.py（aiosqlite）
```

## 1. 入口层（main.py）

| 位置 | 作用 |
|---|---|
| `CMD_XXX = "中文指令"`（顶部常量区） | 全部 109 个指令的中文字符串定义 |
| `require_whitelist(func)` | 群聊白名单装饰器，非白名单群直接拒绝 |
| `XiuXianPlugin.initialize()` | 启动钩子：连库 → `MigrationManager.migrate_or_reset()` → `sect_mgr.ensure_system_sects()`（默认宗门幂等播种）→ 启动 4 个定时任务（Boss 生成/贷款逾期/灵眼生成/悬赏过期，Boss 可配置关闭） |
| `XiuXianPlugin.terminate()` | 关闭钩子：取消全部后台任务 |
| `XiuXianPlugin.__init__` → `_wire_core_services()` | 构造期装配段：core 服务单例（skill/storage_ring/equipment/cultivation/pill/shop 等）统一构造、按依赖序注入全部 manager/handler；**禁止在 handler/manager 内自构造核心服务** |
| `handle_xxx(self, event, ...)` ×111 | 绝大多数为纯路由壳：docstring 标注指令名与下游 handler。例外（含少量逻辑）：`handle_boss_fight`/`handle_spawn_boss`（开关+权限检查、悬赏联动）、`handle_rift_complete`/`handle_adventure_complete`/`handle_adventure_fight`/`handle_adventure_flee`（结算后按 `reward_data` 联动悬赏与师承进度，共用 `_advance_adventure_progress`）、`handle_gm`（管理员门槛） |

## 2. 横切工具（handlers/utils.py）

| 函数 | 作用 |
|---|---|
| `player_required(func)` | 指令核心装饰器：注入 `Player`、检查 `user_cd` 忙碌状态（`BUSY_STATE_ALLOWED_COMMANDS` 白名单放行查询类指令）、逾期贷款追杀提示 |
| `BUSY_STATE_ALLOWED_COMMANDS` | 忙碌时可用的指令白名单常量列表 |

忙碌状态是**双层**的：`player.state` 字符串 + `user_cd` 表（`db.ext.set_user_busy/set_user_free`）。新增"进行中"状态需同时维护两者 + `models_extended.UserStatus` 枚举。

## 3. handlers/ 指令处理层

每个文件一个 Handler 类，方法均为 `async handle_xxx(event, ...) -> AsyncGenerator`，通过 `yield event.plain_result(msg)` 回复。除下表外均为薄封装，职责即指令名：

| Handler 类 | 负责指令域 | 备注 |
|---|---|---|
| `PlayerHandler` | 我要修仙/我的信息/闭关/出关/签到/弃道重修 | 角色创建（灵修/体修）；签到加发宗门俸禄+丹房日重置；出关结算宗门洞天加成；弃道重修视同离宗回收宗门之宝 |
| `BreakthroughHandler` | 突破信息/突破 | → `core/BreakthroughManager` |
| `TechniqueHandler` | 修习目标/我的修习/激活功法/我的技能/战报条数 | → `core/SkillManager` |
| `EquipmentHandler` | 我的装备/装备/卸下 | → `core/EquipmentManager` |
| `PillHandler` | 服用丹药/丹药背包/丹药信息 | → `core/PillManager` |
| `ShopHandler` | 丹阁/器阁/百宝阁/购买/物品信息 | 含 `parse_qty` 数量解析；购买结算读宗门职阶折扣 |
| `StorageRingHandler` | 储物戒/取出/丢弃/赠予/接收/拒绝/更换储物戒/搜索物品/取出所有 | → `core/StorageRingManager`；手动存入已禁用；赠予拦截宗门绑定物 |
| `SectHandlers` | 「宗门」单入口 `handle_sect_entry` 子命令分发（信息/列表/创建/加入/退出/捐献/任务/丹房/建设/镇派功法/晋升/宝库/师承/商店/悬赏/排行/贡献排行 + 管理类 踢出/传位/职位） | 原 18 个宗门顶层指令已删除，子命令自行解析消息文本；悬赏子命令组经 handlers/bounty_handlers 模块级共享函数委托 BountyManager（排行/贡献排行直调 RankingManager，构造注入 `rank_mgr`）；商店子命令组委托 SectManager |
| `CombatHandlers` | 切磋/决斗 | `_get_target_id` 解析 @提及/数字目标；各自冷却 |
| `BossHandlers` | 世界Boss/挑战Boss/生成Boss | 挑战走 `BossManager.challenge_boss` |
| `RiftHandlers` | 秘境列表/探索秘境（子命令分发：数字ID进入/破阵 <答案>/传承；迎战由 main.py 拦截直调 manager）/完成探索/退出秘境 | |
| `AdventureHandlers` | 历练信息/开始历练/完成历练/历练状态 | 顶层指令「迎战」「逃跑」（战前抉择）由 main.py 直接拦截调 `AdventureManager.resolve_adventure_choice`，不经本 handler（与秘境子命令「迎战」同惯例）；`handle_complete_adventure` 未被 main.py 路由引用（实际入口在 main.py），保留仅为兼容旧调用方、删除前请先确认无引用 |
| `BountyHandlers` | 悬赏令/接取/状态/完成/放弃悬赏 | 全部薄委托，渲染与编号防御统一走 handlers/bounty_handlers 模块级共享函数（`scope='global'`）；宗门专属悬赏走「宗门 悬赏」子命令组（scope='sect'）；两路行为由共享函数保持同位素一致 |
| `AlchemyHandlers` | 丹药配方/炼丹 | |
| `BankHandlers` | 银行/存取/利息/贷款/还款/流水/突破贷款 | |
| `BlessedLandHandlers` | 我的洞天/购买/升级/洞天收取 | |
| `SpiritFarmHandlers` | 我的灵田/开垦/种植/收获/升级灵田 | |
| `SpiritEyeHandlers` | 灵眼信息/抢占/收取/释放 | |
| `DualCultivationHandlers` | 双修/接受双修/拒绝双修 | |
| `ImpartHandlers` / `ImpartPkHandlers` | 传承信息 / 激活传承 / 传承挑战/传承排行 | |
| `RankingHandlers` | 境界/战力/灵石/存款排行 | |
| `NicknameHandler` | 改道号 | |
| `GMHandler` | 修仙GM/修仙GM帮助 | 统一入口 → `core/GMManager.dispatch` |
| `MiscHandler` | 修仙帮助 | 帮助文本也在此处维护 |

## 4. managers/ 业务逻辑层

| Manager | 关键公开方法 | 作用 |
|---|---|---|
| `CombatEngine`（combat_manager.py） | `resolve_combat(fighter1, fighter2, combat_type="spar", merge_count=None)` / `build_fighter_from_player(player, ...)` | **统一战斗引擎**：回合制 PvP/PvE 共用；触发技 `EFFECT_HANDLERS` 注册表分发 14 种效果键（13 个处理函数，combo 复用 damage_bonus）、持续状态（dot/buff/debuff/fatigue）生命周期、大招必放。配 `FighterState/StatusEffect/CombatResult` |
| `CombatManager`（同文件） | `player_vs_player` | 旧接口适配器，委托 `CombatEngine`；`calculate_*` 系列为 deprecated 兼容保留 |
| `BossManager` | `spawn_boss` / `challenge_boss` / `get_boss_info` / `auto_spawn_boss` | 世界 Boss 生成（`auto_spawn_boss` 供定时任务）、挑战、奖励 |
| `BountyManager` | `get_bounty_list` / `accept_bounty` / `complete_bounty` / `abandon_bounty` / `add_bounty_progress` / `check_and_expire_bounties` | 悬赏列表按境界分难度、10 分钟缓存（按 scope 分键 `user:global|sect`）；前四者带 `scope` 参数分流公共/宗门悬赏，分流校验先于缓存/冷却/活跃检查；接取/结算均 `BEGIN IMMEDIATE` 事务；`add_bounty_progress` 由历练/秘境回调推进进度 |
| `SectManager` | `create_sect` / `join_sect` / `donate_to_sect` / `kick_member` / `transfer_ownership` / `perform_sect_task` / `handle_owner_death`；宗门成长：`ensure_system_sects` / `reclaim_sect_treasures` / `get_fairyland_exp_bonus` / `claim_elixir` / `upgrade_building` / `manage_sect_buff` / `promote_position` / `get_treasury_info` / `claim_treasure` / `get_master_task_status` / `get_position_benefits` / `get_sect_shop_info` / `buy_sect_shop_item` | 宗门全生命周期；宗主死亡自动传位/解散；默认宗门播种、离宗回收、洞天/丹房/镇派功法/晋升/宝库/师承任务链、宗门商店（贡献点结算，商品池读 faction `shop` 字段）（详见 current-design-report.md §4.8） |
| `BankManager` | `deposit` / `withdraw` / `borrow` / `repay` / `claim_interest` / `check_and_process_overdue_loans` | 银行存贷；**逾期贷款追杀致死**（定时任务入口 `check_and_process_overdue_loans`） |
| `RiftManager` | `list_rifts` / `enter_rift` / `finish_exploration` / `exit_rift` / `answer_puzzle` / `accept_beast_challenge` / `accept_legacy_challenge` / `force_puzzle_encounter` / `force_beast_encounter` / `force_legacy_encounter` | 秘境探索与结算；结算后遭遇判定（谜题/妖兽/传承三类内存 pending，EncounterStore）；迎战胜利返回 `pve_won` 供 main.py 推进师承链；force_* 为 GM 强触入口 |
| `AdventureManager` | `start_adventure` / `finish_adventure` / `resolve_adventure_choice` / `awaits_combat_choice` / `check_adventure_status` / `get_route_overview` / `clear_fatigue` | 历练路线（config 驱动事件权重/掉落表/逃跑系数），v39 起为持久结算状态机：`adventure_settlements.state` 是唯一权威（`adventuring → resolved_win \| pending_choice → resolved_win\|resolved_loss\|resolved_fled`），完成时刻把敌人/事件/基础收益/`rng_seed` 锁进 `snapshot`，迎战/逃跑/重启找回只读该快照；`awaits_combat_choice` 供 GM 判断单据是否挂着 `pending_choice`/`ready_combat`（GM 不持仓储），与 `resolve_adventure_choice` 共用 `_owned_open_run` 归属判定——单据必须属于**当前这次历练忙碌**（`user_cd` 为 `ADVENTURING` 且 extra 里的 run id 与单据一致），否则按「没有待抉择的历练遭遇」拒绝，防 GM 清冷却留下的孤儿单被玩家后来的任一次忙碌消费；`_ensure_run_row` 给升级前就在途的旧忙碌行补建单据时，把 mint 出的 run id 在同一笔事务里经 `BusyState.stamp_extra` 落回 `user_cd.extra_data`（不落回则归属永远对不上，玩家被锁死且每点一次「完成历练」多补建一张事实）；该 run id 由 `user_cd.create_time` 派生而**非 uuid**，靠 `adventure_run_id` 的 UNIQUE + 冲突回读，并发双击也只落一条事实（落败方读到终态后按重放走，不推悬赏/师承）；落回只由**真正插入成功那一路**做（`insert` 的 `created` 闸门）——落败方若也按旧快照整行回写，会把赢家已清掉的忙碌**复活成历练中**（迎战/逃跑此时被归属闸门正确拒绝，只能靠 `_replay_terminal` 的不变式收尾自愈，见下）；终态一笔短事务（`state`+`cas_version` 双条件 CAS 写状态/气血/休整/清忙），三项效果在提交后的第二笔短事务逐项 `claim_effect` 守护（重放与并发不重复发奖，「完成历练」是崩溃点 3 的唯一补发入口）；**不变式「单据终态 ⇒ 不持有该场历练的忙碌」**由 `_replay_terminal` 兜底：忙碌被任何来源的陈旧整行快照复活后（含 GM 强制结算的 `scheduled_time` 直写例外，AGENTS §2），再点一次「完成历练」即按**库里当下**的 `user_cd`（`ADVENTURING` 且 extra 的 run id 为空或等于本场）`clear` 收尾自愈，期间若已开更新的一场则绝不误清；结算时联动悬赏进度（`pve_won` 决定是否推 `win_pve`） |
| `AlchemyManager` | `get_available_recipes` / `craft_pill` | 炼丹（材料从储物戒扣） |
| `BlessedLandManager` | `purchase_blessed_land` / `upgrade_blessed_land` / `collect_income` | 洞天购买/升级/固定收益产出 |
| `SpiritFarmManager` | `create_farm` / `plant_herb` / `harvest` / `upgrade_farm` | 灵田种植（灵草→炼丹材料） |
| `SpiritEyeManager` | `spawn_spirit_eye` / `claim_spirit_eye` / `collect_spirit_eye` / `release_spirit_eye` | 灵眼定时生成、**原子抢占**、修为产出 |
| `DualCultivationManager` | `send_request` / `accept_request` / `reject_request` | 双修请求-响应流程，双方修为奖励 |
| `ImpartManager` / `ImpartPkManager` | `create_legacy` / `activate_legacy` / `add_active_impart_value` / `transfer_legacy` / `list_owner_legacies`；`challenge_impart` / `select_snatch_target` / `get_impart_ranking` | 传承实例生命周期（一人多条、激活累积、PK 转移、等阶奖励）；玩家间传承挑战（夺取制） |
| `RankingManager` | `get_level/power/wealth/sect/deposit/contribution_ranking` | 六大排行榜；战力公式单一实现在 models.py `Player.combat_power`（伤害+身法+迅捷+气血+armor//2，含/不含临时丹药由调用方 `pill_multipliers` 实参决定） |
| `EnemyManager` | `spawn_enemy(level_index)` / `spawn_enemy_from_group(group_key, player_level)` / `get_drop_items` | 按玩家境界生成敌人与掉落（动态路径=固定名册 Batch 5 切流前的临时入口；全局难度**只乘伤害**） |
| `EnemyCatalog` / `build_enemy_fighter`（enemy_catalog.py） | `load` / `load_catalog` / `spawn_enemy(level, category)` / `profile_to_enemy` / `build_enemy_fighter` | 固定名册不可变 catalog（schema v2；28 敌 + 4 世界 Boss profile、(realm_segment, category) 索引、难度单点只乘伤害）；`build_enemy_fighter` 为 Enemy→FighterState **唯一 mapper**（level_index/暴击/触发技/大招/护甲透传，秘境兽与传承守护同走）；正式 sync 批准前 `load_catalog` 对旧 v1 config 返回 None（调用方保持动态路径） |
| `PVECombatManager` | `trigger_pve_combat(player)` | PVE 触发主入口（选敌→CombatEngine→奖励→格式化战报） |

## 5. core/ 通用系统层

| Manager | 关键公开方法 | 作用 |
|---|---|---|
| `CultivationManager` | `generate_new_player_stats` / `calculate_cultivation_exp` / `get_spiritual_root_speed` / `apply_cultivation_comprehension` | 四主属性（气血/伤害/身法/迅捷+armor）初始生成；闭关修为计算；闭关结束领悟判定 |
| `BreakthroughManager` | `check_breakthrough_requirements` / `calculate_breakthrough_success_rate` / `execute_breakthrough` | 突破条件/成功率（连败保底 pity）/执行 |
| `SkillManager` | `roll_*_comprehension`（突破成/败/闭关/通用池）/ `set|clear_study_target` / `get_heart_method_passive` / `can_equip_technique` / `get_battle_loadout` | 领悟（升星）判定、修习目标、心法被动、**出战配置导出给战斗引擎**；领悟池全渠道注入本宗 `skill_pool` 并打 origin_sect_id/sect_bound 标记；`get_battle_loadout` 注入镇派功法 mainbuff 触发 |
| `EquipmentManager` | `equip_item` / `unequip_item` / `get_equipped_items` / `parse_item_from_name` | 装备穿戴（境界要求校验；装备唯一依据=已领悟表 player_skills）；解析与槽位枚举由模块级 `parse_item_from_name` / `build_equipped_items` 承接（三源回退 items→weapons→heart_methods，战斗/面板/健康三域共用同一入口） |
| `PillManager` | `use_pill` / `handle_resurrection` / `calculate_pill_attribute_effects` / `get_breakthrough_modifiers` / `consume_breakthrough_effects` | 丹药服用/回生丹复活/属性乘算加成/突破临时加成生命周期 |
| `StorageRingManager` | `store_item` / `retrieve_item` / `discard_item` / `upgrade_ring` / `has_item` / `is_sect_bound_item` | 储物戒存取（事务保护，每物品占 1 格）；**所有物品发放的统一入口**；`is_sect_bound_item` 识别宗门绑定物（treasure/sect_bound/sect_id）供赠予拦截 |
| `ShopManager` | `generate_shop_items` / `should_refresh_shop` / `get_item_details` / `get_sect_shop_discount` / 三阁展示方法 | 商店刷新（库存+折扣）、丹阁/器阁/百宝阁展示；`get_sect_shop_discount` 读宗门职阶 benefits.shop_discount |
| `HealthService`（health.py） | `get_health_snapshot` / `settle` / `compute_max_hp` / `clamp_current_hp` / `apply_current_hp_change` / `set_current_hp` / `heal_to_full` / `add_base_hp` | 玩家气血三层域唯一入口：`base_hp` 永久底数 / `current_hp` 当前值 / `health_recovered_at` 恢复锚；`max_hp` 运行时聚合不入库；每分钟恢复 1% 上限（读取时按锚结算、幂等、重启安全），**恢复只按经过时间判定、不看忙碌状态**（2026-10-12 取消忙碌闸门，闭关/修炼/历练 pending 期间同样回血），忙碌转换在 `BusyState`/GM 权威写入的同一事务内先结算旧状态并推进锚点；恢复锚**不注册**进时间快进表，GM 时间快进不产生气血恢复 |
| `BusyState`（busy_state.py） | `set_busy` / `set_cooldown` / `clear` / `assert_idle` / `stamp_extra` / `pending_choice_hint` | 玩家忙碌状态唯一属主：`user_cd` 表为真相、`player.state` 为展示镜像，禁止业务模块裸写；`set_busy` 在事务内重读 `user_cd` 做抢占复核（并发双开只有一方成立），并在同一事务内先结算旧状态健康域再写新忙碌；`assert_idle(user_id, template=)` 是自定义守卫的官方入口（18 处调用点共用，`ADVENTURING` 分支自动追加 `pending_choice_hint` 的「💡 可发送「迎战」或「逃跑」…」出路提示，其余忙碌状态文案逐字不变、零额外查库）；`stamp_extra` 供升级窗口补写身份字段：按调用方持有的忙碌行快照**整行回写**（底层 `update_user_cd` 是全列 UPDATE，含 `type`/时间），只把 `extra_data` 换成新载荷；**调用方契约**是「本次写入仍确定持有该忙碌行」才调用（唯一调用点靠 insert 的 `created` 闸门保证），否则并发下拿旧快照晚写一步会把别人已 `clear` 的忙碌复活成原状态、且可能没有任何收尾出口；`pending_choice_hint` 每次现建仓储（`DataBase.connect()` 会替换 `conn`），调用方必须自行确认忙碌是历练 |
| `enemy_schema`（enemy_schema.py） | `validate_enemy_document` / `check_approval` / `build_enemy_profile` / `build_world_boss_profile` / `AFFIX_TRIGGER_SKILLS` / `BOSS_SKILL_MECHANICS` / `WORLD_BOSS_SIGNATURE_SKILLS` | 敌人内容 schema v2 纯 stdlib 契约层：CSV 行→combat profile 构建 + 全字段校验（枚举/边界/阶段阈值/legacy 死键拒绝）+ 正式写审批闸门（`--approval-manifest`：CSV SHA-256、获批数据集/列范围、叙事决策；draft/缺 manifest/hash 漂移/列越权 fail closed）；词条→触发技与 Boss 机制映射的**单一真相**（与 design_docs 验收模拟 `sim_pve_acceptance.py` 常数互锁，运行时/catalog/未来 D 域共同消费；sync 脚本经 importlib 文件加载复用） |
| `GMManager` | `dispatch` / `cmd_set_*` / `cmd_give_*` / `cmd_force_adventure` / `cmd_force_adventure_fight` / `cmd_force_rift` / `cmd_force_rift_puzzle|beast|legacy` / `cmd_advance_master` / `cmd_clear_cd` / `cmd_clear_bounty` / `cmd_clear_all_cooldowns` / `cmd_time_skip` / `cmd_seed` / `cmd_spawn_boss` | GM 子命令分发（目标解析 @提及→数字id→发送者；触发秘境谜题/妖兽/传承用 `single_token_is_target=True` 使单数字 token 视为目标；强制结算类经 `_resolve_force_target` 使单个数字 token 即目标 ID）；全操作写审计日志（500MB 滚动）；`cmd_set_mp/atk/mental_power` 为废弃属性别名；`设置贡献/设置职位` 写宗门字段；`师承推进`（战斗/历练/突破/捐献）确定性推进师承链；`清除悬赏` 清进行中悬赏+放弃冷却（供测试环境重置悬赏状态）；`触发历练结算` 不战而结，但单据挂着 `pending_choice`/`ready_combat` 时诚实拒绝并指路 `强制历练迎战`（后者内部走 `resolve_adventure_choice(flee=False)`，真实胜负入账后只清休整）；两条历练强制命令与正常流程共用 `_advance_adventure_progress` 追加悬赏/师承进度；测试工具三件套：`时间快进` 按时间快进注册表（`core/time_skip_registry.py` 聚合各属主模块 `TIME_SKIP_ENTRIES`）全库前移到期判定时间戳（不可逆，需「确认」）、`清除全部冷却` 按玩家归零全部冷却（既有清除命令并集）、`随机种子` 注入/重置全局 `random.seed`（进程级、不持久化） |
| `EncounterStore`（encounter_store.py） | `pend` / `get_active` / `consume` | 秘境/历练遭遇的内存 pending 表（每玩家 puzzle/beast/legacy 各一，惰性过期、同类覆盖刷新；热重载丢失零惩罚）；main.py 装配单例注入 RiftManager/AdventureManager |
| `RiftPuzzleManager`（rift_puzzle_manager.py） | `generate` / `RiftPuzzle.check` | 古阵谜题纯逻辑引擎：谜题族注册表随机抽取（五行破阵/洛书数阵/灵龟辨窟），三态校验（正确/错误/非法形式不耗次），无 IO 可单测 |
| （`breakthrough_fortune.py`） | 模块级函数 | 突破运势文案 |

## 6. data/ 数据层

| 位置 | 关键方法 | 作用 |
|---|---|---|
| `DataBase`（data_manager.py） | `connect/ensure_connection/reconnect` / `create_player` / `get_player_by_id` / `update_player` / `delete_player_cascade` / `get_shop_data` / `decrement_shop_item_stock` | 连接管理（定时任务前先 `ensure_connection`）；玩家 CRUD 字段从 `Player` dataclass 动态生成；商店库存**原子扣减/回滚** |
| `DatabaseExtended`（database_extended.py，`db.ext`） | 按域分组：宗门 `*_sect*`、Boss `*_boss`、秘境 `*_rift`、状态 `create/get/update_user_cd`+`set_user_busy/free`、技能 `learn_or_star_up`/`get_learned_skills`/`is_skill_learned`、悬赏 `*_bounty`、银行/贷款 `*_loan*`/`add_bank_transaction`、赠予 `*_pending_gift*`、系统配置 `get/set_system_config`（KV 表，悬赏放弃冷却等都用它） | 全部扩展表 SQL |
| `MigrationManager`（migration.py） | `migrate_or_reset()` | 版本化迁移：新装直接建最新 schema（v35）；旧库按版本升序逐个事务执行 `@migration(version)` 注册的任务；低于任务链下限的旧库整体重建为最新 schema（**重置前自动备份** `<db>.v<版本>.pre-reset.bak`）；版本高于 v35 时拒绝降级运行 |

并发敏感操作惯例：`await db.conn.execute("BEGIN IMMEDIATE")` + try/commit/rollback（参照 `BountyManager.accept_bounty`）。

## 7. 模型与配置

| 文件 | 作用 |
|---|---|
| `models.py` | `Player` dataclass（主属性 damage/agility/speed + armor_value；气血三层 `base_hp`/`current_hp`/`health_recovered_at`，气血上限 `max_hp` 运行时聚合不入库；`get_total_attributes` 输出键为 `max_hp`）、`Item`/`StorageRing`（`atk` 等旧字段仅存于 `Boss` 模型） |
| `models_extended.py` | `UserStatus` 枚举（IDLE/CULTIVATING/ADVENTURING/EXPLORING/SECT_TASK，忙碌状态真源之一）、`Sect/Boss/Rift` 等扩展模型 |
| `config_manager.py` | 加载 `config/*.json`（缺失时从 `data/default_configs.py` 建默认）；静态配置改后需重启 |
| `data/default_configs.py` | 全部 JSON 配置的默认值（平衡数值真源之一） |

## 8. 定时任务入口（main.py `initialize()` 启动）

| 任务循环 | 调用 | 说明 |
|---|---|---|
| `_schedule_boss_spawn` | `BossManager.auto_spawn_boss` | 含指数退避重试范式，新定时任务照抄 |
| `_schedule_loan_check` | `BankManager.check_and_process_overdue_loans` | 逾期追杀 |
| `_schedule_spirit_eye_spawn` | `SpiritEyeManager.spawn_spirit_eye` | 灵眼生成 |
| `_schedule_bounty_check` | `BountyManager.check_and_expire_bounties` | 悬赏过期 |
