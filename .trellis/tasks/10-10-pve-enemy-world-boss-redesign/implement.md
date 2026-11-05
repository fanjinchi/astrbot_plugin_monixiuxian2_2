# Implementation Plan: PVE 怪物与世界 Boss 重做总规划

## 1. 执行原则

父任务只负责源需求、依赖顺序、跨 child 验收和上线门，不承载一锅端产品代码。状态（2026-10-28）：A/B/P/C/F 已归档完成；D 规划中（可开工）；E1 收口、E2 内容激活待做。只有用户审批某 child 的规划后，才按 Trellis Phase 2 对其执行 `task.py start` / `trellis-before-dev`。

代码实施批准与内容同步批准是两个不同动作：即使 adapter 已完成，`design_docs/content-design/enemies.csv` 和 `world_bosses.csv` 仍为 draft/叙事占位时，也不得自动写入正式 config。

## 2. Children 与父要求映射

| 顺序 | Child | 覆盖父要求/AC | 主要产物 | 独立回滚点 |
|---|---|---|---|---|
| A | `10-10-pve-player-health-foundation` | R2；AC2 基座 | v35、`base_hp/current_hp/max_hp`、全 HP 消费者、Health Domain、按经过时间的气血恢复 | schema 切换前 DB 备份 |
| B | `10-10-pve-enemy-catalog-runtime` | R1/R3；AC3 | 内容 validator/adapter、固定 catalog、统一 profile/Fighter mapper | 正式 sync 前 config 不变 |
| P | `10-10-pve-persistence-transaction-foundation` | R4–R7 的共享数据基座 | v36…vN、fresh parity、事务叶子审计、settlement/Boss/outbox schema、time-skip matrix | 领域 handler/poller 接线前 |
| F | `10-22-adventure-flee-contract-rework` | R4 逃跑细则；AC4 | 全风险段 pending、逃跑收益 ×0.3/不掉落/不滚传承、败场不滚传承、4 处文案、sect 用例双分支适配 | 单提交 revert（无 schema / config 数值变更） |
| C | `10-10-pve-adventure-settlement` | R4；AC4 | pending、逃跑、current HP、1%战败保底（胜场不保底）、全局疲劳、settlement facts | Adventure handler 切流前 |
| D | `10-10-pve-world-boss-domain` | R5/R6；AC5/AC6 | 四段全随机固定实例、生命周期、北京日次数、HP 地板保底 1%（Q4 统一下调）且无疲劳/入场费、原子挑战/台账、outbox | Boss poller/handler 切流前 |
| E1 | `10-10-pve-cross-system-integration` | R7；AC1/AC7a、AC2/AC4 组合复核 | 全消费者组合复核、PVE 气血地板收口（秘境兽/传承守护者含宗门入口）、暴击双侧接线（`base_crit_rate` 物化）、事务叶子清零、文档与版本 | 地板与消费者收口前备份 |
| E2 | `10-28-pve-content-activation` | R7；AC3b/AC7b 外部门、AC4 激活 | 内容批准/sync/hash、旧 Boss 整删（代码+表 v40+key+测试）、新入口与 poller 原子激活、回滚 | 激活前 DB + generated config 备份 |

Step 7 奖励经济不是 child；只由 C/D 输出稳定事实，待正式秘境设计完成后另建 Trellis 任务。

## 3. 依赖图

```mermaid
flowchart TD
    A[玩家持续气血基座/v35] --> P[持久化与事务基座 v36…v38；v39 归 C]
    P --> C[普通 PVE 结算]
    P --> D[世界 Boss 领域]
    B[内容管线与固定目录] --> C
    B --> D
    C --> F[逃跑契约重拍]
    C --> E1[跨系统收口：地板+消费者]
    D --> E2[内容激活与旧 Boss 整删]
    F --> E2
    E1 --> E2
    U{用户确认正式内容?} -->|是| S[显式 sync + hash/schema 验证]
    U -->|否| W[代码可就绪，但固定名册不宣称上线]
    S --> E2
    E2 --> G[旧 Boss 整删 + 新入口/poller 激活 + 最终回归]
```

A 与 B 可并行；A 的 v35/Health 契约稳定后执行 P；P 与 B 均通过后 C 与 D 可并行，F 与 C 同域先后（F 已完成）；E1 可与 D 并行（只碰地板/消费者，不碰 Boss），E2 在 D、E1 与用户内容批准之后执行。这样避免并行争改 `LATEST_DB_VERSION`、fresh DDL、commit 叶子和 time-skip registry。

## 4. 执行批次与门

### Batch 0 — 规划审批

- 审批本父 PRD/design/implement 和八个 child 工件。
- 不启动实现，不运行内容 sync。

### Batch 1 — Foundations (A + B) ✅ 已完成（2026-10-12）

- A 完成 v35、Health Domain 和所有现有 HP 消费者机械迁移，独立质量门为绿；不得把不可运行的字段迁移红态留给 E。
- B 完成 adapter/catalog/profile，并用真实只读 CSV 渲染内存/临时 preview 做 28+4 四层验证；未经单独确认不覆盖正式 config。
- Gate 1：A/B 各自 AC、定向测试与完整质量门通过；profile 和 Health API 冻结。B 的 preview 通过不等于正式内容已批准，正式 generated config 复验仍在 Batch 5。

### Batch 2 — Persistence and transaction foundation (P) ✅ 已完成（2026-10-13）

- 冻结 v36…vN 连续迁移、fresh parity、PVE/Boss/outbox 最小表、transaction-joining repositories 和 time-skip provider matrix。
- 审计事务入口到叶子的裸 commit，并以故障注入证明 player/busy/settlement/attempt/ledger/outbox 全量回滚。
- Gate 2：v34→latest 不 reset、版本仅成功后推进；schema/repository/CAS/idempotency/registry 契约冻结。

