# 世界 Boss 生命周期与原子挑战

## Goal

把旧随机、逐步提交的 Boss 流程替换为 4 只固定档案驱动、可重启恢复、并发安全的世界 Boss 领域：48h 生命周期、北京时间每日 3 次、真实伤害贡献、三阶段、唯一末击与提交后事件。

## Dependencies

- 玩家气血 child（A）：current/max HP 与事务友好 API。
- 目录 child（B）：固定 profile/snapshot contract；`EnemyCatalog` 装配由本 child 在 `main.py::_wire_core_services` 注入（catalog 为 `None` 时领域 disabled，E2 在内容同步后启用）。
- 持久化基座（P）：v37 instance/attempt/ledger/contribution、v38 business-event/delivery、CAS/claim repository、commit 纪律、Boss lifecycle time-skip provider；本 child 不新增 migration 版本。
- 正式 profile 启用受用户内容确认门控制。

## Requirements

### R1. 固定实例与出生快照

- 常规生成路径（`ensure_spawn(None)`，即 poller）在 4 个境界段中全随机，不按活跃玩家、全服平均境界或来客境界适配；选中段对应第一季固定 profile。selection fact（`seed`/`selected_profile_id`/`selection_source`/`scheduled_epoch`）、profile id/version 随出生快照持久化，重复轮询或幂等重试不重掷。
- `instance_id` 由 `(profile_id, spawn_epoch)` 确定性派生，并发 ensure 靠主键冲突读回同一行（DDL 无「单 active」唯一约束，靠确定性 id + 状态条件写保证）；ensure 的 active 读 + insert 必须同一 `db.transaction()`。
- **`next_spawn_at` 是再生资格的唯一权威**：实例进入终态（defeated/dissipated）的同一 CAS 批次写 `next_spawn_at = terminated_at + respawn_{kill|dissipate}_h`；`spawn_epoch := 全表最近一条终态实例的 next_spawn_at`，查询写死 `WHERE state IN ('defeated','dissipated') ORDER BY terminated_at DESC, rowid DESC LIMIT 1`（**不要用 `MAX(next_spawn_at)`**：强制生成会打破单调；基座 `list_instances` 只按 `expires_at` 排且只查 active，本 child 需补一条「最近终态实例」只读查询）。无终态实例/首次启动取持久化基准时刻（`system_config` 新键，首次同事务写入，或首个实例 `spawned_at`）。
- ensure 事务内先对 `state='active' AND expires_at <= now` 的行执行幂等过期，再查 `state='active' AND expires_at > now`，存在则直接复用；不得因过期行尚未转换、查询暂时无有效 active 就直接插入。`insert_instance` 返回 `created=False` 时必须校验回读行仍是 `state='active'`，否则按冲突处理；poller 调用顺序见 E2 design §4。
- 出生时复制 profile id/version、名称、境界、最大 HP、五维、技能与阶段规则；活动期间不因配置热更新或旧 level/exp 公式重算面板，难度倍率契约见 R4。移除随机 HP、旧 `stone_reward` 与即时奖励作为权威字段。
- **GM/fixture 强制 profile 入口**：`ensure_spawn(profile_id: str | None = None)`。`None` 走常规选段（poller 只用这一种）；`profile_id` 必须来自 catalog（形如 `wb_lq_ba`），未知 id 或 catalog=None 明确失败并转成玩家可读消息（不回落随机）。**只有管理入口可传 `profile_id`**（顶层 `生成Boss` 受 `BOSS_ADMINS`，与 GM 子命令），普通玩家入口不暴露。
  - 无 active：`None` → 仅 `now >= spawn_epoch` 才生成，否则返回「未到再生时间」；`X` → 跳过资格立即生成，仍写不可变快照、仍按 `(profile_id, spawn_epoch)` 派生 id，记 `selection_source='forced'` 与 warning。
  - 有 active：一律不新建、不替换（禁止双 active），返回既有实例与实际 `profile_id`；GM 文案「已有活跃 Boss {实际名}，未生成 {请求名}」，不带参时为「已有活跃 Boss {实际名}」；功能用例此时不得断言「已生成」。
  - **返回契约**：`ensure_spawn → (instance, created, profile_id)`；**只有 `created=True` 才插 spawn 事件**，复用不再发事件；「有 active + 未知 id」按复用处理，「无 active + 未知 id」才失败。
  - 「12h/24h」只约束再生资格与实例自身终态节奏，强制路径只跳过资格判断。

### R2. 生命周期

- 状态机 `active -> defeated | dissipated`；active 最长 48h；defeated 12h、dissipated 24h 后获得下一实例生成资格。
- 过期检查与终态转换幂等；重启或重复轮询不重复生成或广播。
- expiry/next spawn 绝对时间戳已由 P 在 `managers/boss_manager.TIME_SKIP_ENTRIES` 登记（本 child 只确认、不重复声明，勿建第二 provider）；**本 child 必须保证 `next_spawn_at` 在终态同批写入**，否则该条目永不命中。

