# Design: skill-engine-fit-and-content-sync

## Context

设计侧已完成武器/心法/功法三套内容表与预算框架（`design_docs/content-design/`，验算 30 PASS / 0 FAIL），但引擎侧存在契约断裂，内容无法生效：

- **bug#1（lvb）**：config 功法用 `effect` 键，`combat_manager._process_trigger_skills` 只读 `effect_type`（L361/L396），归一化层（`skill_manager._apply_star_to_def`）只注入 `trigger_timing` 不改名 → 6 个功法触发技全部静默不触发。
- **bug#2（iup）**：config 大招无 `trigger_rate`，引擎 `ult.get("trigger_rate", 0.0)`（combat_manager.py L481-494）→ `random < 0` 永假 → 万剑归宗/开天辟地从不触发。且大招判定嵌在每次攻击行动里，无任何时机门槛——若简单改必放则退化为开局第一击固定放。
- **升星无界**：`database_extended.py learn_or_star_up`（L514）`new_star = row[0]+1` 无上限；`_apply_star_to_def` 加法 `(star-1)×0.2` → 10 星御剑术期望 +294%。
- **测试盲区**：`tests/test_combat_engine.py` 直接注入引擎格式 dict，绕开 config→归一化→loadout 路径，上述两个 bug 全绿漏网。
- **无入库管道**：三套 CSV 与 config 之间无转换工具；config 按 `name` 键控（`_load_items_data`），武器词条 config 键为 `damage` 而非设计列名 `bonus_damage`。

约束：项目未上线，用户拍板不关心战力通胀过渡（m00164 #3）；KISS；不做超出本范围的引擎扩展。

## Goals / Non-Goals

**Goals:**
- 修复双 bug 并消灭键名双轨制（A3 统一化）
- 大招必放制 + 战况解锁门槛（C 方案），杜绝开局固定放
- 效果分发注册表化，引擎可从 `effect_type` 动态派发，为 v2 效果（tt3）铺路
- 升星 3 星封顶、乘法单一系数、满星修为补偿
- CSV→config merge 转换脚本 + 契约测试 + 修复后配平

**Non-Goals:**
- v2 needs_code 效果引擎化（tt3，依赖本 change 的注册表，后续单独做）
- 功法池数值重做与武器变体扩展（设计侧后续；本 change 只把现有 6 功法配平到预算内）
- 心法 `route_multiplier` 机制（f4t，P3 已立案，随心法 v2）；功法 `route_multiplier` 死配置的处置（随功法池重做）；专属池路线门控（已拍板弱绑定，不锁池）
- 武器 `route_mult` 语义变更（维持只乘属性词条、不乘 base_damage/K）

## Decisions

### D1: 键名统一走 A3（消灭双轨），拒绝 A1 引擎兜底

config、设计 CSV、测试数据全部统一为 `effect_type`；转换脚本强制校验；引擎不加 `or skill.get("effect")` 兼容兜底。

**理由**：双轨制正是 bug#1 的病根——config 契约与引擎契约之间没有单一事实源。A1（引擎兼容两键）让坏路径合法化，下一个手写 config 还会踩。A3 由转换脚本保证输出规范，根治。
**代价**：需一次性迁移 config/skills.json、skills.csv、weapon-skills.md 示例与测试数据（体量小，全部在版本控制内）。

### D2: 大招必放制，概率字段从设计层删除，引擎默认 1.0 作逃生门

- 归一化层（`_apply_star_to_def`）为大招注入默认 `trigger_rate = 1.0`；引擎保持 dumb，不加默认值逻辑。
- skills.csv 删除大招概率列；转换脚本发现大招含 `trigger_rate` 报错。
- 引擎保留 `ult.get("trigger_rate", ...)` 读取能力：未来若做"低率高倍赌博技"，config 显式写概率即可生效，零代码改动。

**理由**：品类惯例（MB Super、QPet 大招均为确定性触发）；概率+限次组合方差极大（放与不放差 4 倍伤害）；"学了一定看得到"的体验确定性；平衡核算只需 value/TTK 一个式子。

### D3: 大招解锁门槛——统一机制，参数化三种时机风格（C 方案）

大招 config 新增可选字段，引擎在现有每场一次判定前加解锁检查：

| 字段 | 语义 |
|---|---|
| `min_action_index` | 自身已行动数 ≥ N 才解锁（延迟型/兜底） |
| `trigger_self_hp_below` | 自身 HP% ≤ 阈值才解锁（逆袭型，如开天辟地 0.5） |
| `trigger_opponent_hp_below` | 敌方 HP% ≤ 阈值才解锁（斩杀型，如万剑归宗 0.4） |

已声明的条件取 AND；未解锁则跳过且不消耗限次资格。FighterState 增加自身行动计数。

**拒绝的替代**：A（纯行动数延迟）——仍是固定节拍，只是挪到中盘，用户明确否决"固定放没设计感"（m00200）；B（门槛+概率窗口）——破坏必放承诺，短局可能整场不放。
**为什么 C 对**：MB 用"消耗品+逐次概率"的不确定性、QPet 用"半血/致死/被击"的战况条件解决同一问题；C 取 QPet 路线且保留必放——时机由战况决定（均势中盘放、逆风提前放、碾压局不用放），修仙"底牌"题材契合；期望核算不变（必放保留，value/TTK 照旧，门槛只影响时机）。

