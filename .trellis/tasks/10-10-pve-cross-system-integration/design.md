# Technical Design: PVE 跨系统收口（气血地板与消费者清零）

## 1. 边界与职责

- 不重建 Health/Catalog/Persistence/Adventure 模块；**不整删旧 Boss、不做内容 sync 与激活切流**（E2）。
- 两项收口：① 气血地板统一到 Health Domain（秘境兽、传承守护者，含宗门领取入口）；② 暴击双侧接线（玩家侧物化 + 怪物侧缺省回退）。
- 范围边界：旧 Boss 即时路径（`managers/boss_manager.py` 内直接构造 `FighterState`）不接该键（E2 整删）；世界 Boss 由 D 经同一 mapper 接线。

## 2. 地板 API（单源）

```text
core/health.py
  DEFEAT_HP_FLOOR_RATIO = 0.01
  HealthService.defeat_hp_floor(player) -> int   # max(1, ceil(compute_max_hp(player) * ratio))
managers/adventure_manager.py
  _defeat_hp_floor -> 委托 health_service（保留模块级 re-export 供既有导入）
managers/pve_combat_manager.py
  challenge_rift_beast / challenge_legacy_guardian:
      won  -> engine_final
      else -> max(engine_final, health_service.defeat_hp_floor(player))
      写回 -> await health_service.set_current_hp(player, value)
```

战斗层直接落库；`rift_manager` 的 3 处 `db.update_player` 保留但不再是气血权威写点（写回值一致，整行回写仍受 AGENTS §3 约束，不宣称无竞态）；`sect_manager` 的失败分支与胜利分支都不再吞掉战斗气血。PvP 保持引擎终值 + clamp。

## 3. 暴击双侧接线

- 配置：`combat.base_crit_rate = 0.15` 同时写入 `config/game_config.json` 与 `data/default_configs.py`（两份深相等测试已存在）。
- 玩家侧：`build_fighter_from_player` 传 `crit_rate=self._base_crit_rate`（公开读取口）。
- 怪物侧：`build_enemy_fighter(enemy, base_crit_rate=0.15)`；`enemy.crit_rate > 0` → /100 覆盖，否则取该键。
- **普通 PVE 的取值点**：`PVECombatManager._build_enemy_fighter` 用 `getattr(self, "config_manager", None)` 读 `game_config["combat"].get("base_crit_rate", 0.15)`；读不到或值为 `None` → 0.15；**禁止用 `self.combat_engine`**（替身形态不可靠）。世界 Boss 不经过该类，D 自读同一键（D R4）。
- 第一季名册/世界 Boss 的 CSV 无 `crit_rate` 列 → 全部走回退，默认 0.15 行为不变；第二季 per-enemy 值对专项组模板立即可用，对固定名册需先扩 CSV 列 + builder。

## 4. 事务叶子

- 5 处按 `conn._txn_depth == 0` 才提交（与 `data/` 层同一 idiom）：spirit_farm 种植、spirit_eye 生成/释放、bounty 过期扫描、dual_cultivation 发起请求。
- 函数名定位，不写死行号；bd `-dfb` 未修前禁止新增并发叶子路径。

## 5. 验证矩阵

- 地板：历练 / 秘境应邀 / 宗门领取三入口；败场残血 ≥ `ceil(1% × 动态 max_hp)`、胜场不保底；max_hp 下降时 clamp。
- 消费者：创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示；audit 无 `Player.hp`（旧 Boss 白名单，E2 删除）。
- 暴击：改 `base_crit_rate` → 玩家 fighter 与名册/专项组 fighter 同步变化；per-enemy 有值仍覆盖；第一季 28+4 默认 0.15；`_base_crit_rate` 不再死读取；旧 export 不断。
- 事务：5 处门控后 audit 为空；并发双击不提前提交。
- 质量门：完整 pytest + 产品范围 ruff + `audit_pve_redesign.py --scope e1` 为 0。

## 6. 回滚

地板与暴击均无 schema 变更，可单提交 revert；执行前备份 DB（RP1）。宗门/秘境写回变更用定向用例钉住，失败即回退该提交。
