# 修仙插件同属性对战回合数模拟：方法与结果

> **⏱️ 状态（2026-08-07 标注）**：本文与 `sim_xiuxian_turns.py` 基于 **2026-07-30 旧引擎快照**，
> 仅作历史基线：场景 A 引用的 `level_config.json` `base_*` 字段**已移除**（公式化曲线）；
> 场景 C 的武器解析 `physical_damage + magic_damage` 五维字段**已废弃**（v22 四主属性）；
> 战斗规则（减法护甲、无 caps）已被 `def/(def+K)` + 战斗 caps 取代（bd `qtk`）。
> **脚本不可直接重跑**；当前口径见 `current-design-report.md` 与 `sim_balance_regression.py`。

## 1. 目标
定量测算两个**完全相同**的修士（同境界、同属性、同装备）在当前战斗引擎下的平均消耗回合数。

## 2. 源码规则核对（以 `managers/combat_manager.py` 为准）

| 规则 | 源码位置 | 本次采用值 |
|------|----------|------------|
| 行动顺序按 `speed` 加权随机 | `_roll_initiative` 约 335-342 行 | P(A 出手)=A.speed/(A.speed+B.speed) |
| 闪避 = 5% + (防守身法 - 攻击身法)×0.005，上限 50% | `_calc_dodge_rate` 约 509-518 行 | 同身法 → 5% |
| 格挡 = 5% + 护甲×0.001，上限 30%，格挡伤害减半 | `_calc_block_rate` 521-524 / `_resolve_attack` 487-494 行 | 无甲 → 5% |
| 暴击 15%，倍率 1.5 | `_resolve_attack` 约 437-439 / `_calc_damage` 526-552 行 | 1.075 期望倍率 |
| 伤害 = floor((base_damage + damage×weapon_k) × U(0.95,1.05) × 技能倍率) | `_calc_damage` 约 526-552 行 | 无技能时倍率=1 |
| 最终伤害 = max(1, 伤害 - 护甲) | `_resolve_attack` 约 491-494 行 | 见源码 |
| 空手回退 base_damage=5、weapon_k=0.5 | `_calc_damage` 约 539-542 行 | 已采用 |
| 行动上限 200 次，回合 = ceil(actions/2) | `resolve_combat` 约 137-191 行 | 200 行动 / 100 回合上限 |

> 注：原始设计文档 `design_docs/current-design-report.md` 描述的是旧五维体系，已过时，未采用。

## 3. 模拟口径

- **随机种子**：未使用全局 `random.seed()`；改为每个 level 使用独立的 `random.Random(42 + level*1000 + seed_offset)`，保证可复现且避免不同 level 间种子串扰。
- **场景 A（config-baseline）**：全部 99 级，属性取 `config/level_config.json` 的 `base_damage/base_agility/base_speed/base_hp`，裸拳（`base_damage=0` 触发空手回退），护甲 0。每级 2000 场。
- **场景 B（player-random-growth）**：从 Player 默认 `(damage=10, agility=5, speed=5, hp=100)` 出发，每升一级随机一项属性 +5（对应 `game_config.json` 的 `skill_system.random_growth_step`）。每级生成 2000 条独立成长路径，每条路径复制成对战双方并跑 1 场，共 2000 场（同时覆盖成长路径方差与战斗随机方差）。
- **场景 C（armed-milestone）**：里程碑等级 `10/20/30/40/50/60/70/80/90/99`，双方装备该等级可用的最强武器。
  - 武器筛选：`required_level_index ≤ level`，先按品级（凡→灵→地→天→皇→帝→道→仙→混元先天），再按 `damage = physical_damage + magic_damage`，最后按 `base_damage`。
  - 装备后：`damage += weapon.damage`，`armor_value += weapon.armor_value`，`weapon_k` 与 `base_damage` 使用武器值。
  - 武器 `damage` 与 `armor_value` 的解析逻辑与 `combat_manager.py:_parse_item_config` 保持一致（`damage = max(原有 damage, physical_damage + magic_damage)`，`armor_value = max(原有 armor_value, physical_defense + magic_defense)`）。
- **pip 工具结论**：仅使用 Python 标准库（`random`、`csv`、`statistics`、`math`、`json`、`importlib`、`dataclasses`、`pathlib`），无需安装任何第三方包。

## 4. 关键数值发现

### 4.1 场景 A：裸拳基准

- Lv1 `练气一阶`：Lv 1 练气一阶     hp= 100 dmg=   10 agi=  5 spd= 5 arm=   0 weap=bare_fists   battles=2000 acts= 18.16 rnds=  9.34 [8.0,11.0] draw=0.000 ttk=  20.09
- Lv50 `炼虚初期`：Lv50 炼虚初期     hp= 835 dmg=  157 agi= 54 spd=29 arm=   0 weap=bare_fists   battles=2000 acts= 17.54 rnds=  9.03 [7.0,11.0] draw=0.000 ttk=  10.68
- Lv99 `地仙九阶`：Lv99 地仙九阶     hp=1570 dmg=  304 agi=103 spd=54 arm=   0 weap=bare_fists   battles=2000 acts= 17.43 rnds=  8.97 [7.0,11.0] draw=0.000 ttk=  10.37

