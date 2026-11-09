# AC9 世界 Boss HP 锚实测证据

- 日期：2026-11-09
- 脚本：`design_docs/content-design/sim_world_boss_anchor.py`（常驻验收门，非一次性原型）
- 命令：`cd data/plugins/astrbot_plugin_monixiuxian2_2 && /home/guigui/code/AstrBot/.venv/bin/python design_docs/content-design/sim_world_boss_anchor.py 2000`
- 口径（照 design_docs/content-design/pve-enemy-design.md 附录 F，:1194 起）：
  - T2 标模双路线（体修 / 灵修），门槛级 = world_bosses.csv level 列（1/10/20/30）；
  - Boss 面板与阶段倍率经生产 mapper `managers/enemy_catalog.py::build_enemy_fighter` 构建；
  - 占位 HP 1e9 使每场必以玩家倒下告终，单场输出 = 1e9 - 终值 HP；
  - 阶段 P1 原生 / P2 伤害×1.1 / P3 伤害×0.9 + 护甲×0.5，按血量占比 40/40/20 加权；
  - 2000 场/格，逐局 `random.seed` 播种，格子 seed = crc32(profile_id|route|phase)。

## 结果（2000 场/格，50.2s，PASS 4/4）

| Boss | profile_id | 体重输出 | 灵重输出 | 平均回合 | 玩家胜率 | 附录 F 锚 | 偏差 |
|---|---|---|---|---|---|---|---|
| 焚山朱厌 | wb_jd_zhu | 989 | 1060 | 18.5 | 0.0% | 1035 | -1.0% |
| 裂峡罴王 | wb_lq_ba | 221 | 229 | 14.1 | 0.0% | 228 | -1.3% |
| 吞象巴蛇 | wb_yy_ba | 1072 | 1173 | 16.8 | 0.0% | 1123 | -0.1% |
| 泽底鼍龙 | wb_zj_tuo | 397 | 382 | 15.3 | 0.0% | 393 | -0.8% |

全部 ≤ ±1.3%，落在 ±10% 锚带内；玩家胜率全格 0%，与附录 F 的占位 HP 前提一致。

## 冒烟（100 场/格，4.5s，PASS）

朱厌 1002/1043（-1.2%）、罴王 227/236（+1.6%）、巴蛇 1046/1151（-2.2%）、鼍龙 405/380（-0.1%）。

## 说明

- 脚本从设计 CSV 走 `scripts/sync_content_to_config.py::render_enemy_document` 渲染预览文档，并在测量时强制 `narrative_approved=True`（仅测量用，不写 config、不改 CSV 批准状态）。
- 生产领域（`managers/world_boss_service.py`）的阶段倍率挑选逻辑与本脚本一致：P2 用 `phase2_damage_multiplier`、P3 用 `phase3_damage_multiplier`（按阶段择一相乘，不连乘），P3 护甲乘 `phase3_armor_multiplier`。