### R3. 每日次数

- 每名玩家每 `Asia/Shanghai` 自然日最多 3 次；部署时区不影响 date key；并发不超次数；失效/过期实例拒绝不得误扣；次数、challenge id 与幂等键可审计。

### R4. 原子挑战与真实伤害

- 事务外跑战斗：先短读不可变 Boss/玩家快照与固定 RNG。列名以基座为准：Boss 侧 `world_boss_instances.cas_version`（挑战行 `world_boss_challenges.instance_cas_version`），玩家侧无 `health_version`，前像为 `(current_hp, health_recovered_at)`。
- 单个短 `db.transaction()` 内重新校验 active/expiry/次数与版本；执行顺序固定：实例 CAS → 扣每日次数 → 玩家 `cas_update_player_health` → 账本/贡献/阶段/事件；**任一条件写返回 `False` 立即 `txn.abort()`**。
- 版本/CAS 冲突不得把旧战报套到新 HP：同 challenge id 确定性重算并重试，或返回明确冲突；只有成功 CAS 消耗次数。
- 本场伤害 = 成功写事务中的 `hp_before - hp_after`，不得用 `max_hp - final_hp` 重算历史损血；Boss HP 不为负。
- 玩家写回走 `data/pve_repository.py::cas_update_player_health`，值为 `max(engine_remaining_hp, 全局单源地板)`——地板定义见 **E1 R1**（本 child 不新增 0.01 常量）；每场按败场口径（含末击场，设计 :572）。禁止 `set_current_hp` 无条件窄写；`compute_max_hp` 只算上限与地板。战前 settle 在同一短事务内（避免 bd `-dfb` 的悬空隐式事务竞态）。不得复用普通 PVE 600s 疲劳、不收入场费。
- **难度倍率（唯一定义处）**：世界 Boss 消费 `pve.difficulty_multiplier`，由 `ensure_spawn` 在出生时读取并固化进实例快照字段 `difficulty_multiplier`；同一实例出生后修改配置不改变其伤害，下一实例才使用新值。该倍率只乘伤害，不乘 HP、五维或护甲。
- Boss 侧 Fighter 以实例 `current_hp/max_hp` 与构建时 `phase` 倍率构建，不得复用 `profile_to_enemy` 满血面板（旧坑是 `damage_dealt = max_hp - final_hp` 复算历史损血）。**构建走 `build_enemy_fighter` 并传 `base_crit_rate`**（定义见 `10-10-pve-cross-system-integration/design.md` §3）：先把实例行包装成 `Enemy` 载体（`hp=max_hp=实例值`、`damage=profile.damage×出生快照难度倍率×phase 倍率`、phase3 `armor×0.5`、`crit_rate=0`），再调用；服务未注入 `config_manager` 时自读同一键（回退值同 E1 定义）。**若 E1 形参尚未落地**（Batch 顺序先 D 后 E1），先 `build_enemy_fighter(carrier)`（行为不变），由 E2 激活检查点补传，不得自建 `FighterState`。
- 并发至多一个事务把实例变 defeated，末击者唯一；事务异常或任一条件写失败全回滚。
- 挑战入口保留 `BusyState.assert_idle(user_id, template="❌ 你当前正忙，无法挑战Boss！")`，禁止手写 user_cd 判断。
- 使用基座 transaction-joining Boss repository；沿调用图复验无中间 commit。

### R5. 阶段

- 剩余 HP 60%/20% 两阈值；阶段 2 伤害 ×1.10，阶段 3 伤害 ×0.90、护甲 ×0.50；只前进不回退。
- 一次攻击跨两阈值时，同一提交按 `phase_2`→`phase_3` 各插一条唯一事件，最终 phase=3；每实例每阶段事件至多一次。

### R6. 台账与未来奖励输入

- 持久化 challenge 明细、按玩家累计真实伤害、profile version、阶段变化、唯一末击事实，供 Step 7 幂等消费。
- 不发明材料/丹药/掉落/分账数值，不调用旧即时灵石奖励。
- `world_boss_challenges.fled` 一律写 0（世界 Boss 无逃跑通道），不得据此推断存在战前选择。

### R7. 提交后事件