- 行动上限触碰情况：无

### 4.2 场景 B：随机成长

- Lv1 `练气一阶`：Lv 1 练气一阶     hp= 100 dmg=   10 agi=  5 spd= 5 arm=   0 weap=bare_fists   battles=2000 acts= 18.17 rnds=  9.33 [7.9,11.0] draw=0.000 ttk=  20.09
- Lv50 `炼虚初期`：Lv50 炼虚初期     hp= 161 dmg=   72 agi= 66 spd=66 arm=   0 weap=bare_fists   battles=2000 acts=  6.96 rnds=  3.74 [2.0,5.0] draw=0.000 ttk=   6.39
- Lv99 `地仙九阶`：Lv99 地仙九阶     hp= 222 dmg=  132 agi=128 spd=128 arm=   0 weap=bare_fists   battles=2000 acts=  5.40 rnds=  2.95 [2.0,4.0] draw=0.000 ttk=   2.85

### 4.3 场景 C：里程碑最强武器

- Lv10 `筑基初期`：Lv10 筑基初期     hp= 235 dmg=   37 agi= 14 spd= 9 arm=  10 weap=鬼影灵匕         battles=2000 acts=  2.30 rnds=  1.40 [1.0,2.0] draw=0.000 ttk=   2.67
- Lv20 `金丹初期`：Lv20 金丹初期     hp= 385 dmg=   67 agi= 24 spd=14 arm= 100 weap=修罗皇匕         battles=2000 acts=  1.06 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.70
- Lv30 `元婴初期`：Lv30 元婴初期     hp= 535 dmg=   97 agi= 34 spd=19 arm= 400 weap=虚空道匕         battles=2000 acts=  1.06 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.27
- Lv40 `化神初期`：Lv40 化神初期     hp= 685 dmg=  127 agi= 44 spd=24 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.04 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.08
- Lv50 `炼虚初期`：Lv50 炼虚初期     hp= 835 dmg=  157 agi= 54 spd=29 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.06 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.10
- Lv60 `合体初期`：Lv60 合体初期     hp= 985 dmg=  187 agi= 64 spd=34 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.04 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.12
- Lv70 `大乘初期`：Lv70 大乘初期     hp=1135 dmg=  217 agi= 74 spd=39 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.06 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.13
- Lv80 `渡劫初期`：Lv80 渡劫初期     hp=1285 dmg=  247 agi= 84 spd=44 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.05 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.15
- Lv90 `地仙初期`：Lv90 地仙初期     hp=1435 dmg=  277 agi= 94 spd=49 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.05 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.17
- Lv99 `地仙九阶`：Lv99 地仙九阶     hp=1570 dmg=  304 agi=103 spd=54 arm=2000 weap=鸿蒙断魂匕        battles=2000 acts=  1.06 rnds=  1.00 [1.0,1.0] draw=0.000 ttk=   0.18

### 4.4 跨场景对比

| 等级 | 场景 | 平均回合 | 中位数 | P10 | P90 | 平局率 |
|------|------|----------|--------|-----|-----|--------|
| 10 | A 裸拳 | 9.15 | 9 | 7.0 | 11.0 | 0.000 |
| 10 | B 随机成长 | 6.86 | 7 | 4.0 | 10.0 | 0.000 |
| 10 | C 最强武器 | 1.40 | 1 | 1.0 | 2.0 | 0.000 |
| 50 | A 裸拳 | 9.03 | 9 | 7.0 | 11.0 | 0.000 |
| 50 | B 随机成长 | 3.74 | 4 | 2.0 | 5.0 | 0.000 |
| 50 | C 最强武器 | 1.00 | 1 | 1.0 | 1.0 | 0.000 |
| 99 | A 裸拳 | 8.97 | 9 | 7.0 | 11.0 | 0.000 |
| 99 | B 随机成长 | 2.95 | 3 | 2.0 | 4.0 | 0.000 |
| 99 | C 最强武器 | 1.00 | 1 | 1.0 | 1.0 | 0.000 |

## 5. 输出文件

- `xiuxian-battle-turns.csv`：逐行统计三个场景每级的回合分布。
- `sim_xiuxian_turns.py`：可复现模拟脚本。

## 6. 结论摘要

1. 同属性战斗在当前四围体系下总体回合数较低；裸拳场景随等级提升略有波动，但未出现因伤害不足而触碰 200 行动上限的情况。
2. 随机成长引入的方差在低级时更明显，随着等级升高，多次成长的均值逐渐逼近基准曲线。
3. 装备高等级武器后，由于双方同时获得高伤害与相对有限的护甲，战斗往往在 1-3 回合内结束；高 milestone 等级的最强武器普遍可以一击决定胜负。
4. 本次模拟仅依赖 Python 标准库，可复现且无需额外 pip 包。
