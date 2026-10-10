# Implementation Plan: 世界 Boss 生命周期与原子挑战

## Dependencies and Gate

1. 玩家气血 child 完成。
2. 固定 Boss profile/snapshot contract 完成。
3. 持久化/事务基座的 v37/v38 schema、transaction-joining repository、CAS/claim 和 Boss time-skip provider 通过 Gate 2。
4. 正式内容 sync 需用户确认；领域实现可先用 fixtures。

## Steps

1. 用 shared-schema/concurrency/lifecycle fixtures 固化持久化基座约束和领域状态机。
2. 对接并验证 v37 instance/version、attempt、ledger/contribution 与 v38 business event/per-destination delivery repository；不得在本 child 重新分配 migration 版本或复制 fresh DDL。
3. 实现 4 境界段全随机、非玩家适配的 spawn selector；持久化 spawn seed/selection fact 与固定 profile→不可变出生快照，保证重复 poll/幂等重试不重掷，并实现幂等 lifecycle commands。
4. 沿 challenge 调用图复验所有 Boss 数据操作加入外层 `DataBase.transaction()`，无中间 commit。
5. 实现 Beijing date helper、每日 3 次和 challenge idempotency。
6. 实现 challenge service：短读不可变快照/版本 → 事务外固定 RNG 战斗 → 短写事务 CAS；通过 Health Domain 写回 `max(engine_remaining_hp, ceil(0.25 * max_hp))`，不得写 fatigue 或扣灵石入场费；同时提交真实 HP 差、贡献、phase2→phase3 有序事件、唯一末击和终态，并验证有界冲突重算。
7. 删除旧即时奖励调用，只保留稳定奖励输入事实。
8. 实现稳定 event facts / `copy_key + vars` 的新 renderer 及提交后 business event→per-destination delivery dispatcher，替换旧多平台/多群直接广播与读取 `stone_reward` 的 callback；补 partial success、claim 崩溃、uncertain/人工重放和重启测试。
9. 验证领域生命周期字段与持久化基座已登记的 `TIME_SKIP_ENTRIES` 映射一致，完成并发/故障/完整质量门。

## Rollback Point

在新轮询和 handler 切流前，schema/service 可独立验证。切流前备份数据库；失败时回退代码并恢复备份，不允许旧随机生成器和新实例生成器同时运行。

## Completion Evidence

- v37/v38 shared schema/repository 消费与领域字段映射证据；
- 4 段全随机/固定 seed/重复 poll 不重掷、北京日、生命周期和 time-skip 测试；
- 并发次数/伤害/末击、玩家 25% maxHP floor、无 fatigue/入场费与故障回滚报告；
- 阶段和 outbox 广播测试；
- 证明无 Step 7 奖励调用的静态/行为检查；
- 完整质量门摘要。
