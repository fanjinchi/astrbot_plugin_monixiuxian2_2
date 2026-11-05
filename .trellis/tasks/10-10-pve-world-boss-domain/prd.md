# 世界 Boss 生命周期与原子挑战

## Goal

把旧随机、逐步提交的 Boss 流程替换为 4 只固定档案驱动、可重启恢复、并发安全的世界 Boss 领域：48 小时生命周期、北京时间每日 3 次、真实伤害贡献、三阶段、唯一末击和提交后事件。

## Dependencies

- 依赖玩家气血 child 的 current/max HP 和事务友好 API。
- 依赖目录 child 的固定 Boss profile/snapshot contract。
- 依赖持久化/事务基座 child 提供 v37 instance/attempt/ledger/contribution、v38 business-event/delivery schema、CAS/claim repository、commit 纪律与 Boss lifecycle time-skip provider；本 child 不再自行分配 migration 版本。
- **目录装配**：B 已交付 `EnemyCatalog` 与 best-effort `load_catalog()`（legacy v1 → `None`），但生产装配为 0 调用。本 child 负责在 `main.py::_wire_core_services` 注入；catalog 为 `None` 时新领域必须保持 disabled（不建实例、不抛错），E2 在内容同步后启用。
- 事务叶子门控：`handlers/combat_handlers.py:79-80` 已由 child C 按 `conn._txn_depth` 门控（bd `-qbo` notes，2026-10-14）；该点在 PvP 调用图上，**不在**世界 Boss 调用图（Boss 路径为 main → boss_handlers → 领域服务）。本 child 仅静态复核，不再修改。
- 正式 profile 配置启用仍受用户内容确认门控制。

## Requirements

### R1. 固定实例与出生快照

- 每次新实例在 4 个境界段中全随机选择，不按活跃玩家、全服平均境界或来客境界适配；选中段对应第一季固定 profile。选择用可审计的 spawn seed/selection fact，profile id/version 与 seed 随出生快照持久化，重复轮询或幂等重试不得重掷。`instance_id` 由 `(profile_id, spawn_epoch)` 确定性派生，并发 ensure 靠主键冲突读回同一行（DDL 无「单 active」唯一约束，领域侧以确定性 id + 状态条件写保证）。**`spawn_epoch` 定义 = 上一实例 `terminated_at + respawn_{kill|dissipate}_h`**（无上一实例/首次启动时取持久化基准时刻），seed 只由该 epoch 派生；ensure 前先查 `state='active'`，存在则直接复用、不生成新实例。**首次基准落点**：取 `system_config` 新键（首次实例同事务写入）或首个实例 `spawned_at` 作为基准；ensure 的 active 读 + insert 必须在同一 `db.transaction()` 内，否则并发 ensure 只靠「同一秒算出同一 id」的巧合。
- **GM/fixture 强制 profile 入口**：`ensure_spawn(profile_id: str | None = None)` —— `None` 走 4 段随机；给定 profile 时强制选择该 Boss，供 GM「生成Boss」与功能用例按 Boss 验证。强制路径不得改变其它不变式：instance_id 仍由 `(profile_id, spawn_epoch)` 派生、快照仍不可变、仍受「单 active」与 12h/24h 到期约束，并记 warning 日志区分人工触发。
- 出生时复制 profile id/version、名称、境界、最大 HP、五维、技能和阶段规则；活动期间不可因配置热更新或旧 level/exp 公式重算面板，难度倍率只乘伤害。
- 移除随机 HP、旧 `stone_reward` 和即时奖励作为新实例权威字段/行为。

### R2. 生命周期

- 状态机为 `active -> defeated | dissipated`；active 最长 48h。
- defeated 12h 后、dissipated 24h 后获得下一实例生成资格。
- 过期检查和终态转换幂等；重启或重复轮询不重复生成或广播。
- expiry/next spawn 等绝对时间戳**已由 P 在 `managers/boss_manager.TIME_SKIP_ENTRIES` 登记**（本 child 只确认、不重复声明；勿建第二 provider，避免快进双扣）；E2 负责迁到新领域属主模块。

### R3. 每日次数

- 每名玩家每个 `Asia/Shanghai` 自然日最多挑战 3 次；部署机器时区不影响 date key。
- 并发请求不能超次数；是否消耗次数的语义以进入合法战斗为准，失效/过期实例拒绝不得误扣。
- 次数、challenge id 和请求幂等键可审计。

### R4. 原子挑战与真实伤害

