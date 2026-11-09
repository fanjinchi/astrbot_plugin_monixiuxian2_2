# Implementation Plan: 世界 Boss 生命周期与原子挑战

## 依赖与门

1. A（气血）与 B（目录）已归档；P 的 v37/v38 schema、repository、CAS/claim、time-skip provider 已冻结。
2. 正式内容 sync 需用户确认；领域实现可先用 fixtures。
3. `EnemyCatalog` 装配由本 child 在 `main.py::_wire_core_services` 完成（v1 → `None` → 领域 disabled），E2 在 sync 后启用。
4. bd `-dfb` 未修前，并发路径全程在 `db.transaction()` 内，禁止事务外叶子写。
5. AC9 用 B 的 preview profile/fixtures 完成（不依赖正式 config），正式 config 复验归 E2。

## Steps

1. 用 shared-schema/concurrency/lifecycle fixtures 固化状态机约束，覆盖 catalog 可用/不可用两种装配。
2. 对接 v37 instance/attempt/ledger/contribution 与 v38 event/delivery repository（不新增版本、不复制 fresh DDL）；按 prd R1 补带同秒 tiebreak 的「最近终态实例」只读查询，并按 prd R7 补固定窗口的 outbox 恢复扫描查询（只读、不改 schema）。
3. 实现选段与 ensure：按 prd R1 落地 4 段全随机 + selection fact（`seed`/`selected_profile_id`/`selection_source`/`scheduled_epoch`）随快照持久化、`next_spawn_at` 终态同批写、`spawn_epoch` 取最近终态、事务内先过期到期 active 再读 + insert、`created=False` 校验回读行 active；暴露 `ensure_spawn(profile_id=None)` 强制入口（三分支与返回 `(instance, created, profile_id)` 契约见 prd R1，仅 `created=True` 插 spawn 事件）。补「两次 poll 间到期且新随机 profile 不同」回归，断言任意时点至多一个 active。
4. 沿 challenge 调用图复验无中间 commit（Boss repository 参与外层事务）。
5. 复用 `pve_repository.shanghai_date_key`，补业务时钟注入与 UTC 15:59/16:00 测试；实现每日 3 次与 challenge 幂等。
6. 实现 challenge service：短事务 settle 气血 → 短读快照/版本（顺序颠倒会让 CAS 前像失效）→ 事务外固定 RNG 战斗 → 短写事务（实例 CAS → 扣次数 → `cas_update_player_health` → 账本/贡献/阶段事件/唯一末击/终态；任一条件写失败立即 `txn.abort()`）。玩家写回 `max(engine_remaining_hp, E1 地板)`（E1 未交付时用 re-export 常量，E2 激活检查点改调 API）；难度倍率按 prd R4 在 ensure 出生快照固化，Boss Fighter 由实例面板包装成 `Enemy` 载体后经 `build_enemy_fighter(..., base_crit_rate=…)` 构建（E1 形参未落地时先不传，E2 补传）。补「出生后改难度不改当前实例、下一实例才生效」carrier/伤害测试。不写 fatigue、不收入场费；保留 `BusyState.assert_idle`；验证有界冲突重算。
7. 新领域不引用 `stone_reward`/旧即时奖励，只保留稳定输入事实；旧实现与其测试的整删归 E2（本 child 不动旧路径）。
8. 按 prd R7 扩展共享 Schema 与 `WorldBossProfile` 往返契约，实现 event renderer（只读出生快照五文案与 `narrative_approved`，不接 `narrative_config.json`/代码 fallback）与 dispatcher（逐 destination claim，网络 await 在事务外；partial success、claim 崩溃、uncertain 人工处置、无 delivery 恢复扫描使用 R7 固定窗口）。补窗口边界、builder 缺省 false、profile 往返、缺键/类型错误/已批准空文案 fail-closed 与未批准不广播用例；正式 sync 的批准转换与真实配置加载验收归 E2。
9. 验证生命周期字段与 `TIME_SKIP_ENTRIES` 映射一致；补 AC9 HP 锚（4 profile × 真实引擎、阶段 40/40/20 加权、±10%、3 次/日×2 日）；补 GM 强制 profile 三分支与时间快进前移再生资格用例；完成产品范围 ruff + 完整 pytest。

## 回滚点

切流前备份 DB；失败回退代码并恢复备份。本 child 只交付 service/poller 函数与 fixture 测试，不注册 poller、不切 handler。

## 完成证据

- v37/v38 repository 消费与字段映射证据；
- 选段/强制 profile（生成·复用·失败）、`next_spawn_at` 终态写入与 time-skip 前移、到期换 profile 单 active、出生后难度改键、北京日、生命周期、重启恢复测试；
- 并发次数/伤害/末击、地板写回与无 fatigue/入场费、故障回滚报告；
- 事件顺序、partial success/uncertain、恢复扫描、catalog disabled、narrative 未批准不广播；
- AC9 HP 锚实测（4 只 profile vs 附录 F、±10%、3 次/日×2 日）；
- 无 Step 7 奖励调用的静态/行为检查；产品范围 ruff + pytest 摘要。
