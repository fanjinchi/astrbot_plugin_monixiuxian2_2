# Proposal: 防具内容设计框架（对称 EHP 预算 + armors.csv）

## Why

防具是当前数值体系最明显的空洞：护甲减伤公式已定稿（减伤率 = 护甲/(护甲+K)，同级目标 10~25%），但全游戏防具仅 3 件占位（armor_value 1/10/25），design_docs 无防具预算表，route-identity 满级期望面板（体修护甲 6）还是旧公式遗留。武器/功法/心法三族已建立 canon→config 的内容管线，防具需要以同等规范补齐——且必须以「对称 EHP 预算」为框架，避免把路线不对称偷渡进装备层（定量测算：重甲 25% vs 法袍 8% 的不对称方案会造成跨路线 ~44% EHP 差距，无法由迅捷补偿，直接破坏 route-identity 校准的 50% 胜率）。

## What Changes

- 新建 `design_docs/content-design/armors.csv`：重甲/法袍两族 × 9 品级标杆件，列结构对齐 weapons.csv 约定（含 route_mult_ling/route_mult_ti），新增 `armor_family`、`bonus_hp` 列，删武器专属列。
- 确立对称 EHP 预算框架：重甲（护甲主、HP 辅）与法袍（HP 主、护甲辅）在同等级的等效生命倍率相等；路线向性只通过 route_mult 对称系数表达。
- 确立防具供给曲线：由减伤目标反解 `A = K×r/(1−r)`，重甲 r≈20%、法袍 r≈8%，护甲随要求等级线性增长；HP 辅量由镜像 TTK ≥5 回合约束反推。
- 确立设计纪律：防具只动护甲/HP 两池，**永不挂身法/迅捷**（闪避是差值公式，装备 ±身法直接搬动校准过的闪避差值轴）。
- 修订 `design_docs/content-design/route-identity.md` 满级期望面板：分离"天生护甲"与"装备护甲"，体修护甲身份改由天生护甲 + 路线向装备乘区共同表达。
- 核算 weapons.csv 既有 armor_value（如青铜剑 15）纳入总护甲预算；删除 3 件占位防具（玄铁甲/月华袍/泰坦之铠，用户已拍板不映射、重做），导入须用户确认后由 sync 管线执行（注意 bd bx8 reconcile 地雷）。
- 预算校验扩展：`validate_budget.py` 增加防具校验（供给曲线带、总减伤 ≤40% 含格挡期望、对称 EHP 容差）。
- **依赖**：separate-block-armor-source 先行落地（格挡来源分离是供给曲线的前提）。

## Capabilities

### New Capabilities

- `armor-content`: 防具内容设计规约——供给曲线、对称 EHP 预算、路线向性表达、TTK 验收、与武器护甲的预算合并核算。

### Modified Capabilities

（无——路线身份的数值修订落在 design_docs/route-identity.md 文档层，不改 spec 行为契约）

## Impact

- **文档/内容**：`design_docs/content-design/armors.csv`（新建）、`route-identity.md`（修订满级面板）、`content-design/README.md`（登记 + §6 缺口清单更新）、`design_docs/current-design-report.md`（防具节从"占位"更新为"已定稿"）。
- **工具**：`design_docs` 侧 `validate_budget.py` 增加防具校验规则。
- **配置（导入阶段，用户确认后执行）**：`config/items.json` 防具条目替换（3 件占位 → 18 件标杆件），经 `scripts/sync_content_to_config.py` 管线导入。
- **游戏行为**：玩家可获得成体系的防具供给；同级同装镜像 TTK 保持 ≥5 回合；跨路线带装胜率维持 50%±2。
- **校准**：`sim_route_matchup.py` 需扩展带装场景作为验收手段。
