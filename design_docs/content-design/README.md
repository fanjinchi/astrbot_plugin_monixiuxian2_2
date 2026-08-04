# 玩家侧内容设计工作区：武器 / 功法 / 心法

> 2026-08-06 建立。目标：以 My Brute / Q宠大乐斗 的内容为原型蓝本，按本项目的
> 数值框架（`design_docs/attribute-growth/growth-balance-proposals.md`）适配产出
> 武器、功法、心法的定稿数值，最终生成 `config/weapons.json` / `skills.json` /
> `heart_methods.json`。

---

## 1. 文件形式约定

**数据用 CSV，设计理由用 Markdown，验算用 Python 脚本。**

| 文件 | 内容 |
|---|---|
| `weapons.csv` | 武器设计表（每行一件武器） |
| `skills.csv` | 功法设计表（每行一个功法，含触发技） |
| `heart_methods.csv` | 心法设计表（每行一个心法） |
| `validate_budget.py` | 数值预算验算脚本（§3 速查表的机器校验） |
| `*.md` | 各系统的设计说明、原型对照、适配决策记录 |

为什么用 CSV 而不是 Markdown 表格 / JSON / Excel：

- **方便查看**：任何编辑器 / 表格软件 / PR diff 都直接可读；
- **方便脚本**：Python 标准库 `csv` 即可读取，无需第三方依赖；
- **与项目惯例一致**：`design_docs/attribute-growth/` 的回归数据均为 CSV；
- 嵌套字段（`trigger_skills`、`skill_pool`）以 **JSON 字符串写在单元格内**
  （`*_json` 列），其余列与 `config/*.json` 的字段名一一对应，后续转换脚本可
  机械地 CSV → JSON。

## 2. 列约定

### weapons.csv

| 列 | 对应 config 字段 | 说明 |
|---|---|---|
| `id` / `name` / `weapon_category` / `rank` / `required_level_index` | 同名 | 分类沿用现有 10 类：剑/刀/阔刀/琴/匕首/符箓/鼎/棍/枪/笔 |
| `size_class` | **设计列**（不入库） | 轻/中/重（§4.1 三角定位），决定预算区间与建议 K 值 |
| `base_damage` / `weapon_coefficient_k` | 同名 | 新框架：每击 = base_damage + 伤害属性 × K（`combat_manager.py:566`） |
| `bonus_damage` | `damage` | 武器提供的 +伤害属性词条 |
| `armor_value` / `price` / `shop_weight` | 同名 | |
| `route_mult_ling` / `route_mult_ti` | `route_multiplier.灵修/体修` | 路线倍率 ±20% 以内（§4.2） |
| `trigger_skills_json` | `trigger_skills` | JSON 数组，武器触发技（可空 `[]`） |
| `description` | 同名 | |
| `ref_source` | **设计列** | 原型出处，如 `MB:Leek`、`QPet:接力棒`、`现有配置` |
| `design_note` | **设计列** | 适配修改理由 |
| `status` | **设计列** | `draft` 设计中 / `final` 已定稿 / `legacy` 现有配置参照（仅参考，不计入校验） |

### skills.csv

`pool,id,name,trigger_name,trigger_condition,trigger_rate,effect,effect_value,`
`route_mult_ling,route_mult_ti,learn_coefficient,ultimate_json,description,ref_source,design_note,status`

- `pool`：通用功法池 / 灵修专属 / 体修专属 / 传承功法池（对应 skills.json 的 4 个键）
- 触发技字段平铺为列；`ultimate_json` 为奥义（once_per_battle），无则 `null`
- effect 词表以 `combat_manager.py` 实际支持的为准（设计中遇到的未知效果先记
  `design_note`，定稿前必须核对）

### heart_methods.csv

`id,name,description,rank,required_level_index,passive_bonus_json,skill_pool_json,`
`route,shop_weight,ref_source,design_note,status`

- `passive_bonus_json`：如 `{"hp_percent": 0.1}`；`skill_pool_json`：决定功法池（心法是 build 的"职业"）

## 3. 数值预算速查（机器校验规则）

源自 `growth-balance-proposals.md` §3/§4，验算脚本即按此实现：

