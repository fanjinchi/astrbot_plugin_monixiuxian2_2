# Implementation Plan: PVE 跨系统迁移与集成上线

## Dependencies

Health、Catalog、Persistence、Adventure、Boss 五个前置 child 全部满足各自 AC 后执行。内容 sync 是独立用户批准门，不可由本任务自行推定。

## Steps

1. 建立全消费者/旧入口静态清单和端到端失败测试。
2. 复核 Health child 已完成的 base/current/max HP 消费者清单，在新 Adventure/Boss 接线后补组合 clamp/跨玩法回归并证明无旧 `hp`；若发现遗漏，回到 Health ownership 修复，不在 E 形成第二套迁移边界。
3. 在 disabled/fixture 状态接线新 ordinary PVE settlement，验证专项组兼容和旧普通动态派生的退役清单；正式内容未批准时不改变生产入口。
4. 在 disabled/fixture 状态接线新 Boss lifecycle/challenge/poller/outbox，验证停用旧 poller/随机生成/直接广播/即时奖励及删除/忽略 `system_config.boss_next_spawn_time` 的 cutover 机制；正式内容未批准时不执行生产切流。
5. 聚合所有到期字段的 `TIME_SKIP_ENTRIES` 并做一次 GM 快进矩阵；验证 health anchor/pending/北京日期键未注册且不受字段快进影响，经过量与跨日另用可注入业务时钟验证。
6. 执行 migration/restart/concurrency/cross-day/functional 回归和完整质量门。
7. 更新架构、状态、README、API/玩法文档。
8. **内容门与原子激活**：向用户展示最终 CSV 的 combat/narrative 独立状态、approval manifest、hash/获批列范围及差异；只有明确批准且 adapter 校验 `combat_status=final` 后才运行 sync。生成配置 count/hash/schema 验证通过后，在同一检查点停用旧普通/Boss 入口和旧 poller/key、启用固定 roster/new poller；任一步失败保持/恢复旧入口且绝不双运行。
9. 记录 content approval、sync、cutover/rollback evidence；真实 webtest 仅用户另行要求。

## Rollback Points

- RP1：消费者迁移前数据库备份；
- RP2：普通 PVE handler 切流前；
- RP3：Boss poller 原子切流前，记录旧 key/入口与新 lifecycle 开关，确保失败时旧/新不能同时运行；
- RP4：内容 sync 前保存 generated config hash/备份。

任一门失败都回到同一 RP 的代码、数据库和配置组合，禁止混搭版本。

## Completion Evidence

- 旧语义/入口静态清单归零报告；
- 集成、time-skip、迁移、并发、功能回归摘要；
- ruff/完整 pytest 结果；
- 文档 diff；
- 用户内容批准记录与 sync/hash 结果（若尚未批准，明确标记为唯一未完成上线门，而非伪造完成）。
