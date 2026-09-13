# Tasks — combat-result-winner-identity

## 0. 前置检查

- [ ] 0.1 重新锚定行号：确认 `busy-state-owner` / `add-transaction-unit-of-work` 未改动 `managers/combat_manager.py` 结算段与 `pve_combat_manager.py` 的消费者行；有变动则按当时代码更新本文件全部行号引用
- [ ] 0.2 全仓 grep 基线：`result.winner` / `"winner"` / `startswith("enemy_")` / `isinstance(winner` 的消费者清单与 design.md Context 枚举一致

## 1. 引擎接口重构（combat_manager.py）

- [ ] 1.1 `managers/combat_manager.py:168-177` `CombatResult`：删 `winner: str`，新增 `winner_side: Literal["fighter1", "fighter2", "draw"]` 与 `winner_id: str | None`（docstring 注明：平局时 `winner_side == "draw"` 且 `winner_id is None`；id 仅为便捷查询，身份编码语义由引擎内部消化）
- [ ] 1.2 `resolve_combat` 结算分支（:341-363）：四个分支逐一代换——`winner = fighter2.user_id` → `winner_side = "fighter2"; winner_id = fighter2.user_id`；`fighter1.hp <= 0` 分支同理；三个平局分支 → `winner_side = "draw"; winner_id = None`；banner/flavor 逻辑一行不动；`CombatResult(...)` 构造（:370-377）同步改字段名
- [ ] 1.3 `CombatManager.player_vs_player` legacy dict（:1518）：`"winner": result.winner` → `"winner": result.winner_id or "draw"`（值域不变，runtime 无消费者，测试断言原样通过）

## 2. 运行时调用点改查询/显式比较

- [ ] 2.1 `managers/pve_combat_manager.py`：
  - `_calculate_rewards`（:234-248）：删 `isinstance(winner, str) and winner.startswith("enemy_")`，改 `is_enemy_winner = result.winner_side == "fighter2"`（该路径 fighter1 恒为玩家）；`is_draw = result.winner_side == "draw"`
  - `_format_combat_result`（:273-275）：同上改写
  - `trigger_pve_combat` legacy dict（:357）：`"winner": result.winner_id or "draw"`（下游 `_calculate_rewards`/`_format_combat_result` 接收的 dict 值域保持不变）
  - `challenge_rift_beast`（:412-413）：`won = result.winner_id == player.user_id` 语义不变（design D5 显式比较），`is_draw = result.winner_side == "draw"`；**核对 fighter1 归属为玩家**；`:409-411` 的补丁注释更新为「接口已结构化，前缀判定不可复活」类简述
  - `challenge_legacy_guardian`（:467-468）：同上
- [ ] 2.2 `managers/boss_manager.py:427-520`：`winner = result.winner` → 结构化读取；`:480` `if winner == "draw"` → `result.winner_side == "draw"`；`:513` legacy dict `"winner"` 值 = `result.winner_id or "draw"`；**核对 fighter1 归属**（玩家侧）并据此选 side 或 id 比较
- [ ] 2.3 `managers/impart_pk_manager.py:115-119`：`result.winner == "draw"` → `result.winner_side == "draw"`；`attacker_wins = result.winner == attacker.user_id` → `result.winner_id == attacker.user_id`；**核对 attacker 对应 fighter1**（engine 调用处 :107 的实参顺序）
- [ ] 2.4 收尾 grep：运行时代码（main.py、handlers/、managers/、core/）`startswith("enemy_")`、`isinstance(winner` 零命中；`result.winner`（裸字段）零命中

## 3. 测试与 design_docs 脚本同步

- [ ] 3.1 测试更新（构造 `CombatResult(winner=...)` → `winner_side=/winner_id=`；断言 `result.winner` → `result.winner_side`/`winner_id`）：`tests/test_combat_engine.py`（:503,:515,:546 等多处）、`tests/test_combat_report_structure.py`（:177,:195,:219）、`tests/test_trigger_effect_extensions.py`（:358-382,:704,:739）、`tests/test_rift_encounters.py`(:486 桩与 :530 用例）、`tests/test_boss.py`（:91,:359,:401,:443）、`tests/test_pve_combat.py`（:68,:380,:470,:545）；注意 `winner="draw"` 构造点改 `winner_side="draw", winner_id=None`
- [ ] 3.2 `design_docs/attribute-growth/` 脚本胜负读取改 `winner_side`：`sim_route_matchup.py`（:154-160,:388,:413-419）、`sweep_route_growth.py`（:124-129）、`sim_balance_regression.py`(:317)、`sim_xiuxian_turns.py`(:275)、`rebalance_equipment.py`(:517)；按各脚本 fighter1 归属选 `"fighter1"/"fighter2"` 比较（脚本里 `== "体修"` 按名字判定的点改按侧判定，站位以脚本内 FighterState 构建为准）
- [ ] 3.3 校准复现验证：改造前后对 `sim_route_matchup.py` 跑同种子逐局比对（bd 9j1 播种基础设施），输出数值逐位一致
- [ ] 3.4 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 4. 收尾

- [ ] 4.1 行为快照比对：切磋/决斗/历练 PvE/秘境妖兽/世界 Boss/传承挑战六条路径的战报文本与胜负结算，改造前后一致（functional_tests 相关用例或手工场景）
- [ ] 4.2 按 AGENTS.md §7 版本 checklist 评估（纯重构无玩法变化，通常无需升版本号；若有遗漏则补）
- [ ] 4.3 `openspec validate --change combat-result-winner-identity` 通过；本地 conventional commit（不 push）