- Combat engine 的纯计算不得在 SQLite `BEGIN IMMEDIATE` 写事务内运行。先用短读取得不可变 Boss/玩家快照与固定 RNG seed——**列名以基座实际为准**：Boss 侧是 `world_boss_instances.cas_version`（挑战行记录为 `world_boss_challenges.instance_cas_version`），玩家侧没有 `health_version` 列，版本号就是健康前像 `(current_hp, health_recovered_at)`（见 `data/pve_repository.py::cas_update_player_health`）。在事务外计算战斗；再在单个短 `async with db.transaction() as txn:` 中重新校验 active/expiry/次数和这些版本，以 CAS 写 Boss HP、玩家 `current_hp`、次数、挑战记录、贡献、阶段、末击和事件。
- 版本/CAS 冲突不得把旧战报强行套到新 HP；从最新快照使用同一 challenge id 的确定性 RNG 重新计算并重试，或返回明确冲突。只有成功 CAS 的尝试消耗次数。
- **事务契约**：任一条件写（实例 CAS / 每日次数 / 玩家前像）返回 `False` 时必须立即 `txn.abort()`（或抛出明确冲突错误）再离开事务——事务正常退出等于提交，禁止带半截写入退出。执行顺序固定：实例 CAS 成功 → 扣每日次数 → 玩家 `cas_update_player_health` → 账本/贡献/阶段/事件；任一失败即终止。
- 本场伤害只等于成功写事务中的 `hp_before - hp_after`，不可用 `max_hp - final_hp` 重算历史损血；Boss HP 不得为负。
- 每场只结算玩家战斗 HP 损耗，写回必须走 `data/pve_repository.py::cas_update_player_health`（前像 = 短读的 `current_hp, health_recovered_at`），值为 `max(engine_remaining_hp, 全局单源地板)`——**本 child 不新增 0.01 常量**：E1 把地板上收 `HealthService.defeat_hp_floor` 之前复用 `managers/adventure_manager.py::DEFEAT_HP_FLOOR_RATIO`；若 E1 已交付则直接调该 API，若本 child 先落地则由 **E2 在激活检查点改调**（E2 R2 承接，设计 :886 明确地板全局统一，含世界 Boss）；本玩法每场按败场口径写回（含末击场，设计 :572「世界 Boss 每场本质是必败的 DPS 竞赛」）。禁止用 `HealthService.set_current_hp` 的无条件窄写，`HealthService.compute_max_hp` 只用于算动态上限与地板。战前 settle 必须放在一笔短 `db.transaction()` 内（事务外 settle 触发叶子写，与 bd `-dfb` 的悬空隐式事务竞态冲突）。不得复用普通 PVE 的 600 秒疲劳，不得收取灵石入场费或新增其他挑战税。每日 3 次就是本玩法的稀缺闸门。
- Boss 侧 Fighter 必须以实例 `current_hp/max_hp` 与构建时 `phase` 倍率构建，**不得直接复用** `profile_to_enemy` 的满血面板（`profile_to_enemy` 固定 `hp=max_hp=profile.hp`，复用会让每场从满血开打、实例累计伤害与末击事实全失真；旧实现的真实坑是用 `damage_dealt = max_hp - final_hp` 复算历史损血）。
- 并发挑战至多一个事务把实例变为 defeated，末击者唯一；事务异常或任一条件写失败时全回滚。
- 挑战进入前保留 `BusyState.assert_idle(user_id, template="❌ 你当前正忙，无法挑战Boss！")` 守卫（沿用旧实现语义；禁止手写 user_cd 判断）。
- 使用持久化基座已重构的 transaction-joining Boss repository；本 child 必须沿 challenge 调用图复验无中间 commit，但不重复拥有共享 commit 基础改造。

### R5. 阶段

- 阶段阈值为剩余 HP 60% 与 20%；阶段 2 伤害×1.10，阶段 3 伤害×0.90、护甲×0.50。
- 阶段只前进不回退；一次攻击若从阶段 1 跨过 60% 和 20% 两个阈值，必须在同一提交中按 `phase_2`→`phase_3` 顺序各插入一条唯一业务事件，最终实例 phase=3；不得聚合或漏掉中间阶段，每实例每阶段事件至多一次。

### R6. 台账与未来奖励输入

- 持久化 challenge 明细、按玩家累计真实伤害、profile version、阶段变化和唯一末击事实，支持 Step 7 后续幂等消费。
- 本任务不发明材料/丹药/掉落/分账数值，不调用旧即时灵石奖励作为临时替代。
- `world_boss_challenges.fled` 是基座与历练结算表对称留下的列：世界 Boss **没有逃跑通道**（本玩法的闸门是每日 3 次），该列一律写 0，不得据此推断存在战前选择。

### R7. 提交后事件

