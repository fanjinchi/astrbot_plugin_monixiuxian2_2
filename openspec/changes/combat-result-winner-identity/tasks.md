# Tasks — combat-result-winner-identity

## 0. 前置检查

- [ ] 0.1 重新锚定行号：确认 `busy-state-owner` / `add-transaction-unit-of-work` 未改动 `managers/combat_manager.py` 结算段与 `pve_combat_manager.py` 的消费者行；另核对 `narrative-contract-module` 对 `tests/test_combat_report_structure.py` 的注释级编辑（其 tasks 3.5，文件头部 :31 附近）是否已合入——若已合入，tasks 3.1 中该文件的断言行号（:177,:195,:219）需按当时代码更新；有变动则按当时代码更新本文件全部行号引用
- [ ] 0.2 全仓 grep 基线：`result.winner`（属性读取）与 `"winner"` / `.get("winner"`（dict 键读取，覆盖 `main.py:1126` 这类非属性消费点）/ `startswith("enemy_")` / `isinstance(winner` 的消费者清单与 design.md Context 枚举一致

## 1. 引擎接口重构（combat_manager.py）

- [ ] 1.1 `managers/combat_manager.py:168-177` `CombatResult`：删 `winner: str`，新增 `winner_side: Literal["fighter1", "fighter2", "draw"]` 与 `winner_id: str | None`（docstring 注明：平局时 `winner_side == "draw"` 且 `winner_id is None`；id 仅为便捷查询，身份编码语义由引擎内部消化）；同步更新 `resolve_combat` Returns docstring（:275，现文 "CombatResult with winner, log, and final HP values" 引用被删字段，按 AGENTS.md docstring 约定改为 `winner_side`/`winner_id` 表述）
- [ ] 1.2 `resolve_combat` 结算分支（:341-363）：五个分支逐一代换——`fighter1.hp <= 0 and fighter2.hp <= 0` / `total_actions >= action_limit` / `else` 三个平局分支 → `winner_side = "draw"; winner_id = None`；`winner = fighter2.user_id` → `winner_side = "fighter2"; winner_id = fighter2.user_id`；`fighter1.hp <= 0` 胜利分支（fighter1 胜）同理；banner/flavor 逻辑一行不动；`CombatResult(...)` 构造（:370-377）同步改字段名
- [ ] 1.3 `CombatManager.player_vs_player` legacy dict（:1518）：`"winner": result.winner` → `"winner": result.winner_id or "draw"`（值域不变，runtime 无消费者，测试断言原样通过）

## 2. 运行时调用点改查询/显式比较

- [ ] 2.1 `managers/pve_combat_manager.py`（helper 保持接收 legacy dict，设计 D6；**不**穿 CombatResult）：
  - `_calculate_rewards`（:234-248）：删 `isinstance(winner, str) and winner.startswith("enemy_")`，改显式相等比较——`is_enemy_winner = winner == enemy.user_id`、`is_draw = winner == "draw"`（`enemy` 已是该 helper 实参 :206，`enemy.user_id` 存在 :196；dict 形态与 `"winner"` 值域不变，胜利=玩家 id / 失败=敌人 id（`enemy_`/`guardian_` 前缀）/ 平局=`"draw"`）
  - `_format_combat_result`（:273-275）：同上改写
  - `trigger_pve_combat` legacy dict（:357）：`"winner": result.winner_id or "draw"`（下游 `_calculate_rewards`/`_format_combat_result` 接收的 dict 值域保持不变）
  - `challenge_rift_beast`（:412-413）：`won = result.winner_id == player.user_id` 语义不变（design D2 显式比较），`is_draw = result.winner_side == "draw"`；**核对 fighter1 归属为玩家**；`:409-411` 的补丁注释更新为「接口已结构化，前缀判定不可复活」类简述
  - `challenge_legacy_guardian`（:467-468）：同上