| 项 | 规则 |
|---|---|
| 武器每击预算 | 含属性贡献总每击 = `base_damage + (期望伤害+bonus_damage) × K`，须落在同级 HP 的比例区间：轻 1/10~1/8、中 1/8~1/6、重 1/6~1/4 |
| 建议 K 值 | 轻 0.4 / 中 0.5 / 重 0.6（必须 <1，v3.5.0 sim 实测结论） |
| 镜像 TTK | 持同级典型武器 5~10 回合；任何等级不允许 1 回合秒杀 |
| 功法期望增益 | `trigger_rate × (effect_value − 1) ≤ 0.30` / 槽位 |
| 奥义 | ≤ 同级 HP 50%，必中类再减半 |
| 心法被动 | 单条百分比 ≤ 15%，走百分比区加法叠加 |
| 战斗 caps | 闪避 40% / 格挡 30% / 暴击 50% / 暴伤 ≤200% / 受伤减免 40% |

基准成长曲线（验算用）：`HP(L) = 100 + 15×(L−1)`，`伤害(L) = 10 + 3×(L−1)`
（与 proposals §2 的 L10/L99 锚点一致：L10 HP 235 / 伤害 37，L99 HP 1570 / 伤害 304）。

## 4. 工作流

1. **照搬原型**：从 MB/QPet 素材（见 §5）挑选武器/技能，填 `draft` 行，
   `ref_source` 标注原型，数值先抄原型或按直觉占位；
2. **适配修改**：按修仙世界观重命名/重分类，按 §3 预算重算数值
   （`base_damage = max(1, 预算 − 期望伤害×K)`），`design_note` 记录修改理由；
3. **验算**：`uv run python design_docs/content-design/validate_budget.py`，
   全部 PASS 后将 `status` 改为 `final`；
4. **入库**：定稿后由转换脚本（待写）生成/合并进 `config/*.json`，
   跑 `design_docs/attribute-growth/sim_balance_regression.py` 回归。

## 5. 素材来源

- 已有调研（本地，照搬首选）：
  - `design_docs/mybrute/wiki-weapons.md`、`wiki-skills.md`（My Brute 武器/技能全表）
  - `design_docs/qpet-daledou/weapons-skills.md`（Q宠大乐斗武器/技能/升星）
- researcher 补充调研：已完成，成果在 `researcher-similar-games.md`
  （subagent run bafbdf41，2026-08-05）：8 个深读来源、20 类效果 taxonomy 与数值区间、
  平衡手段清单、Q宠神器蓝本、待解 gaps（控制递减/升星消耗公式/复活护盾沉默样本少）。
  可直接照搬的蓝本仍以本地 `design_docs/mybrute/` 与 `design_docs/qpet-daledou/` 为主。

## 6. 现状缺口（本次设计要补的量）

- **功法**：现仅 6 个（通用 2 / 灵修 1 / 体修 1 / 传承 2）—— 极度缺内容；
- **心法**：现仅 5 个 —— 需要按路线/品级成体系；
- **武器**：120 件但数值为旧框架（legacy 行验算普遍超预算），且 L36-L99 无
  境界档位（bd issue `wxg`）—— 需要全量按新预算重做 + 补齐高档。

## 7. 当前进度与下一步

> 2026-08-05 状态快照，供接续会话参考；总跟踪 issue：`bd show hz7`。

- [x] 工作区搭建（CSV 骨架 + 验算脚本 `validate_budget.py`，已跑通）
- [x] researcher 外部调研整合（`researcher-similar-games.md`）
- [ ] **下一步：武器标杆件**——每品级先定 1 件（凡品 L0 → 混元先天 L99），按 §3
  预算定 `base_damage`/`K`，`validate_budget.py` 全 PASS 后再批量扩展同品级变体；
  同步补 L36-L99 境界档位（`wxg`）。注意：重武器取预算低段才能让 TTK≥5。
- [ ] 功法池扩充（现 6 个 → 每池 5-8 个，照搬 MB/QPet taxonomy 适配）
- [ ] 心法成体系（现 5 个 → 按路线 × 品级矩阵补齐）
- [ ] 定稿后写 CSV → config 转换脚本，跑 `design_docs/attribute-growth/sim_balance_regression.py` 回归
