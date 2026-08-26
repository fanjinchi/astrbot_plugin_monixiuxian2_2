# Proposal: dual-route-identity

## Why

灵修/体修双路线目前仅停留在 `cultivation_type` 字段和物品 `route_multiplier` 上：突破成长完全路线盲（`breakthrough_manager.py` 固定气血步长 + 统一权重），两条路线的战斗身份没有数值支撑，内容设计也缺少统一的路线归属规范。本变更确立双路线的身份差异，为第一季（封顶元婴）内容填充提供设计基线。

## What Changes

- **突破成长路线化**：成长权重与气血步长改为按「路线 × 境界段」取表（config 可调），体修初期略强（气血/身法占优）、灵修后期追平（伤害反超、迅捷全程领先），满级面板差距控制在个位数百分比
- **内容三族规范**：武器/心法/功法按路线归属分通用件、体修向件、灵修向件三族；`route_multiplier` 是逐件物品的身份标识（对称偏差），不承担全局平衡职责；通用件保持双边 ≈1.0
- **机制预算表**：按境界段限定可用的技能/武器机制复杂度（练气仅直接增伤/减伤 → 筑基+暴击吸血连击 → 金丹+状态/条件触发 → 元婴+必杀/复合机制）；机制对两条路线均等开放，路线差异体现在构成比例与机制风味上
- **模拟校准**：用 `design_docs/attribute-growth/` 的镜像战工具跑路线对抗模拟，校准成长表数值
- 同步更新 `design_docs/current-design-report.md` 与 content-design authoring 规则

## 已定基调（探索对话结论）

- 体修：本体成长初期略强、身法/闪避全程占优、技能偏数值型但后期同样有机制（肉身风味：反震/护体/浴血类）
- 灵修：迅捷（出手频次）全程领先、伤害后期反超、技能偏机制型（控制/连击/必杀），迅捷 × 触发频率放大机制收益形成自洽身份
- 双方后期都有足够机制丰富度：机制预算表只管解锁时机，不管路线准入
- 体修初期优势的载体 = 成长表 + 前期机制天然吃面板，**不通过通用件系数倾斜实现**

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `attribute-numerics`: 「属性来源：初始属性 + 随机成长」需求修改——随机成长从全局统一权重改为按路线 × 境界段取表，气血步长同样分路线分段

## Impact

- 代码：`core/breakthrough_manager.py` 成长发放逻辑读路线 × 境界段表（约 20 行改动）；`config/game_config.json` 成长配置结构变更
- 内容规范：`design_docs/content-design/README.md`（或新增 authoring 规则文档）写入三族规范与机制预算表
- 模拟：`design_docs/attribute-growth/` 新增/复跑路线对抗校准
- 存量数据：不改玩家已有属性（成长只影响未来突破），无迁移
- 不在本变更内：`max_level` 封顶、内容 CSV 批量填充、宗门扩充（属后续 season1-content 变更）