- [ ] 2.2 `managers/boss_manager.py:427-520`：`winner = result.winner` → 结构化读取；`:438` `winner == user_id` → `result.winner_id == user_id`；`:480` `if winner == "draw"` → `result.winner_side == "draw"`；`:513` legacy dict `"winner"` 值 = `result.winner_id or "draw"`；**核对 fighter1 归属**（玩家侧）并据此选 side 或 id 比较。**注意运行时消费者 `main.py:1126`**（`battle_result.get("winner") == user_id`，击败广播门槛）：本任务不动它，值域不变故等值比较语义逐位保持（design D4）
- [ ] 2.3 `managers/impart_pk_manager.py:115-119`：`result.winner == "draw"` → `result.winner_side == "draw"`；`attacker_wins = result.winner == attacker.user_id` → `result.winner_id == attacker.user_id`；**核对 attacker 对应 fighter1**（engine 调用处 :107 的实参顺序）
- [ ] 2.4 收尾 grep：运行时代码（main.py、handlers/、managers/、core/）`startswith("enemy_")`、`isinstance(winner` 零命中；`result.winner`（裸属性）零命中；`"winner"` / `.get("winner"` 仅命中刻意保留的 legacy dict 键（`combat_manager.py:1518`、`pve_combat_manager.py:357`、`boss_manager.py:513` 赋值侧 + `main.py:1126` 消费侧 + 测试 fake/dict 用例），逐处确认属预期

## 3. 测试与 design_docs 脚本同步

- [ ] 3.1 测试更新（构造 `CombatResult(winner=...)` → `winner_side=/winner_id=`；断言 `result.winner` → `result.winner_side`/`winner_id`）：`tests/test_combat_engine.py`（:456,:503,:515,:546 等多处）、`tests/test_combat_report_structure.py`（:177,:195,:219）、`tests/test_trigger_effect_extensions.py`（:358-382,:704,:739）、`tests/test_rift_encounters.py`（:485-493 桩与 :499,:517,:530 用例）、`tests/test_boss.py`（:91,:359,:401,:443）、`tests/test_pve_combat.py`（仅 :68,:470 两个 `CombatResult` 桩）；注意 **`CombatResult` 桩的** `winner="draw"` 构造点改 `winner_side="draw", winner_id=None`。**无需改动**：`test_pve_combat.py` 的裸 dict 用例（:340-399、:517-552，含 :380、:545——dict 接口按 D6 保留，喂 `_calculate_rewards`/`_format_combat_result` 的 `{"winner": ...}` 原样有效）与 `tests/test_combat_handlers.py:45`（fake `player_vs_player` legacy dict，`"winner"` 键按 D4 保留）
- [ ] 3.2 `design_docs/attribute-growth/` 脚本胜负读取改 `winner_side`：`sim_route_matchup.py`（:154-160,:413-419——:388 镜像格循环只读 `result.rounds`，不在范围内）、`sweep_route_growth.py`（:124-129）、`sim_balance_regression.py`(:317)、`sim_xiuxian_turns.py`(:275)；按各脚本 fighter1 归属选 `"fighter1"/"fighter2"` 比较（脚本里 `== "体修"` 按名字判定的点改按侧判定，站位以脚本内 FighterState 构建为准）；`rebalance_equipment.py` 不读 winner，**不在范围内**
- [ ] 3.3 校准复现验证：改造前后对 `sim_route_matchup.py` 跑同种子逐局比对（bd 9j1 播种基础设施），输出数值逐位一致
- [ ] 3.4 `uv run python -m pytest tests/ -v` 全绿；`uv run ruff format . && uv run ruff check .` 通过

## 4. 收尾

- [ ] 4.1 行为快照比对：切磋/决斗/历练 PvE/秘境妖兽/世界 Boss/传承挑战六条路径的战报文本与胜负结算，改造前后一致。按 AGENTS.md 2026-08-30 约定，真实环境 webtest 用例由用户发起——本条默认以手工场景/文本快照自验，若需 functional_tests 平台回归由用户指示后执行，实施者不得卡在 `WEBTEST_URL`/`WEBTEST_TOKEN` 环境变量上
- [ ] 4.2 按 AGENTS.md §7 版本 checklist 评估（纯重构无玩法变化，通常无需升版本号；若有遗漏则补）
- [ ] 4.3 `openspec validate --change combat-result-winner-identity` 通过；本地 conventional commit（不 push）
