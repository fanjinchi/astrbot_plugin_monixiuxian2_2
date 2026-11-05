# Implementation Plan: PVE 跨系统收口（气血地板与消费者清零）

## Steps

1. 生成静态清单与审计脚本：HP 消费者、`Player.hp`/`else 1` 残留、data/ 之外裸 `conn.commit()`（函数名锚，不写死行号）。
2. 地板 API 上收：`core/health.py` 增 `DEFEAT_HP_FLOOR_RATIO` + `HealthService.defeat_hp_floor`；`AdventureManager._defeat_hp_floor` 改委托；删除本地常量但**保留模块级 re-export**（`tests/test_adventure_settlement_state_machine.py` 从 `_adv_mod` 导入 `DEFEAT_HP_FLOOR_RATIO`）。
3. 战斗接线：`PVECombatManager` 增 `health_service` 注入（`main.py::_wire_core_services`）；`challenge_rift_beast` / `challenge_legacy_guardian` 按 `won ? 引擎终值 : max(引擎终值, 地板)` 经 `set_current_hp` 落库；补秘境/宗门两条入口用例与 PvP 不受地板用例；改写 `tests/test_rift_encounters.py` 旧 `== 1` 断言与注释；两函数 docstring 的「气血降为 1 / HP 下限 1」同步。
4. 暴击双侧接线：`config/game_config.json` + `data/default_configs.py` 补 `combat.base_crit_rate=0.15`；`build_fighter_from_player` 传 `crit_rate`（新增公开读取口）；`build_enemy_fighter` 增 `base_crit_rate` 形参并在 `enemy.crit_rate<=0` 时回退（per-enemy 优先）；补断言：改键后玩家与怪物 fighter 的 `crit_rate` 同步变化、`_base_crit_rate` 不再是死读取、第一季 28+4 默认仍为 0.15。
5. 事务叶子：门控 5 处裸 commit；补静态审计测试；注明 bd `-dfb` 依赖。
6. 消费者组合复核：跨玩法 clamp/restart 回归；静态证明无含混 `Player.hp`（旧 Boss 实现白名单，E2 删除）。
7. 文档与版本：按 PRD R4 清单逐项同步（§Q4 / current-design-report §4.7、§4.12、§4.17、`:208`、`:11`、`:40`、§五 / project-architecture `:74`、`:16`、`:132` / api-overview:108 / pve-enemy-design `:472-476`、`:477-482`、`:755`、`:758-760`、`:883-885` / docstring+行内注释）；改写 §Q4 时一并更正该段已漂移的行号（`:716-717`→`pve_combat_manager.py:504/:568`、`:479` 与 pit#3 `:89`→`combat_manager.py:234`）；`metadata.yaml` version、`README.md` 日志、`/修仙帮助`。
8. 质量门：完整 pytest + 产品范围 ruff。

## Rollback Points

- RP1：地板与消费者改动前备份 DB；任一步失败回到上一提交（无 schema 变更，git revert 即可）。

## Completion Evidence

- 三入口地板数学与落库证据（秘境/宗门/PvP 对照）；
- 暴击双侧接线证据（`combat.base_crit_rate` 写入 config/default_configs、玩家 `build_fighter_from_player` 传参、怪物 `build_enemy_fighter` 回退与 per-enemy 覆盖、改键后双方 fighter 同步变化、`_base_crit_rate` 不再是死读取）；
- 静态清零报告（`Player.hp` / `else 1` / 裸 commit）；
- 文档 diff 与版本清单；
- ruff/pytest 摘要。
