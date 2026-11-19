# Current System Evidence

## Purpose

记录 PVE 怪物与世界 Boss 重做规划所依据的现状证据，避免关键架构判断只停留在聊天记录。行号以 2026-10-10 规划时工作树为准。

## Player health

- `models.py:95-167,258-347`：`Player.hp` 是持久字段，`get_total_attributes(...)` 又从该值叠加装备/功法/丹药；它实际承担永久基础值。
- `managers/pve_combat_manager.py:350,419,472`、`managers/boss_manager.py:518`、`core/pill_manager.py:434-440,493,524,703-713`、`managers/adventure_manager.py:292`、`handlers/shop_handler.py:371-388,452`：同一个 `Player.hp` 又被当作当前血条读写。
- `core/breakthrough_manager.py:256`：突破对旧 `hp` 做永久成长。
- 结论：必须用 `base_hp` / `current_hp` / 动态 `max_hp` 拆分，且不能保留含混 alias，否则静态搜索无法阻止新误用。

## Database and transaction boundary

- `data/migration.py:19`：当前 `LATEST_DB_VERSION = 34`。
- `data/migration.py:71-125`：fresh players schema 只有 `hp`。
- `data/migration.py:180-197`：fresh boss schema 只有旧 10 字段。
- `data/migration.py:57-125,538-640`：v32 是冻结基线，v33+ 通过 `MIGRATION_TASKS` 升级；新实现必须同时改 fresh schema 与增量迁移。
- `data/data_manager.py:63-149,268-277`：`DataBase.transaction()` / `_TransactionCM` 使用 `BEGIN IMMEDIATE`、同任务 join、跨任务串行和 abort flag；它是多写领域操作的权威 UoW。
- `data/database_extended.py:252-329`：旧 boss CRUD 按方法 commit，不能直接组成一次原子挑战；需提供可参与外层事务的操作。

## Busy state, recovery, and fatigue

- `core/busy_state.py:58-194`：`BusyState` 拥有 `user_cd` 与 `players.state` 镜像，`assert_idle` 以权威窗口判断空闲；气血恢复不能只看 state 字符串。
- `core/busy_state.py:43-51`、`core/time_skip_registry.py:34-51`：持续时间字段由属主声明 `TIME_SKIP_ENTRIES` 并注册 provider。
- `managers/adventure_manager.py:188-370`：路线疲劳在 `_route_cooldowns` 内存字典；失败把 `player.hp = 1`，且 player 保存、clear busy、疲劳写入不是同一事务。
- 结论：恢复锚点、PVE 疲劳和 pending settlement 必须持久化、声明 time-skip，并统一结算边界。

## Enemy runtime

- `managers/enemy_manager.py:51-69`：旧 `Enemy` 缺 level/skills/affix。
- `managers/enemy_manager.py:142-153`：仍装载旧 `difficulty_coefficients`。
- `managers/enemy_manager.py:300-410`：普通敌人按玩家动态派生，和固定名册目标冲突。
- `managers/enemy_manager.py:412-503`：秘境兽/守护者专项组是现有兼容入口，必须保留。
- `managers/enemy_manager.py:367-370,475-478`：难度同时乘 damage/hp/armor，违背 `design_docs/content-design/pve-enemy-design.md:37,439-442` 的“只乘伤害”。
- `managers/pve_combat_manager.py:69-368`：普通 PVE 概率与类别内嵌，Enemy→Fighter 未传 level/crit/skills，战后写旧 `player.hp`。
- `managers/pve_combat_manager.py:370-485`：秘境兽与守护者用定向组路径，应迁移 current HP 但不能被固定名册重写破坏。

## Flee pending settlement

- `design_docs/content-design/pve-enemy-design.md:668-673,781-796` 原先只有“身法挂钩”方向，没有公式或实现。
- `core/encounter_store.py:1-127`：`EncounterStore` 仅进程内，热重载丢失之所以可接受是因为现有遭遇零惩罚；不适合承载路线收益和战斗选择。
- `managers/adventure_manager.py:250-370`：历练完成时立即触发和结算 PVE，要支持重启可恢复的战前选择必须引入持久 pending settlement，而不是只加同步布尔参数。

## World Boss

- `models_extended.py:104-117`：旧 `Boss` 只有 `boss_id,boss_name,boss_level,hp,max_hp,atk,defense,stone_reward,create_time,status`。
- `managers/boss_manager.py:215-305`：从 level config/exp 动态回退，且难度同时乘 HP/身法/迅捷/护甲。
- `managers/boss_manager.py:321-392`：旧生成带随机 HP 与即时奖励。
- `managers/boss_manager.py:394-535`：挑战没有次数、台账和完整事务；`damage_dealt = boss_fighter.max_hp - result.fighter2_final_hp` 会把历史损血重复算进本场，随后立即走旧奖励。
- `main.py:610-746`：轮询和 spawn/defeat callback 直接 await 外部广播。
- `handlers/player_handler.py:551-626`：签到依赖服务器本地 `datetime.now()`，因此 Boss 每日次数不能复用本地日期逻辑，必须显式 `ZoneInfo("Asia/Shanghai")`。
- 结论：用固定 profile 出生快照 + 可变实例状态；challenge service 原子处理 active/expiry、北京日次数、真实 HP 差、玩家气血、贡献、阶段、唯一末击与 outbox，提交后广播。

## Content source and governance

- `design_docs/content-design/enemies.csv:1-32`：28 只固定名册，4 段各 4 普通 + 2 精英 + 1 组内 Boss。
- `design_docs/content-design/world_bosses.csv:1-5`：4 只固定 Boss，含五维、技能、60%/20% 阶段、48h 存续、每日 3 次、击杀 12h/消散 24h。
- 两份 CSV 当前均为 `status=draft`、`narrative_status=占位`。
- `scripts/sync_content_to_config.py:115-120`：脚本可处理 draft/final，且当前没有 enemy/world_boss adapter；所以用户确认必须是显式治理门，不能依赖状态被脚本自动排除。

## Confirmed product decisions

- 本轮实施 Step 0–6 基础设施；Step 7 奖励经济延后至正式秘境设计后统一总账。
- 世界 Boss 每日 3 次按 `Asia/Shanghai` 00:00 重置。
- 气血采用 `base_hp` / `current_hp` / 动态 `max_hp`，旧 `hp` 迁移后不保留 alias。
- ~~高/极高风险历练战前可主动逃跑一次；成功保留当前气血并照常结算路线基础收益……公式参数经模拟封板。~~ **已被 2026-10-19 逃跑契约重拍覆盖**：全风险段遇敌给一次选择、成功收益 ×0.3/不掉落/不滚传承、失败锁同一敌人、成功率临时值即封板值（bd `-9hq` 零改动收口）、2026-10-20 起败场也不滚传承。
