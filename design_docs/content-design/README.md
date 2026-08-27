# 玩家侧内容设计工作区：武器 / 功法 / 心法

> 2026-08-06 建立。目标：以 My Brute / Q宠大乐斗 的内容为原型蓝本，按本项目的
> 数值框架（`design_docs/attribute-growth/growth-balance-proposals.md`）适配产出
> 武器、功法、心法的定稿数值，最终生成 `config/weapons.json` / `skills.json` /
> `heart_methods.json`。
>
> **路线定位（2026-08-27 起生效）**：灵修/体修的身份差异、成长表定稿、内容三族
> 系数规范与机制预算表统一见 **`route-identity.md`**，填充内容前必读。

---

## 1. 文件形式约定

**数据用 CSV，设计理由用 Markdown，验算用 Python 脚本。**

| 文件 | 内容 |
|---|---|
| `weapons.csv` | 武器设计表（每行一件武器） |
| `skills.csv` | 功法设计表（每行一个功法，含触发技） |
| `heart_methods.csv` | 心法设计表（每行一个心法） |
| `events-canon.csv` | 历练事件叙事表（事件组 key/name + 叙事四列，无数值列） |
| `enemies-canon.csv` | 敌人叙事表（模板 key/name + 叙事四列 + 精英前缀/Boss 名备注） |
| `rifts-canon.csv` | 秘境叙事表（id/name + 叙事四列 + 文案待工程变更备注） |
| `bounty-canon.csv` | 悬赏叙事表（模板 id/name + 叙事四列 + category/difficulty 备注） |
| `validate_budget.py` | 数值预算验算脚本（§3 速查表的机器校验） |
| `lint_narrative.py` | 叙事文案 lint 脚本（禁词/数值承诺/长度/品级冠词/名字一致性 + canon 列校验，sync 第二道闸门） |
| `../../scripts/export_config_to_canon.py` | config → canon CSV 逆向导出补登记脚本（缺失条目以 status=legacy 照抄 config 数值补登，保护其不被 reconcile 删除） |
| `*.md` | 各系统的设计说明、原型对照、适配决策记录 |

> **叙事 canon 四列（2026-09-03 起）**：`weapons/skills/heart_methods` 三表末尾追加
> `canon_origin`（叙事出处，须可查证于 bible 州域/宗门/秘境或通用出处类）、`tone_tier`
> （文风档：正经 / 正经+冷幽默 / 玩梗灰 / 平淡）、`story_hook`（一句话叙事钩子）、
> `narrative_status`（占位 / 待写 / 定稿）。三张 `*-canon.csv` 只含叙事列、不含数值列。
> 文风与禁词规范见 `world-bible.md` §1.3/§5.3；变体量标准见 bible §1.7。

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
| `route_mult_ling` / `route_mult_ti` | `route_multiplier.灵修/体修` | 路线倍率：逐件身份标识，三族取值规则见 `route-identity.md` §3（通用件 1.0；路线向件优势方 1.2~1.4 / 劣势方 0.5~0.7） |
| `trigger_skills_json` | `trigger_skills` | JSON 数组，武器触发技（可空 `[]`） |
| `description` | 同名 | |
| `ref_source` | **设计列** | 原型出处，如 `MB:Leek`、`QPet:接力棒`、`现有配置` |
| `design_note` | **设计列** | 适配修改理由 |
| `status` | **设计列** | `draft` 设计中 / `final` 已定稿 / `legacy` 未收编现存内容登记位（不导入、闸门违例仅 WARN、config 同名条目受 reconcile 保护；删除内容 = 整行移除，收编 = 改 draft 并过预算闸门） |

### skills.csv

`pool,id,name,trigger_name,trigger_condition,trigger_rate,effect_type,effect_value,`
`route_mult_ling,route_mult_ti,learn_coefficient,ultimate_json,description,ref_source,design_note,status`

- `pool`：通用功法池 / 灵修专属 / 体修专属 / 传承功法池（对应 skills.json 的 4 个键）
- 触发技字段平铺为列；`ultimate_json` 为大招（必放制：引擎注入 `trigger_rate=1.0`，不填概率，可配解锁门槛 `min_action_index`/血量阈值），无则 `null`
- `effect_type` 词表以 `combat_manager.py` 的 `EFFECT_HANDLERS` 注册表为准（damage_bonus/combo/stun/counter/damage_reduction；未知效果记 warning 跳过，设计中遇到的未知效果先记
  `design_note`，定稿前必须核对）
