# 修仙插件同属性对战回合数模拟报告

## 1. 任务概述
定量回答：在当前 AstrBot 修仙插件战斗体系下，两个**完全相同**的个体（同境界、同属性、同装备）战斗平均消耗多少回合。

## 2. 产出文件
| 文件 | 说明 |
|------|------|
| `design_docs/attribute-growth/sim_xiuxian_turns.py` | 可复现模拟脚本 |
| `design_docs/attribute-growth/xiuxian-battle-turns.csv` | 三个场景 208 行统计结果 |
| `design_docs/attribute-growth/xiuxian-methodology.md` | 源码核对、公式、方法与关键发现 |

## 3. 模拟规模
- **场景 A（config-baseline）**：1-99 级，每级 2000 场，共 198,000 场
- **场景 B（player-random-growth）**：1-99 级，每级 2000 条成长路径 × 1 场，共 198,000 场
- **场景 C（armed-milestone）**：10/20/30/40/50/60/70/80/90/99，每级 2000 场，共 20,000 场
- **合计**：约 416,000 场战斗

## 4. 关键数值发现
1. **裸拳基准（场景 A）非常稳定**：Lv1 平均 9.34 回合，Lv50 9.03 回合，Lv99 8.97 回合。`level_config.json` 的 HP 成长与伤害成长基本同步，同属性对战回合数不随等级明显变化。
2. **随机成长（场景 B）后期过短**：Lv1 平均 9.33 回合，Lv50 3.74 回合，Lv99 2.95 回合。因为 `random_growth_step=5` 的成长总量远低于基准 HP 成长， damage/hp 比值持续放大，导致 TTK 快速下降。
3. **最强武器（场景 C）普遍一击分胜负**：Lv10 平均 1.40 回合；Lv20 起因为可装备皇品/道品匕首，平均回合降至 1.00；Lv40 起可装备混元先天 鸿蒙断魂匕，全部 1 回合结束。
4. **未触碰 200 行动上限**：全部 416,000 场战斗中，最大回合数为场景 A Lv1 的 14 回合，远低于 100 回合上限。
5. **pip 工具结论**：仅使用 Python 标准库（`random`、`csv`、`statistics`、`math`、`json`、`importlib`、`dataclasses`、`pathlib`），无需安装任何第三方包。

## 5. 源码规则核对（与描述一致处）
- 行动顺序：`speed` 加权随机，`managers/combat_manager.py:_roll_initiative` 约 335 行
- 闪避：同身法 → 5%，`_calc_dodge_rate` 约 509 行
- 格挡：无甲 → 5%，`_calc_block_rate` 约 521 行；格挡伤害减半 `_resolve_attack` 约 487-494 行
- 暴击：15% × 1.5，`_resolve_attack` 约 437 行 / `_calc_damage` 约 526 行
- 伤害公式：`floor((base_damage + damage×weapon_k) × U(0.95,1.05) × 技能倍率)`，`_calc_damage` 约 544 行
- 空手回退：`base_damage=5`、`weapon_k=0.5`，`_calc_damage` 约 539-542 行
- 行动上限：200 行动 / 100 回合，`resolve_combat` 约 137-191 行

## 6. 验证命令
```bash
cd /home/guigui/code/AstrBot
uv run ruff format data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/
uv run ruff check data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/
uv run python data/plugins/astrbot_plugin_monixiuxian2_2/design_docs/attribute-growth/sim_xiuxian_turns.py
```
- ruff format：通过
- ruff check：通过
- 脚本执行：通过，输出 CSV 与 MD

## 7. 残留风险
- 武器选择仅按“品级 → damage → base_damage”排序，未考虑实际游戏内价格/掉率/获取难度。
- 未纳入功法、被动技能、丹药、装备防具等额外系统，结果仅反映裸拳/同武器同属性对战的基准。
- 随机成长路径每级 2000 条独立采样，战斗随机方差与成长路径方差耦合；若需分离两者方差，需额外分层采样。

## 8. 推荐下一步
- 若需验证成长曲线平衡，可对比 `level_config.json` 的 HP/伤害成长斜率与 `random_growth_step` 的总增量。
- 若需评估真实 PvP/PvE 体验，应补充技能、防具、丹药、功法等系统的综合模拟。
