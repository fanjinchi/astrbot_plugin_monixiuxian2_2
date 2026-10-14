# 世界 Boss 生命周期与原子挑战

## Goal

把旧随机、逐步提交的 Boss 流程替换为 4 只固定档案驱动、可重启恢复、并发安全的世界 Boss 领域：48 小时生命周期、北京时间每日 3 次、真实伤害贡献、三阶段、唯一末击和提交后事件。

## Dependencies

- 依赖玩家气血 child 的 current/max HP 和事务友好 API。
- 依赖目录 child 的固定 Boss profile/snapshot contract。
- 依赖持久化/事务基座 child 提供 v37 instance/attempt/ledger/contribution、v38 business-event/delivery schema、CAS/claim repository、commit 纪律与 Boss lifecycle time-skip provider；本 child 不再自行分配 migration 版本。
- 基座遗留的事务叶子门控技术债（bd `astrbot_plugin_monixiuxian2_2-qbo`）按「谁接入谁修」归属：`handlers/combat_handlers.py:75` 的裸 `await self.db.conn.commit()` 位于本 child 原子挑战（`async with db.transaction()` 内 CAS 写回）的调用图上，接线前必须先门控（与 adventure-settlement child 共享此点，先接入方负责，后方仅确认已清零）。
- 正式 profile 配置启用仍受用户内容确认门控制。

## Requirements

### R1. 固定实例与出生快照

- 每次新实例在 4 个境界段中全随机选择，不按活跃玩家、全服平均境界或来客境界适配；选中段对应第一季固定 profile。选择用可审计的 spawn seed/selection fact，profile id/version 与 seed 随出生快照持久化，重复轮询或幂等重试不得重掷。
- 出生时复制 profile id/version、名称、境界、最大 HP、五维、技能和阶段规则；活动期间不可因配置热更新或旧 level/exp 公式重算面板，难度倍率只乘伤害。
- 移除随机 HP、旧 `stone_reward` 和即时奖励作为新实例权威字段/行为。

### R2. 生命周期

- 状态机为 `active -> defeated | dissipated`；active 最长 48h。
- defeated 12h 后、dissipated 24h 后获得下一实例生成资格。
- 过期检查和终态转换幂等；重启或重复轮询不重复生成或广播。
- expiry/next spawn 等绝对时间戳登记 GM time-skip。

### R3. 每日次数

- 每名玩家每个 `Asia/Shanghai` 自然日最多挑战 3 次；部署机器时区不影响 date key。
- 并发请求不能超次数；是否消耗次数的语义以进入合法战斗为准，失效/过期实例拒绝不得误扣。
- 次数、challenge id 和请求幂等键可审计。

### R4. 原子挑战与真实伤害

- Combat engine 的纯计算不得在 SQLite `BEGIN IMMEDIATE` 写事务内运行。先用短读取得不可变 Boss/玩家快照与固定 RNG seed——**列名以基座实际为准**：Boss 侧是 `world_boss_instances.cas_version`（挑战行记录为 `world_boss_challenges.instance_cas_version`），玩家侧没有 `health_version` 列，版本号就是健康前像 `(current_hp, health_recovered_at)`（见 `data/pve_repository.py::cas_update_player_health`）。在事务外计算战斗；再在单个短 `async with db.transaction() as txn:` 中重新校验 active/expiry/次数和这些版本，以 CAS 写 Boss HP、玩家 `current_hp`、次数、挑战记录、贡献、阶段、末击和事件。
- 版本/CAS 冲突不得把旧战报强行套到新 HP；从最新快照使用同一 challenge id 的确定性 RNG 重新计算并重试，或返回明确冲突。只有成功 CAS 的尝试消耗次数。
- 本场伤害只等于成功写事务中的 `hp_before - hp_after`，不可用 `max_hp - final_hp` 重算历史损血；Boss HP 不得为负。
- 每场只结算玩家战斗 HP 损耗，写回 `current_hp = max(engine_remaining_hp, ceil(0.01 * dynamic_max_hp))`；不得复用普通 PVE 的 600 秒疲劳，不得收取灵石入场费或新增其他挑战税。每日 3 次就是本玩法的稀缺闸门。
- 并发挑战至多一个事务把实例变为 defeated，末击者唯一；事务异常全回滚。
- 使用持久化基座已重构的 transaction-joining Boss repository；本 child 必须沿 challenge 调用图复验无中间 commit，但不重复拥有共享 commit 基础改造。

