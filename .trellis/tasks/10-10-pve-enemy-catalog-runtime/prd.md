# PVE 固定名册内容管线与敌人运行时

## Goal

建立从已确认设计内容到确定性运行时档案的唯一管线，使 28 只普通 PVE 敌人与 4 只世界 Boss 不再由旧经验公式和随机抖动生成，同时保留秘境兽/传承守护专项组兼容入口。

## Requirements

### R1. 内容治理与同步 adapter

- 为 `design_docs/content-design/enemies.csv` 和 `world_bosses.csv` 增加 schema 校验与 `scripts/sync_content_to_config.py` adapter。
- 当前内容仍为 `status=draft`、`narrative_status=占位`；adapter 引入独立 `combat_status`（或等价机器字段）后，正式写入必须同时满足 `combat_status=final` 与显式 `--approval-manifest`。manifest 绑定源 CSV SHA-256、获批数据集/列范围和叙事是否可用；实现 adapter 不等于获得同步授权。
- 战斗数值批准与 `narrative_status` 分离：可以只批准战斗列而继续拒绝占位叙事；不得把整份 draft 模糊升为 final。draft、hash 不匹配、列范围越权或缺 manifest 必须 fail closed 且不触碰正式 `config/`。
- 同步输出必须确定性排序、可重复生成，并校验稳定 id 唯一、28+4 数量、段位/类别枚举、数值边界、技能/词条结构和 Boss 阶段阈值。
- 禁止手改脚本生成的配置。

### R2. Enemy Catalog / Resolver

- 配置 schema 无损承载普通敌人的段位、类别、名称、五维、境界、暴击、技能、词条和展示元数据。
- 运行时按 id 与 `(realm_segment, category)` 建不可变索引；普通 PVE 选择返回完整 combat profile。
- 28 只敌人使用绝对面板，移除 `exp_needed`、随机等级、类别倍率与 ±10% 属性抖动的普通怪派生路径。
- `pve.difficulty_multiplier` 只乘伤害，不改变 HP、护甲、身法或迅捷。

### R3. Fighter 映射

- combat profile 到 `FighterState` 必须完整映射 `level_index`、五维、暴击、护甲、触发技能和必要词条。
- B 阶段用真实只读 CSV 渲染到内存/临时目录（不覆盖正式 `config/`），完成 CSV→preview JSON→profile→Fighter 四层逐字段一致性测试；正式 generated config 的同链路复验属于父计划 Batch 5 activation gate。
- 解析和映射为纯运行时职责，不写数据库、不发奖励。

### R4. 专项组兼容

- 保留 `spawn_enemy_from_group(...)` 或等价明确 API，服务秘境兽与传承守护。
- 专项组也输出统一 combat profile/Fighter 映射，但不被 28 只固定名册随机池替换。
- 本任务不重新平衡三只守护者胜率。

### R5. 世界 Boss 内容目录

- 同一同步治理下生成 4 只 Boss profile，含完整五维、技能、60%/20% 阶段规则、48h、每日3次、击杀12h/消散24h元数据。
- 本任务只提供不可变 profile/copy-to-snapshot 输入，不实现 Boss 生命周期或数据库实例。

## Acceptance Criteria

- [ ] AC1：无效数量、重复 id、错误枚举、越界数值和错误阶段阈值均被同步校验拒绝；确定性输出测试通过。
- [ ] AC2：draft、缺失/错误 approval manifest、CSV hash 不匹配及未获批叙事列均 fail closed；只读预览不会生成/覆盖正式配置，且操作说明明确 `combat_status` 与 `narrative_status` 独立。
- [ ] AC3：真实只读 CSV 的 28 只普通敌人关键字段在 preview JSON、profile 和 Fighter 四层一致；正式 generated config 的同链路复验明确留给父计划 Batch 5。
- [ ] AC4：普通怪不再使用旧动态/随机派生；难度回归证明只有伤害变化。
- [ ] AC5：秘境兽和传承守护专项组定向生成及 Fighter 映射回归通过。
- [ ] AC6：真实只读 CSV 的 4 只世界 Boss 可渲染 preview profile 并供后续 child 复制出生快照，但本任务无正式 sync 或实例状态写入。
- [ ] AC7：定向测试及完整 ruff/pytest 质量门通过。

## Out of Scope

- 用户未确认前的正式内容同步。
- 逃跑/疲劳/普通 PVE settlement。
- 世界 Boss 生命周期、贡献和奖励。
- 叙事占位文本创作与 Step 7 经济。
