# Technical Design: 世界 Boss 生命周期与原子挑战

## 1. Persistence model

按职责拆分（最终命名可随现有 repository 风格调整）：

- Boss instance：稳定 instance id、全随机境界段选择事实与 spawn seed、profile id/version、不可变出生快照、current/max HP、phase、status、spawn/expires/next_spawn、终态元数据和版本；
- Daily attempts：`(user_id, beijing_date)` 唯一，count≤3；
- Challenge ledger：challenge/idempotency id、instance/user、hp_before/after、真实伤害、玩家气血结果、阶段/终态事实；
- Contribution：`(instance_id, user_id)` 唯一累计，或从不可变 ledger 聚合但需满足性能与审计；
- Business outbox event：event key 唯一、payload 和创建提交状态；
- Outbox delivery：`(event_id, platform, group_id)` 唯一，目标快照、queued/dispatching/sent/uncertain、lease/attempt/error。

旧 boss 表的归档/转换及 fresh schema 已由持久化基座按连续 v37/v38 冻结并以 fixtures 验证；本 child 只消费对应 repository/schema contract，不修改 `LATEST_DB_VERSION` 或重复迁移。由于未上线，Integration 可一次性切换运行入口，但数据库版本仍必须连续、可回滚验证。

## 2. Challenge service

```mermaid
sequenceDiagram
    participant H as Handler
    participant S as BossChallengeService
    participant DB as Database
    participant C as CombatEngine
    participant O as Outbox Dispatcher

    H->>S: challenge(user, instance, idempotency_key)
    S->>DB: short read immutable snapshots + versions
    DB-->>S: boss/player snapshots + version + attempt view
    S->>C: run snapshots with deterministic RNG (no write txn)
    C-->>S: final fighter states
    S->>DB: BEGIN IMMEDIATE; revalidate + CAS versions
    S->>DB: write attempt/boss/player/ledger/contribution/phases/events
    S->>DB: COMMIT
    alt CAS conflict
        S->>S: reload and deterministically recompute, bounded retry
    end
    S-->>H: committed result
    O->>DB: expand/claim committed per-destination delivery
    O-->>H: external broadcast (outside transaction)
```

combat 对短读得到的不可变快照和 challenge 派生的固定 RNG 做事务外纯计算。写事务重新读取版本与状态，只有 `instance_version`、玩家 health version、active/expiry 和次数条件全部成立时才 CAS 提交；冲突后加载最新快照并以同一 challenge id 确定性重算，设置有界重试/明确冲突错误。Boss damage 为成功提交时的 `hp_before - max(0, hp_after)`；`max(engine_remaining_hp, ceil(0.01 * dynamic_max_hp))`，且挑战事务不写 fatigue、不扣灵石入场费。challenge idempotency key 的重复请求返回已提交结果，不再扣次数。这样避免最多 200 回合战报计算长期占用 SQLite 全局写锁。

## 3. Lifecycle and phases

轮询服务调用领域命令而不直接写表：ensure spawn eligibility、expire active、dispatch committed events。生成命令在 4 个境界段中全随机且不读取玩家/全服平均境界；spawn seed 派生选择并与 profile/version 原子持久化，重复 poll 读回既有实例而不重掷。所有终态用 status 条件更新。阶段由持久 max/current 比例计算，只允许升序；一次攻击从 phase 1 跨过 60% 与 20% 时，同一事务按 phase2→phase3 各插入一条唯一事件，最终 phase=3。不得把两阶段聚合为一条。

## 4. Beijing day

集中 helper 用 `ZoneInfo("Asia/Shanghai")` 从业务时钟产生 `YYYY-MM-DD` date key。测试 UTC 15:59/16:00（非夏令时）、部署 TZ 改变及模拟时钟。不得复用本地 `datetime.now().date()`。

## 5. Events

领域事务只插唯一 business outbox event，event key 如 `(instance, type, phase/version)`。payload 是稳定 event facts 或 `copy_key + vars`，由新 renderer 生成消息，禁止把新事件传给读取 `stone_reward` 的旧 Boss object callback。dispatcher 提交后读取当前平台/白名单群并持久化目标快照，展开为唯一 `(event_id, platform, group_id)` delivery；随后逐 delivery 条件 claim 为 `dispatching`，并发 worker 只有一个取得发送权。

平台发送无法提供真正 exactly-once，因此 delivery 状态机明确取舍：调用前已知失败可回 `queued` 自动重试；请求已发但结果不确定标记 `uncertain` 且禁止自动重试，只允许管理员在接受重复风险后显式重放；`sent` destination 永不因同事件其他目标失败而重播。`dispatching` 必须有 lease/owner，只有能证明请求尚未发出的 stale claim 才能自动回收，否则转 uncertain。网络 await 始终在数据库事务外。该接口保证业务事件唯一与 partial success 隔离，不承诺接收端 exactly-once。

## 6. Tests

shared-schema contract、4 段全随机且不按玩家适配、固定 spawn seed 可复现/重复 poll 不重掷、snapshot immutable、lifecycle/time-skip、Beijing date、3次并发、同幂等键、事务外战斗/版本 CAS/有界重算、玩家 maxHP 地板 1%（Q4 统一下调）、无 fatigue/灵石入场费、多人并发击杀、真实 damage、唯一末击、phase1→3 两事件顺序、事务注错回滚、新 renderer 不读取旧奖励字段，以及多平台/多群 delivery partial success、claim 崩溃、uncertain 人工处置。
