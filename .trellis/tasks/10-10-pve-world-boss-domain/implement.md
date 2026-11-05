# Implementation Plan: 世界 Boss 生命周期与原子挑战

## Dependencies and Gate

1. 玩家气血 child 完成。
2. 固定 Boss profile/snapshot contract 完成。
3. 持久化/事务基座的 v37/v38 schema、transaction-joining repository、CAS/claim 和 Boss time-skip provider 通过 Gate 2。
4. 正式内容 sync 需用户确认；领域实现可先用 fixtures。
5. `EnemyCatalog` 装配（B 的 catalog + `load_catalog()`；v1 → `None` 时领域 disabled）由本 child 在 `main.py::_wire_core_services` 完成，E2 在内容同步后启用。
6. bd `-dfb`（叶子写事务竞态，P1 open）未修前，本 child 并发路径必须全程在 `db.transaction()` 内，禁止事务外叶子写。
7. AC9 的 HP 锚验收用 B 的 preview profile/fixtures 完成（不依赖正式 config），正式 config 复验归 E2。

## Steps

1. 用 shared-schema/concurrency/lifecycle fixtures 固化持久化基座约束和领域状态机，并覆盖 catalog 可用/不可用两种装配状态。
2. 对接并验证 v37 instance/version、attempt、ledger/contribution 与 v38 business event/per-destination delivery repository；不得在本 child 重新分配 migration 版本或复制 fresh DDL。**恢复扫描缺只读查询**：基座只有 `get_event`/`get_event_by_business_key`/`list_deliveries`/`claim_delivery`/`list_stale_dispatching`，本 child 需在 `data/pve_repository.py` 补「已提交但无 delivery 的事件」查询（如 `list_events_without_deliveries`，只读、不改 schema），并说明它与「展开完成标记 / 最近 N 分钟限定」的配合。
3. 实现 4 境界段全随机、非玩家适配的 spawn selector；`instance_id` 用 `(profile_id, spawn_epoch)` 确定性派生（`spawn_epoch := 上一实例 terminated_at + respawn_h`，首次取持久化基准时刻），持久化 spawn seed/selection fact 与固定 profile→不可变出生快照（含 5 个叙事文案列），保证重复 poll/幂等重试不重掷、已有 active 时 ensure 不生成、并发 ensure 只落一行；并实现幂等 lifecycle commands；首次基准取 `system_config` 新键（首次同事务写入）或首个实例 `spawned_at`，ensure 的 active 读 + insert 同一事务。另暴露 `ensure_spawn(profile_id: str | None = None)` 供 GM「生成Boss」/ fixture 强制指定 profile：强制路径仍走同一 `(profile_id, spawn_epoch)` 派生、不可变快照与「单 active」校验，只替换选段决策，并记 warning 日志区分人工触发。
4. 沿 challenge 调用图复验所有 Boss 数据操作加入外层 `DataBase.transaction()`，无中间 commit。
5. 复用基座 `data/pve_repository.py::shanghai_date_key`（不重写时区逻辑），补业务时钟注入与 UTC 15:59/16:00 测试；实现每日 3 次与 challenge idempotency。
6. 实现 challenge service：先在一笔短 `db.transaction()` 内 settle 气血，再短读不可变快照/版本（顺序颠倒会使 CAS 前像必然失效）→ 事务外固定 RNG 战斗 → 短写事务：实例 CAS 成功 → 扣每日次数 → 玩家 `cas_update_player_health`（写 `max(engine_remaining_hp, 全局单源地板)`：E1 前用 `DEFEAT_HP_FLOOR_RATIO`、之后 `HealthService.defeat_hp_floor`（**若本 child 先于 E1 落地，由 E2 在激活检查点改调该 API**，见 R4）；每场按败场口径含末击场，不新增 0.01 常量；Boss Fighter 用实例 `current_hp/max_hp` + 当前 phase 倍率构建，不复用 `profile_to_enemy` 满血面板）→ 账本/贡献/phase2→phase3 有序事件/唯一末击/终态；**任一条件写返回 `False` 立即 `txn.abort()`**；不得写 fatigue 或扣灵石入场费；保留 `BusyState.assert_idle` 守卫；验证有界冲突重算。
7. 新领域不引用 `stone_reward`/旧即时奖励，只保留稳定奖励输入事实；旧实现与其测试的整删归 E2（本 child 不动旧路径）。
8. 实现稳定 event facts / `copy_key + vars` 的新 renderer（文案取自出生快照的 5 个叙事列；需同步扩展 `core/enemy_schema.build_world_boss_profile`、`_WB_PROFILE_REQUIRED_KEYS`、`managers/enemy_catalog.WorldBossProfile` 字段与 `from_dict`（**同批补 `profile_version`**，否则实例/台账版本恒为 0），并在本 child 定义 `narrative_approved` 字段与运行期门控；**该字段的写入义务归 E2 的 sync**（E2 R1/AC1），D 不自己编批准结论；sync golden 同步）及提交后 business event→per-destination delivery dispatcher（**不复用旧 callback**；旧多平台/多群直接广播与读 `stone_reward` 的路径整删归 E2）；补 partial success、claim 崩溃、uncertain/人工重放、**事件提交后无 delivery 的恢复扫描**和重启测试。
9. 验证领域生命周期字段与持久化基座已登记的 `TIME_SKIP_ENTRIES` 映射一致；补 AC9 HP 锚验收（4 只 profile × 真实引擎、阶段 40/40/20 加权、偏差 ≤±10%、3 次/日×2 日磨死复核）；补 `narrative_approved` 门控与 outbox 展开去重（展开完成标记或最近 N 分钟限定）；完成并发/故障/产品范围 ruff + 完整 pytest 质量门。

## Rollback Point

在新轮询和 handler 切流前，schema/service 可独立验证。切流前备份数据库；失败时回退代码并恢复备份，不允许旧随机生成器和新实例生成器同时运行。本 child 只交付 service/poller 函数与 fixture 测试，**不注册 `main.py` 的 poller、不切 handler**（注册与整删旧实现归 E2；poller 复用 `_schedule_boss_spawn` 的指数退避模板）。

## Completion Evidence

- v37/v38 shared schema/repository 消费与领域字段映射证据；
- 4 段全随机/固定 seed/重复 poll 不重掷、北京日、生命周期和 time-skip 测试；
- 并发次数/伤害/末击、玩家 1% maxHP floor（Q4 统一下调）、无 fatigue/入场费与故障回滚报告；
- 阶段和 outbox 广播测试（含 CAS 失败方次数/HP 不变、确定性 `instance_id` 并发 ensure、事件无 delivery 的恢复扫描、catalog disabled、叙事未批准不广播）；
- AC9 HP 锚实测：4 只 profile 场均输出 vs 附录 F（±10%）、阶段 40/40/20 加权、3 次/日×2 日磨死复核；
- 证明无 Step 7 奖励调用的静态/行为检查；
- 完整质量门摘要。