### D4: 效果注册表 + battle_flags（回答"引擎能否动态派发"：现状不能，如此改造）

现状 `_process_trigger_skills` 是扁平 if/elif 链，效果语义硬编码，**无法从 `effect_type` 字段动态获得对应函数**。改造：

```
EFFECT_HANDLERS: dict[str, Callable[[FighterState, FighterState, dict, BattleState], float]]
  - "damage_bonus" / "combo" / "stun" / "counter" / "damage_reduction" 平移现有分支
  - 派发: handler = EFFECT_HANDLERS.get(effect_type)；未知 → logger.warning 跳过
FighterState.battle_flags: dict   # 通用战斗内状态容器（v2 免死/DOT/buff 剩余回合的家）
```

功法与武器挂载共用派发入口（现状本就汇入同一循环，注册表化后契约显式化）。与 D1 键名统一同 PR——改的是同一处代码。

### D5: 升星——3 星封顶、乘法、单一系数、满星修为补偿

- `learn_or_star_up`：star_level ≥ 3 时不再 +1，返回满星标志；`MAX_STAR = 3` 放 config。
- `_apply_star_to_def`：`STAR_UP_RATE_BONUS`/`STAR_UP_EFFECT_BONUS` 合并为 `STAR_UP_BONUS = 0.10`（config 可调）；`rate×(1.1)^(star-1)`（截断 1.0）、`value×(1.1)^(star-1)`。3 星 = ×1.21。
- 满星重复参悟 → 修为补偿 = 品级修为基数 × 折算比例（比例初值 50%，均 config 可调；基数表新增 config 键，落地时参照修为产出曲线定初值）。
- G2 预算按 1 星核算即可（封顶+乘法小系数后膨胀 ≤21%）。

### D6: 转换脚本 merge 模式（现在），--prune 留给终局

`scripts/sync_content_to_config.py`：name 键控 merge（同名更新/新名新增/表外不动）；status 过滤；`bonus_damage→damage` 映射；引擎键契约校验；写盘前跑 `validate_budget.py`，FAIL 中止。武器变体扩完（120 件全入 CSV）后再加 `--prune` 转 replace。**拒绝现在 replace**：CSV 只有 10 武器 + 18 心法，replace 会把 120 件线上内容砍剩 28。

### D7: 契约测试堵盲区，模拟一律走真实代码

新增测试走「config/skills.json → `_apply_star_to_def` → `get_battle_loadout` → 引擎结算」真实路径：断言引擎可读键齐全、大招带门槛可触发、满星补偿正确。后续平衡模拟（sim_balance_regression 扩展）禁止重实现逻辑，一律调生产 loadout + 引擎。

### D8: 配平移出本 change（2026-08-06 m00291 用户拍板）

原计划随修复同 change 完成 G2 配平（万剑归宗/开天辟地降档 2.0 并分配斩杀/逆袭条件）。**用户拍板不配平**：功法池尚未丰富，届时重做池子时统一重新设定数值，现在配平是白做。本 change 交付后游戏处于「引擎已活、功法数值超模」的中间态（未上线可接受）。大招门槛字段（`min_action_index`/`trigger_*_hp_below`）与斩杀/逆袭条件**仍在 tasks §3 配置到位**（机制交付），仅数值不降档。dhh 保留为独立 bd issue，依赖本 change 落地。

## Risks / Trade-offs

- [修复即战力结构剧变：功法从零作用跳到满效，且数值为既有超模值] → 已拍板接受中间态（m00291），项目未上线；配平随功法池重做（dhh）统一处理。
- [斩杀型大招过量伤害浪费（敌 39% 血时 ×3.0 远超斩杀线）] → 视为设计风味（终结演出）；若配平显示浪费过大，落地时降 value 而非加逻辑。
- [门槛参数使期望核算出现战况相关性] → 必放制下期望仍 = value/TTK，门槛只影响时机分布；validate_budget 公式不动。
- [注册表重构触及核心战斗循环，引入回归风险] → D7 契约测试与重构同 PR；现有 test_combat_engine.py 全量回归。
- [满星补偿基数初值拍脑袋] → 机制先行，基数/比例 config 可调，上线前用 sim 校准。
- [大招 unlock 后「学了一定看得到」在极端碾压局不成立（对手死太快）] → 接受：碾压局不需要底牌；`min_action_index` 兜底保证长局必放。

## Migration Plan

1. 代码与 config 同 PR 合入（键名统一是 BREAKING 契约变更，不可分两次部署）。
2. 无数据库 schema 变更；玩家存档的技能引用按 name 存，运行时 loadout 从 config 取，无需数据迁移。
3. 已存在的 >3 星测试数据：项目未上线，直接清档或手动修正，不做迁移脚本。
4. 回滚：git revert 本 PR（代码 + config + 脚本一体）。

## Open Questions

- 满星补偿的品级修为基数表初值（建议落地时参照修为丹/闭关产出曲线定，比例 50% 起步）。
- 斩杀型/逆袭型的血量阈值是否随品级变化（初版统一 0.4/0.5，v2 再说）。
- 满星后再参悟的提示文案（落地时定，需告知玩家折算了多少修为）。
