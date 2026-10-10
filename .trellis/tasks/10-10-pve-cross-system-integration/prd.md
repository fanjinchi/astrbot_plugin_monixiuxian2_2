# PVE 跨系统迁移与集成上线

## Goal

在气血、目录、持久化基座、普通 PVE 和世界 Boss 五个前置 child 完成后，组合复核所有气血与战斗消费者，切断旧动态敌人/旧 Boss 奖励路径，完成 poller 原子切流、time-skip、广播、文档、全量回归和可恢复上线检查。

## Dependencies

- 玩家持续气血领域与 v35 数据库迁移。
- 固定名册内容管线与敌人运行时。
- v36…vN 持久化/事务基座。
- 普通 PVE 持久结算与逃跑疲劳。
- 世界 Boss 生命周期与原子挑战。
- 内容 CSV 正式同步仍需单独取得用户确认；未确认时只可完成代码集成与 fixture 验证。

## Requirements

### R1. 全消费者组合复核

- Health child 已原子迁移创角、突破、装备、功法、丹药、商店、GM、PvP、现有 PVE/秘境/Boss 和显示/排行消费者；本 child 负责在新 Adventure/Boss 流程接线后静态清零并做跨玩法组合回归，不把基础 `Player.hp` 迁移留到此处。
- 产品代码和测试不得遗留 `Player.hp`、含混属性键或“战败写1”语义。
- 属性变化、购买/使用药品和跨玩法战斗均维护 current clamp。

### R2. 旧路径退役

- 普通 PVE 不再调用旧 exp/随机动态敌人派生；专项 group 兼容路径保留且可回归。
- 旧 Boss 随机生成、历史损血误算、逐步 commit 和即时奖励路径必须在新玩法激活后从 handler/轮询不可达；旧 `system_config.boss_next_spawn_time` 同时删除或明确忽略，不再是真相源。旧 poller 停用与新 lifecycle poller 启用必须在内容批准、sync/hash 验证后的同一 cutover 检查点完成，禁止未批准先切流或旧/new 双运行。
- Step 7 未完成前不得用兼容代码新增掉落或分账数值。

### R3. 时间与事件集成

- PVE fatigue、Boss expiry/respawn 等到期字段登记 time-skip；health recovery anchor、pending、北京日期键不登记。GM `/时间快进` 不改变业务时钟，须验证它不修改 anchor、不额外恢复或重置当日次数；经过量与跨日另用可注入业务时钟测试。PVE pending 首版无自动过期，须验证 busy 跨重启保持并在终态原子清除。
- spawn/stage/defeated/dissipated 广播只消费提交后 business event 与 per-destination delivery；已 sent 目标不因 partial failure 重播，已知未发送可安全重试，发送结果不确定则禁止自动重试并进入可审计人工处置；不承诺平台 exactly-once，事务中没有平台网络 await。
- 北京日次数不受服务器 TZ 或其他本地日期逻辑影响。

### R4. 内容与启用门

- 代码合入、内容确认、正式 sync/hash 验证、旧入口停用与新领域启用分为清晰检查项；后两项必须落在同一原子激活检查点，未获内容确认时新入口保持 disabled、旧入口维持原状。
- 未获用户确认不得把 draft/占位 CSV 同步进正式配置，也不得声称固定名册已经上线。正式 adapter 只接受独立 `combat_status=final`（或等价字段）及显式 approval manifest；manifest 绑定 CSV hash、获批列范围和 `narrative_status` 决策。
- sync 后运行 profile count/hash/schema 和运行时 smoke；hash/列范围不符或叙事未获批即 fail closed，失败则停止启用而非手改配置。

### R5. 测试和文档

- 扩充单元/迁移/功能用例，覆盖重启、并发、跨日、过期、台账、广播幂等、逃跑和当前气血。
- 运行完整 ruff/pytest；真实 webtest 仅用户明确要求时运行。
- 更新 `design_docs/project-architecture.md`、`design_docs/current-design-report.md`、`design_docs/README.md` 及相关 API/玩法说明，使 Step 7 边界和占位叙事状态清晰。

## Acceptance Criteria

- [ ] AC1：全仓静态搜索和定向测试证明无含混 `Player.hp`/属性键/战败写1；所有消费者使用正确层级。
- [ ] AC2：旧普通怪派生和旧 Boss 生成/即时奖励路径从运行入口不可达，专项组兼容仍通过。
- [ ] AC3：普通 PVE 与 Boss 端到端均维护 current HP、幂等事实和重启恢复；time-skip 全字段集成测试通过。
- [ ] AC4：Boss 广播提交后按 destination 执行，partial success 不重播已 sent 目标、uncertain 可审计人工处置，事务测试证明没有持锁网络发送且文档不伪称 exactly-once。
- [ ] AC5：combat/narrative 独立确认、manifest/hash/列范围、sync/启用 checklist 可执行；draft/未确认/不匹配时不会修改正式 config。
- [ ] AC6：迁移、定向、功能用例和完整 `uv run ruff format .`、`uv run ruff check .`、`uv run python -m pytest tests/ -v` 通过。
- [ ] AC7：架构/状态/README/API 文档与实现一致，并明确 Step 7 仍未实施。

## Out of Scope

- 未经用户要求的真实 webtest。
- Step 7 奖励经济、正式秘境生态和叙事创作。
- 战斗引擎通用公式再平衡。