- spawn/stage/defeated/dissipated 先产生唯一业务事件，再按发送时目标快照展开唯一 `(event_id, platform, group_id)` delivery；payload 只存稳定 facts 或 `copy_key + vars`。
- **文案与 profile 契约（唯一定义处）**：`world_bosses.csv` 的 `spawn_text`/`phase2_text`/`phase3_text`/`kill_text`/`dissipate_text` 五列依次供 spawn、phase2、phase3、defeated、dissipated 事件使用。扩展 `core/enemy_schema.py` 的 `build_world_boss_profile`/`_WB_PROFILE_REQUIRED_KEYS`/`validate_enemy_document` 与 `managers/enemy_catalog.py` 的 `WorldBossProfile`/`from_dict`；五个文案键均为必填字符串，不设代码默认文案；本轮新增的五个文案键与 `narrative_approved` 全部进入 profile/产物必填键集合，无其他新增可选键，除 `narrative_approved` 缺省 `False` 外不提供默认值。`profile_version` 同批补入 `from_dict`（builder 已产出但当前运行时丢弃，否则实例/台账版本恒为 0）。
- **文案准入与单一运行时来源**：profile 另含必填 `narrative_approved: bool`，builder/preview 缺省 `False`；正式 sync 的写入方与批准规则见 E2 R1。该标记为 `True` 时五个文案必须非空，为 `False` 时即使有文案也禁止广播。文案随出生快照持久化，renderer 只读快照，不读取 `narrative_config.json`、`copy_variants.csv` 或运行时 CSV，也不得以代码 fallback 冒充已批准文案。
- 发送不在数据库事务内 await；dispatcher 每轮/启动扫描「已提交但无 delivery 的事件」幂等补展开。`business_events` 无「展开完成」列且不改 schema，因此恢复扫描采用固定「最近 10 分钟窗口」，超窗口不补发；不新增配置项。
- 平台无接收端幂等：已知未发送可安全重试；已发但结果不确定标 `uncertain`、禁止自动重试，只能人工重放；已 sent destination 不因其他目标失败重播。`claim_delivery` 只认 `queued`，陈旧 `dispatching` 由 `list_stale_dispatching` 暴露、管理员判定。

## Acceptance Criteria

- [ ] AC1：常规生成路径 4 段全随机、不按玩家境界适配；`selection_source='seed'` 时固定 seed 可复现、selection fact 持久化后重复轮询不重掷；4 只 profile 可生成不可变快照、活动中配置变化不改面板；难度倍率出生时固化且只改伤害，出生后改键不影响当前实例、下一实例才生效。已有 `active AND expires_at>now` 时 ensure 不生成新实例；旧实例在两次 poll 间到期且新随机 profile 不同的回归中任意时点至多一个 active；`instance_id` 由 `(profile_id, spawn_epoch)` 派生、并发 ensure 只落一行。GM/fixture 强制 `profile_id` 时只替换选段决策（id 派生、快照、单 active、12h/24h 规则照旧，记 `selection_source='forced'`）。
- [ ] AC2：active/48h/defeated/dissipated/12h/24h 在重启与重复轮询下唯一合法；终态同批写 `next_spawn_at`，GM「时间快进」前移它即前移再生资格。
- [ ] AC3：北京日 3 次在 UTC 边界、异时区、并发与幂等重试下正确。
- [ ] AC4：并发挑战不超扣次数/HP，本场与累计伤害正确、末击唯一；玩家写回按败场口径 `max(引擎终值, 1% 动态 max_hp)`（每场含末击场），地板复用 E1 单源、不新增 0.01 常量；挑战不写 fatigue、不收入场费；combat 不占写事务；故障注入全回滚；CAS 失败方次数与 HP 不变。
- [ ] AC5：60%/20% 阶段属性通过；一次跨两阈值产生 phase2→phase3 两条唯一事件且最终 phase=3。
- [ ] AC6：外部发送均在提交后；多平台/多群 partial success 只重试未发送；uncertain 不自动重试、不伪称 exactly-once；无 delivery 事件只恢复最近 10 分钟、超窗不补发；五个文案键与 `narrative_approved` 经 builder→validator→`WorldBossProfile.from_dict` 往返不丢失，缺键/类型错误/已批准但文案为空均 fail closed；narrative 未批准不广播，renderer 无 `narrative_config.json` 或代码文案 fallback。
- [ ] AC7：贡献/末击事实可供未来消费；**本 child 新领域**不引用 `stone_reward`/旧即时奖励（旧实现整删归 E2）。
- [ ] AC8：定向、重启、并发测试 + 产品范围 ruff + 完整 pytest 通过。
- [ ] AC9：4 只 profile 快照跑真实引擎，场均输出对附录 F（228/393/1035/1123）偏差 ≤±10%，按「3 次/日 × 2 日」复核可磨死，阶段 40/40/20 加权；正式 config sync 后由 E2 复跑（±10% 为工程容差、样本 2000 场/格）。

## Out of Scope

- Step 7 奖励分账与 claim 发放、普通 PVE 逃跑/疲劳、4 只之外的新叙事或赛季绑定。