### Batch 3 — Gameplay domains (C + F + D)（C/F 已完成 2026-10-14 / 2026-10-28；D 待做）

- C 完成可重启 ordinary PVE settlement（✅ 已完成 2026-10-14）；F 完成逃跑契约重拍（✅ 已完成 2026-10-28：全风险段选择、收益 ×0.3、不滚掉落/传承）。
- D 完成 Boss 状态机/挑战/台账/outbox，不发放 Step 7 奖励（待做）。
- Gate 3：状态机、并发、异常、restart/time-skip 测试通过；无旧即时奖励渗透。

### Batch 4 — E1 收口（可独立关闭）

- 复核 A 已完成的全消费者迁移；把秘境兽/传承守护者 PVE 气血地板统一到 Health Domain（含宗门领取入口）。
- 暴击双侧接线：`base_crit_rate` 物化进 config + 玩家侧传参 + 怪物侧缺省回退（世界 Boss 侧由 D 经同一 mapper 接线）。
- 清零 data/ 之外剩余事务叶子；更新架构、状态、README/API 文档与版本清单。
- Gate 4：产品范围旧语义清零（旧 Boss 实现按 2026-10-28 决议由 E2 整删，不在 E1 删）；产品范围 ruff/pytest 通过。真实 webtest 仍不运行，除非用户明确要求。

### Batch 5 — E2 内容批准与激活（外部门）

- 向用户展示最终 28+4 CSV 的 `status`/`narrative_status`、批准 manifest/hash/列范围、逃跑参数和生成 diff。
- 用户明确确认后才运行 `scripts/sync_content_to_config.py`。
- adapter 仅接受 `status=final`（`enemies.csv` / `world_bosses.csv` 的战斗数值列；等价于独立战斗数值批准）+ 显式 CLI approval manifest；校验 count/id/schema/hash 后，在同一激活检查点：整删旧 Boss 实现/表/键/测试（清单见 E2 PRD R3；含 v40 `DROP TABLE IF EXISTS boss`），**沿用 D 的 catalog 装配（不重复装配）**、注册新 lifecycle poller（指数退避）与新 handler，**同批执行普通 PVE 调用方切流**（E2 R2：默认出怪改走固定名册、难度系数显式传入、退役旧派生（静态保留为 v1 回落）、删 `enemy_groups` 中 `key=top` 的组），再执行最终功能回归。叙事可否使用占位内容由 manifest 单独记录批准 hash 与列范围，不得把整份 draft 模糊升 final。
- 若 sync、验证或 cutover 任一步失败，新入口不得启用；按 RP 恢复同一代码/DB/config 组合，禁止旧/new 双运行。
- 若用户暂不确认，任务状态应准确记录为“代码就绪、内容启用门待确认”，旧生产入口维持原状，不能伪装完成上线。

## 5. 父级验收矩阵

| Parent AC | Evidence owner | 必须证据 |
|---|---|---|
| AC1 拆分/依赖/回滚 | 父任务 + E2 | 8 children 完整工件、依赖图、4级 rollback checklist |
| AC2 HP 迁移 | A + E1 | v34/fresh/idempotent migration，全消费者静态清零与回归 |
| AC3a 四层一致（可关闭） | B | 真实 CSV→临时 preview→profile→Fighter golden（已交付） |
| AC3b 正式 config 生效（外部门） | E2 | 内容批准 + 正式 sync + 同链路复验 + 旧派生退役 |
| AC4 地板/疲劳/逃跑 | C + E1 | 1%战败保底（历练/秘境/守护者+宗门入口）、疲劳与 time-skip、restart；普通/精英/组内 Boss 胜率·TTK·资源税与天花板档 ≤70% 归 bd -9u2 |
| AC5 Boss 状态/并发 | D + E2 | 四段全随机且不按玩家适配/不重掷、北京日3次、48h/12h/24h、玩家 HP 地板保底 1%（每场按败场口径）且无疲劳/入场费、真实damage、唯一末击、并发/重启；HP 锚复跑（D AC9，E2 正式 config 复验） |
| AC6 广播/奖励边界 | D + E2 | 唯一 business event、per-destination partial-success/uncertain 证据、贡献/末击事实、无 Step 7 数值 |
| AC7a 质量/文档（可关闭） | E1 + E2 | 定向+完整 pytest、产品范围 ruff、文档一致 |
| AC7b 内容双闸门（外部门） | E2 | 独立批准/manifest/hash/列范围、sync 复验 |

## 6. 总回滚策略

项目未上线，不做长期兼容 alias 或双运行。每次 schema/handler/poller/config 切换前保留同一检查点的代码、数据库备份和 generated config hash；回滚必须恢复三者一致组合。禁止新 schema 配旧代码、旧轮询和新轮询同时运行、或手改 generated config 救火。

## 7. 最终 Definition of Done

- 八个 child 的 AC 全部有证据；父 AC1–AC7（AC3/AC7 各含 a/b 两段）逐项关闭，外部门（内容批准）按「代码就绪、内容待批」记录结案。
- Step 0–6 的运行时与权威设计一致；其中动态数值门（普通/精英/组内 Boss 胜率·TTK·资源税、天花板档 ≤70%）以**外部门** bd `-9u2` 关闭为准，世界 Boss HP 锚以 D AC9 + E2 复跑为准；Step 7 明确未实施。
- 只有在内容另行获批并同步验证后，才能称「固定名册玩法已启用」。
- 旧 Boss 数据与结构不迁移（2026-10-28 拍板），旧实现随 E2 激活检查点整删。
- 完整质量门通过；真实 webtest 仅用户另行明确要求。
