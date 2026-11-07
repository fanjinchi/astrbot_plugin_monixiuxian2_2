# Technical Design: 世界 Boss 生命周期与原子挑战

## 1. 持久化模型（消费 P 已冻结的 v37/v38）

- Instance：稳定 id、selection fact 与 spawn seed、profile id/version、不可变出生快照（含 5 个叙事列）、current/max HP、phase、state、spawn/expires/next_spawn、终态元数据与 CAS 版本。
- Daily attempts：`(date_key, user_id)` 唯一，count ≤ 3。
- Challenge ledger：challenge/幂等 id、instance/user、hp_before/after、真实伤害、气血结果、阶段/终态事实。
- Contribution：`(instance_id, user_id)` 唯一累计。
- Outbox event / delivery：事件唯一键；`(event_id, platform, group_id)` 唯一，状态 queued/dispatching/sent/uncertain + lease/attempt/error。

本 child 不新增迁移版本。旧 `boss` 表与数据不迁移（2026-10-28），其删除归 E2。

## 2. 挑战服务

```mermaid
sequenceDiagram
    participant H as Handler
    participant S as BossChallengeService
    participant DB as Database
    participant C as CombatEngine
    participant O as Outbox Dispatcher
    H->>S: challenge(user, instance, idempotency_key)
    S->>DB: 短读不可变快照 + 版本 + 次数视图 + 固定 RNG
    S->>C: 事务外确定性战斗
    S->>DB: BEGIN IMMEDIATE; 重校验 + CAS 写 attempt/boss/player/ledger/contribution/phases/events
    alt CAS 冲突
        S->>S: 重读 + 同 challenge id 重算（有界）
    end
    S-->>H: 已提交结果
    O->>DB: 提交后展开/claim per-destination delivery
    O-->>H: 事务外广播
```

事务契约：任一条件写返回 `False` → 立即 `txn.abort()`；顺序为实例 CAS → 扣次数 → `cas_update_player_health` → 账本/贡献/阶段/事件。玩家前像 `(current_hp, health_recovered_at)`，禁止无条件 `set_current_hp`。本场伤害 = `hp_before - max(0, hp_after)`。玩家写回 `max(engine_remaining_hp, 全局单源地板)`（地板定义见 E1）；不写 fatigue、不收入场费。Boss Fighter 用实例面板 + phase 倍率经 `build_enemy_fighter` 构建（难度快照见 prd R4、暴击键见 E1 R2），不复用满血 `profile_to_enemy`。

## 3. 生命周期与阶段

轮询服务只调领域命令，调用顺序见 E2 design §4。常规生成 4 段全随机；GM/fixture 可传 `profile_id` 强制（走同一 id 派生、快照与单 active 校验）。`spawn_epoch := 最近终态实例的 next_spawn_at`（终态同批写；确定性排序见 prd R1）。ensure 事务内先幂等过期到期 active，再发现 `active AND expires_at>now` 直接复用；过期、active 读 + insert 同一事务。

阶段由持久 max/current 比例计算，只升不降；一次跨 60%/20% 时同事务按 phase2→phase3 各插一条唯一事件，最终 phase=3。

## 4. 北京日

集中 helper 用 `ZoneInfo("Asia/Shanghai")` 从业务时钟产 `YYYY-MM-DD`；测试 UTC 15:59/16:00、部署时区变化与模拟时钟；不得用本地 `datetime.now().date()`。

## 5. 事件

领域事务只插唯一 business event；payload 为稳定 facts 或 `copy_key + vars`，由新 renderer 生成，禁止传给读 `stone_reward` 的旧 callback。dispatcher 提交后读取平台/白名单群并持久化目标快照，展开唯一 delivery；逐 delivery 条件 claim，并发只有一个取得发送权。恢复扫描使用 prd R7 的固定窗口（`business_events` 无展开完成列、不改 schema），超窗口不补发。

平台无 exactly-once：已知未发送可回 `queued` 重试；已发但不确定标 `uncertain` 禁止自动重试；`sent` 不因同事件其他目标失败重播。`dispatching` 有 lease/owner，陈旧行由 `list_stale_dispatching` 暴露由管理员处置。网络 await 始终在事务外。

## 6. 测试

- 契约：4 段全随机、固定 seed 可复现、重复 poll 不重掷、快照不可变、GM 强制 profile 三分支（生成/复用并回报/未知 id 失败）。
- 生命周期：48h/12h/24h、time-skip 前移 `next_spawn_at` 即前移资格、重启恢复、到期边界换不同 profile 仍单 active、最近终态同秒确定性排序、北京日 3 次与 UTC 边界。
- 并发/事务：并发挑战唯一末击、CAS 失败次数与 HP 不变、故障注入全回滚、确定性 instance id 并发 ensure 单实例。
- 事件：phase1→3 两事件顺序、partial success、claim 崩溃、uncertain 人工处置、无 delivery 恢复扫描、`narrative_approved` 门控。
- 数值：出生后修改难度配置不影响当前实例、下一实例才生效；AC9 HP 锚（4 profile × 真实引擎，阶段 40/40/20 加权，±10%，3 次/日×2 日磨死）。

## 7. 回滚

切流前备份 DB；失败回退代码并恢复备份，不允许旧随机生成器与新实例生成器同时运行。本 child 只交付 service/poller 函数与 fixture 测试，不注册 poller、不切 handler（归 E2）。