- spawn、stage、defeated、dissipated 先产生唯一业务事件；再按发送时的目标快照展开 per-destination delivery，唯一键为 `(event_id, platform, group_id)`，避免一个群成功、另一个群失败后整批重播。payload 只保存稳定 event facts 或 `copy_key + vars`；**文案来源**：`world_bosses.csv` 的 5 个叙事列（spawn/phase2/phase3/kill/dissipate_text）随 profile 契约携带（扩展 `core/enemy_schema.build_world_boss_profile` + `_WB_PROFILE_REQUIRED_KEYS` + **运行期载体 `managers/enemy_catalog.py::WorldBossProfile` 的字段与 `from_dict`**，否则 catalog 装载会静默丢字段；**同批补 `profile_version`**——builder 已产出、`_WB_PROFILE_REQUIRED_KEYS` 已要求，但 `from_dict` 现在丢弃它，实例/台账 `profile_version` 会恒为 0），随出生快照持久化，renderer 只读快照、不在代码硬编码；**文案准入归 E2 的 approval manifest**：本 child 只定义 profile 字段 `narrative_approved: bool` 与运行期门控（未批准不广播），**写入义务归 E2**（sync 从 manifest 叙事结论派生写入 v2 `world_bosses` 段，见 E2 R1/AC1）——否则「占位经 manifest 放行」只放行 sync、不会放开广播；fixture 只验证机械契约；不得复用读取 `stone_reward` 的旧 Boss callback。
- 网络广播不得在数据库事务持锁期间 await；每条 delivery 只能由一个 dispatcher claim。平台不提供接收端幂等，因此不承诺端到端 exactly-once：已知请求未发出可安全自动重试；请求已发但结果不确定则该 destination 进入可审计 `uncertain`、禁止自动重试，只能由管理员接受潜在重复后人工重放。其他已 sent destination 永不因 partial failure 重播。
- 重启不得重复产生业务事件；自动调度对每个 destination 遵守上述状态机。

## Acceptance Criteria

- [ ] AC1：每次新实例在 4 个境界段中全随机且不按玩家境界适配；固定 seed 可复现选择，profile/seed 持久化后重复轮询或幂等重试不重掷；4 只 profile 均可生成不可变快照，活动中配置变化不改面板，难度只改伤害。**已有 `active` 实例时 ensure 不得生成新实例**，`instance_id` 由 `(profile_id, spawn_epoch)` 确定性派生且并发 ensure 只落一行（active 读 + insert 同一事务；首次基准落点见 R1）。**GM/fixture 用 `profile_id` 强制时上述不变式同样成立**（强制只替换选段决策，不改 id 派生、快照与单 active 校验）。
- [ ] AC2：active/48h/defeated/dissipated/12h/24h 状态机在重启和重复轮询下唯一合法。
- [ ] AC3：北京日 3 次在 UTC 边界、服务器不同时区、并发和幂等重试下均正确。
- [ ] AC4：并发挑战不超扣次数或 HP，本场/累计伤害正确且只有一个末击；玩家写回按败场口径 `max(引擎终值, 1% 动态 max_hp)`（10-12 Q4 决议；本玩法每场均按败场口径、含末击场，设计 :572），地板比例复用全局单源、不新增 0.01 常量；挑战只产生 HP 损耗而不增加 fatigue 或收取入场费；combat 不占用写事务，版本冲突以固定 RNG 重算/CAS 处理，故障注入全回滚；CAS 失败方 `attempts_used` 与 Boss HP 均不变，事务无半截提交。
- [ ] AC5：60%/20% 阶段属性通过；阶段1一次跨两阈值时按 phase2→phase3 产生两条唯一事件且最终 phase=3。
- [ ] AC6：spawn/stage/defeat/dissipate 外部发送均在提交后，事务不 await 网络；多平台/多群 partial success 只重试未发送 destination，uncertain 不自动重试且不伪称 exactly-once。
- [ ] AC7：贡献/末击事实可供未来奖励消费；**本 child 新领域**不引用 `stone_reward`/旧即时奖励（旧实现整删归 E2，D 不改动旧路径）。
- [ ] AC8：定向、重启、并发测试及**产品范围 ruff**（与父 PRD R7 同口径，`.trellis/scripts` 存量不计）+ 完整 pytest 通过。
- [ ] AC9（设计 Step 6 遗留④）：用 4 只 profile 快照跑真实引擎，核对场均输出与附录 F（228/393/1035/1123）偏差 ≤±10%，并按「3 次/日 × 2 日」复核四段 HP 可被单活跃玩家磨死；阶段混合场景（phase 1→2→3 按血量 40/40/20 加权）一并收口；正式 config sync 后由 E2 复跑同一断言（±10% 为工程容差、非设计锚；样本沿用附录 F 2000 场/格）。

## Out of Scope

- Step 7 奖励分账与 claim 发放。
- 普通 PVE 逃跑/疲劳。
- 4 只 Boss 之外的新叙事或赛季绑定。
