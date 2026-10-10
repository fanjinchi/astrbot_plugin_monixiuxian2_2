# Technical Design: PVE 固定名册内容管线与敌人运行时

## 1. Pipeline

```text
confirmed design CSV --validator/adapter--> generated JSON --loader--> immutable catalog
                                                                  --> resolver --> combat profile --> FighterState
```

adapter 纳入现有 `sync_content_to_config.py`，但正式写路径必须同时校验源行 `combat_status=final`（或等价独立字段）和显式 `--approval-manifest`。manifest 记录 CSV SHA-256、获批数据集/列范围与 `narrative_status` 决策；hash/范围不匹配、draft 或缺 manifest 一律在写文件前 fail closed。战斗列可独立获批，叙事占位不得随整表状态被隐式放行。输出稳定排序，JSON 中带 schema/profile version 与 source/approval hash 以便 Boss 出生快照和后续奖励事实追溯。

## 2. Catalog contracts

普通敌人用稳定 id、段位、category 索引；Boss 用稳定 profile id 索引。加载阶段一次性验证并冻结，调用方只拿完整 profile，不再自己乘段位/类别公式。

`difficulty_multiplier` 在 resolver 的单一位置作用于 damage。测试对同一 profile 使用多个 multiplier，断言只有 damage 改变。

## 3. Compatibility adapter

旧 `spawn_enemy_from_group(...)` 背后的专项配置继续装载；通过 adapter 转成和固定名册相同的 combat profile，复用一个 Fighter mapper。普通目录切换不改变 group 的选择来源和显式 id 行为。

## 4. Content boundary

当前 CSV 仍 draft/占位。adapter 必须支持把真实只读 CSV 渲染到内存或测试临时目录，B 的 golden/四层一致性直接使用该 preview，既验证 28+4 实际设计行又不覆盖正式 `config/`。preview 模式不得接受或伪造正式批准状态；正式写模式对 draft、缺 manifest、hash 漂移和未批准列做负向测试。正式 generated config 仍是父计划 Batch 5 的独立批准门；未批准时旧运行配置不变，普通 PVE child 只能以 preview/fixture 完成代码验收而不能宣称启用固定名册。

## 5. Tests

- validator negative matrix（draft、缺/错 manifest、hash 漂移、列范围越权、占位叙事未获批）与 deterministic golden；
- 28+4 数量/id/schema；
- 每个 profile 的 CSV→JSON→runtime→Fighter 字段；
- 只乘伤害；
- 专项组定向选择/技能映射；
- 旧普通动态派生入口不再被新调用方使用。
