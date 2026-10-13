# 普通 PVE 持久结算与逃跑疲劳

## Goal

把历练遭遇从一次同步、内存疲劳的流程改为可重启恢复、幂等消费的 settlement，并落实持续气血、败场保底和高/极高风险战前一次逃跑。

## Dependencies

- 依赖玩家气血 child 的 `current_hp` / 动态 `max_hp` / transaction-friendly Health Domain。
- 依赖固定敌人目录 child 的稳定 enemy id 和完整 combat profile。
- 依赖持久化/事务基座 child 提供的 v36 settlement/effect/fatigue schema、CAS/幂等 repository、commit 纪律和 fatigue time-skip provider；本 child 不再自行分配迁移版本或重复定义共享表。
- 基座遗留的事务叶子门控技术债（bd `astrbot_plugin_monixiuxian2_2-qbo`）按「谁接入谁修」归属：`handlers/combat_handlers.py:75` 的裸 `await self.db.conn.commit()` 位于本 child 战斗结算将被 `db.transaction()` 包裹的调用图上，接线前必须先门控（与 world-boss child 共享此点，先接入方负责，后方仅确认已清零）。
- 正式启用固定名册前需通过内容同步用户确认门。

## Requirements

### R1. Settlement 状态机

- 所有风险档在历练开始时生成全局唯一 `adventure_run_id`，并持久化一条 settlement；该 id 同时作为完成请求、终态事实和所有下游副作用的幂等根键。
- 低/中风险不提供选择，但历练完成时仍先持久化已选定 enemy id/profile version、路线基础收益快照、RNG seed/结果和可消费状态，再运行战斗；不得走无记录的同步旁路。
- 高/极高风险在历练完成时进入 `pending_choice`，记录同样的稳定快照；首版不设自动过期。
- settlement 在重启后可查询；迎战/逃跑只能消费一次，并发或重试不得重复收益、重掷敌人或重复战斗。
- 非终态 settlement 保留本次历练 busy，阻止新历练及空闲回血；成功逃跑或战斗终态提交时必须在同一结算边界 clear busy，避免弃置坏遭遇或延迟回血后再战。
- 不得复用进程内、零惩罚语义的 `EncounterStore`。

### R2. 逃跑契约

- 玩家在高/极高风险战斗前可选择迎战或尝试逃跑一次。
- 成功：不进入战斗，`current_hp` 不变；历练机会已经消耗，路线基础收益照常；不产生怪物击败事实或战败疲劳。
- 失败：使用 pending 内同一 enemy id 立即开战；不得再次逃跑或重掷。
- 成功率是玩家/敌人身法关系的单调有界函数。先以配置槽和模拟收口参数，参数写回权威设计后才允许启用；禁止工程手拍常数。

### R3. 战斗与气血

- 玩家 Fighter 从当前 `current_hp` 和动态 `max_hp` 构建；战后只通过 Health Domain 写回 current。
- 战败后当前气血保底为 `ceil(25% * max_hp)`，取和引擎剩余值中合法较高值；不再写旧 `hp=1`。
- Enemy→Fighter 复用目录 mapper；普通、精英和组内 Boss 的选择/结果事实带稳定 profile id/version。
- 秘境兽/传承守护入口迁移 current HP，但不强制使用本历练 pending/逃跑流程。

### R4. 持久疲劳

- 以持久时间戳/状态替代 `AdventureManager._route_cooldowns` 权威；只有实际战败追加 600 秒。
- 疲劳结束时间登记 GM time-skip；重启后仍阻止非法重复路线。
- 玩家保存、busy 清理、pending 终态、路线基础收益与疲劳必须形成明确且可重试的结算边界，不能留下收益已发但 pending 未消费的状态。

### R5. Settlement facts 与奖励边界

- 输出 `adventure_run_id`/settlement id、enemy id/version、风险、战斗结果、current HP 差、是否逃跑、是否击败等稳定事实。
- 路线基础收益、悬赏进度、师承 `adventure_complete` 与 `win_pve` 等下游副作用必须以 `(adventure_run_id, effect_type)` 唯一消费；终态响应 replay 只读取已提交结果/副作用状态，不得再次直接推进。
- 若副作用需要调用当前不支持同事务/幂等的模块，先在 settlement 事务中写入 effect outbox，再由提交后 dispatcher 逐项消费；失败可重试且不能重复业务效果。
- 保持已存在的路线基础收益；不得加入 Step 7 新掉落、材料、丹药或临时正式经济数值。

## Acceptance Criteria

- [ ] AC1：所有风险档都以唯一 `adventure_run_id` 持久化 settlement；高/极高风险 pending 可跨重启恢复，任意档完成/迎战/逃跑的并发重试只产生一个终态和一次路线收益。
- [ ] AC2：逃跑成功完整满足“无战斗、血量不变、基础收益、无击败/疲劳”；失败锁定同敌人且只战斗一次。
- [ ] AC3：概率函数通过单调性、上下界和地板/标模/天花板模拟；未封板参数时功能不可误启用。
- [ ] AC4：胜负均只写 `current_hp`；战败 25% maxHP 保底和 600 秒持久疲劳可观察验证。
- [ ] AC5：重启、stale resolution 恢复、GM time-skip、事务异常和终态重复请求不造成路线收益、击败事实、悬赏/师承进度或疲劳重复。
- [ ] AC6：普通/精英/组内 Boss 回归与设计 TTK/胜率/资源税口径一致；秘境兽/守护者 current HP 回归通过。
- [ ] AC7：无 Step 7 新经济数值；定向及完整 ruff/pytest 质量门通过。

## Out of Scope

- 世界 Boss 生命周期。
- Step 7 正式奖励。
- 守护者独立胜率重标。