### R5. 阶段

- 阶段阈值为剩余 HP 60% 与 20%；阶段 2 伤害×1.10，阶段 3 伤害×0.90、护甲×0.50。
- 阶段只前进不回退；一次攻击若从阶段 1 跨过 60% 和 20% 两个阈值，必须在同一提交中按 `phase_2`→`phase_3` 顺序各插入一条唯一业务事件，最终实例 phase=3；不得聚合或漏掉中间阶段，每实例每阶段事件至多一次。

### R6. 台账与未来奖励输入

- 持久化 challenge 明细、按玩家累计真实伤害、profile version、阶段变化和唯一末击事实，支持 Step 7 后续幂等消费。
- 本任务不发明材料/丹药/掉落/分账数值，不调用旧即时灵石奖励作为临时替代。
- `world_boss_challenges.fled` 是基座与历练结算表对称留下的列：世界 Boss **没有逃跑通道**（本玩法的闸门是每日 3 次），该列一律写 0，不得据此推断存在战前选择。

### R7. 提交后事件

- spawn、stage、defeated、dissipated 先产生唯一业务事件；再按发送时的目标快照展开 per-destination delivery，唯一键为 `(event_id, platform, group_id)`，避免一个群成功、另一个群失败后整批重播。payload 只保存稳定 event facts 或 `copy_key + vars`，由新 renderer 渲染；不得复用读取 `stone_reward` 的旧 Boss callback。
- 网络广播不得在数据库事务持锁期间 await；每条 delivery 只能由一个 dispatcher claim。平台不提供接收端幂等，因此不承诺端到端 exactly-once：已知请求未发出可安全自动重试；请求已发但结果不确定则该 destination 进入可审计 `uncertain`、禁止自动重试，只能由管理员接受潜在重复后人工重放。其他已 sent destination 永不因 partial failure 重播。
- 重启不得重复产生业务事件；自动调度对每个 destination 遵守上述状态机。

## Acceptance Criteria

- [ ] AC1：每次新实例在 4 个境界段中全随机且不按玩家境界适配；固定 seed 可复现选择，profile/seed 持久化后重复轮询或幂等重试不重掷；4 只 profile 均可生成不可变快照，活动中配置变化不改面板，难度只改伤害。
- [ ] AC2：active/48h/defeated/dissipated/12h/24h 状态机在重启和重复轮询下唯一合法。
- [ ] AC3：北京日 3 次在 UTC 边界、服务器不同时区、并发和幂等重试下均正确。
- [ ] AC4：并发挑战不超扣次数或 HP，本场/累计伤害正确且只有一个末击；玩家写回不低于 `ceil(25% * max_hp)`，挑战只产生 HP 损耗而不增加 fatigue 或收取入场费；combat 不占用写事务，版本冲突以固定 RNG 重算/CAS 处理，故障注入全回滚。
- [ ] AC5：60%/20% 阶段属性通过；阶段1一次跨两阈值时按 phase2→phase3 产生两条唯一事件且最终 phase=3。
- [ ] AC6：spawn/stage/defeat/dissipate 外部发送均在提交后，事务不 await 网络；多平台/多群 partial success 只重试未发送 destination，uncertain 不自动重试且不伪称 exactly-once。
- [ ] AC7：贡献/末击事实可供未来奖励消费，但无 Step 7 数值或旧即时奖励。
- [ ] AC8：定向、重启、并发测试及完整 ruff/pytest 质量门通过。

## Out of Scope

- Step 7 奖励分账与 claim 发放。
- 普通 PVE 逃跑/疲劳。
- 4 只 Boss 之外的新叙事或赛季绑定。
