# Implementation Plan: 普通 PVE 持久结算与逃跑疲劳

## Dependencies and Gate

1. 玩家气血 child 完成。
2. 固定敌人目录/profile contract 完成。
3. 持久化/事务基座的 v36 schema、repository、commit 审计和 fatigue time-skip provider 通过 Gate 2。
4. 逃跑公式模拟并经用户确认后才启用；代码和测试可先实现参数化槽位。
5. 正式固定名册切换需内容 sync 另行批准。

## Steps

1. 用状态机/并发/崩溃点 fixtures 固化所有风险档统一 `adventure_run_id` 与 settlement 契约。
2. 对接并验证持久化基座的 v36 settlement、终态事实、`(run_id,effect_type)` 唯一副作用记录、持久 fatigue 与 time-skip 字段；不得在本 child 重新分配 migration 版本或复制 schema。
3. 拆分 Adventure 流程为持久 run/encounter generation、choice、事务外确定性 combat resolution、CAS 终态提交和提交后幂等 effect consumption；移除无记录同步旁路及永久 `resolving_combat` 风险。
4. 接入 Health Domain 与固定 Enemy/Fighter mapper；移除 `hp=1` 和内存 fatigue 权威。
5. 实现参数化 flee function、RNG 固化和地板/标模/天花板模拟；在参数封板前保持禁用。
6. 实现完成/迎战/逃跑 handler 接线、重启后查询和终态 replay；把 `main.py` 外置悬赏/师承推进迁到按 run/effect 幂等的消费 seam，不复用 `EncounterStore`。
7. 增加普通/精英/组内 Boss 统计回归、专项组 current HP 回归、计算/CAS 崩溃恢复及副作用重复投递测试。
8. 运行完整质量门。

## Rollback Point

在 handler 切流前，新表和服务可保持未被调用。切流失败则恢复旧调用方并回滚开发数据库备份；不得同时让旧内存 fatigue 和新持久 fatigue 双写成为长期状态。

## Completion Evidence

- v36 schema/repository 消费与领域字段映射证据；
- 状态机、并发、重启、故障和 time-skip 测试；
- 逃跑参数的模拟报告及权威设计回写；
- PVE 统计与完整质量门摘要。