- 注：`trigger_condition`/`trigger_rate` 为设计列，入库时经 `sync_content_to_config.py` 归一化映射为引擎键 `trigger_timing`/`trigger_rate`（skills.csv 同步已于 2026-08-08 随 `implement-content-design` 落地，见 `schema-and-engine-fit.md` §4）

### heart_methods.csv

`id,name,description,rank,required_level_index,passive_bonus_json,skill_pool_json,`
`route,route_mult_ling,route_mult_ti,shop_weight,ref_source,design_note,status`

- `passive_bonus_json`：如 `{"hp_percent": 0.1}`；`skill_pool_json`：决定功法池（心法是 build 的"职业"）
- `route_mult_ling` / `route_mult_ti`：设计列，入库后对应 `route_multiplier.灵修` / `route_multiplier.体修`；取值规则（三族：通用/体修向/灵修向，通用件保持 1.0）见 `route-identity.md` §3

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
注：这是**路线中立的验算基准**；2026-08-27 起实际成长为路线分表（`route-identity.md` §2），
内容预算按中立基准评估即可，路线间差异由系数三族而非预算表达。

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

- **功法**：config 现 6 个（通用 2 / 灵修 1 / 体修 1 / 传承 2）；CSV 设计池已扩至 **20 行**
  （2 legacy + 18 draft，2026-08-07，扩充记录与待实现清单见 `skills-ultimates.md` §6）—— 待定稿后同步 config；
- **心法**：现仅 5 个 —— 需要按路线/品级成体系；
- **武器**：120 件但数值为旧框架（legacy 行验算普遍超预算），且 L36-L99 无
  境界档位（bd issue `wxg`）—— 需要全量按新预算重做 + 补齐高档。

## 7. 当前进度

> 2026-08-06 状态快照，供接续会话参考；总跟踪 issue：`bd show hz7`。

- [x] 工作区搭建（CSV 骨架 + 验算脚本 `validate_budget.py`，已跑通）
- [x] researcher 外部调研整合（`researcher-similar-games.md`）
- [x] **武器标杆件**：9 品级 × 1 件已定 draft 且 `validate_budget.py` 全 PASS
  （决策记录见 `weapons.md`：品级门槛按大境界重排 0/11/21/…/81，同步解决
  `wxg` 的 L36-L99 档位缺口；轻/中/重取预算高/中/低段的调参规则已定）
- [ ] 武器变体扩展：以标杆件为锚，同品级同体量件用 bonus/armor/触发技/route_mult 做横向差异
- [x] **功法池扩充 v1**：3 → 20 行 draft（新增通用 5 / 灵修 3 / 体修 4 / 传承 5，照搬
  MB/QPet/researcher taxonomy 适配，`validate_budget.py` 全 PASS；分配规则与待实现
  效果清单（needs_code → bd `tt3`）见 `skills-ultimates.md` §6；升星倒推公式同步
  修正为乘法 0.10；`validate_budget.py` check_skills 扩展支持 combo/counter/stun/纯大招）
- [ ] 心法成体系（现 5 个 → 按路线 × 品级矩阵补齐）
- [x] **设计实现落地（implement-content-design，2026-08-08）**：`sync_content_to_config.py` 升级为 **reconcile 全量重导**（weapons/heart_methods/skills 三类同规则：导入 draft/final 后删除表外条目；legacy 不导入即删除；dry-run DELETE 清单；原子写）；技能行契约（trigger_condition 持久化键、大招禁 trigger_rate、0.x 加性 effect_value）；exp_multiplier 零值保留修复；**route_multiplier 功法侧消费**（loadout 触发技乘 rate/大招乘 value）；**心法 route 装备校验**（5 件专属化：烈火功/太虚功→灵修、龟息功/玄影功/战神诀→体修）；sim 回归 PASS；20 新增测试 + 全量 360 通过
- [x] 定稿后写 CSV → config 转换脚本，跑 `design_docs/attribute-growth/sim_balance_regression.py` 回归
