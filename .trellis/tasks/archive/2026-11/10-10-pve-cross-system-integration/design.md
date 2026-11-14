# Technical Design: PVE 跨系统收口（气血地板与消费者清零）

## 1. 边界与职责

- 不重建 Health/Catalog/Persistence/Adventure 模块；**不整删旧 Boss、不做内容 sync 与激活切流**（E2）。
- 三项收口：① dfb 事务归属竞态与全局同类独立叶子写；② 气血地板统一到 Health Domain（秘境兽、传承守护者，含宗门领取入口）；③ 暴击双侧接线（玩家侧物化 + 怪物侧缺省回退）。
- 范围边界：旧 Boss 即时路径（`managers/boss_manager.py` 内直接构造 `FighterState`）不接该键（E2 整删）；世界 Boss 由 D 经同一 mapper 接线。

## 2. 地板 API（单源）

```text
core/health.py
  DEFEAT_HP_FLOOR_RATIO = 0.01
  HealthService.defeat_hp_floor(player) -> int   # max(1, ceil(compute_max_hp(player) * ratio))
managers/adventure_manager.py
  _compute_locked:
      loss/draw -> max(engine_final, health_service.defeat_hp_floor(player))
      loss      -> resolved_loss；draw 保持 resolved_win 与基础收益
      仅保留 DEFEAT_HP_FLOOR_RATIO 模块级 re-export，无本地 helper/公式
managers/pve_combat_manager.py
  challenge_rift_beast / challenge_legacy_guardian:
      won  -> engine_final
      else -> max(engine_final, health_service.defeat_hp_floor(player))
      写回 -> await health_service.set_current_hp(player, value)
```

战斗层直接落库；`rift_manager` 的 3 处 `db.update_player` 保留但不再是气血权威写点（写回值一致，整行回写仍受 AGENTS §3 约束，不宣称无竞态）；`sect_manager` 的失败分支与胜利分支都不再吞掉战斗气血。PvP 保持引擎终值 + clamp。

## 3. 暴击双侧接线

- 配置：`combat.base_crit_rate = 0.15` 同时写入 `config/game_config.json` 与 `data/default_configs.py`（两份深相等测试已存在）。
- 玩家侧：`CombatEngine` 构造边界把 missing/None 归一为 0.15、保留显式 0；`build_fighter_from_player` 传 `crit_rate=self._base_crit_rate`（公开读取口）。
- 怪物侧：`build_enemy_fighter(enemy, base_crit_rate=0.15)`；`enemy.crit_rate > 0` → /100 覆盖，否则取该键。
- **普通 PVE 的取值点**：`PVECombatManager._build_enemy_fighter` 用 `getattr(self, "config_manager", None)` 读 `game_config["combat"].get("base_crit_rate", 0.15)`；读不到或值为 `None` → 0.15；**禁止用 `self.combat_engine`**（替身形态不可靠）。世界 Boss 不经过该类，D 自读同一键（D R4）。
- 第一季名册/世界 Boss 的 CSV 无 `crit_rate` 列 → 全部走回退，默认 0.15 行为不变；第二季 per-enemy 值对专项组模板立即可用，对固定名册需先扩 CSV 列 + builder。

## 4. 事务归属与独立叶子写（dfb，2026-11-09 定案）

### 4.1 所有权契约

- 新增连接级、可重入的 `leaf_write(conn, *, immediate=False)` 共享上下文（放在独立 data 层模块，避免 `data_manager` ↔ `database_extended` 循环依赖）；`DataBase.connect()` 把 CM 使用的 condition 绑定到 conn，裸连接首次使用时允许初始化同一组所有权字段。
- standalone 叶子在**首条 DML / 自有 BEGIN 之前**取得与 CM 相同的 owner：同任务递增 depth、passive join；跨任务在共享 condition 上等待。owner 正常退出 commit，异常退出 rollback，最终复位 depth/owner/state 并 notify；joined 退出只递减 depth。
- 默认 `immediate=False` 保留 sqlite 首条 DML 隐式 BEGIN 与 raw-hand-BEGIN 兼容；确有读改写原子要求的既有 `own_txn + BEGIN IMMEDIATE` 叶子用 `immediate=True`。取消/ BEGIN 失败走与 CM 相同的补偿释放，不得强制 flush 其他任务的事务。
- 叶子公开方法把整个写操作包进该上下文，删除原“execute 后按 depth 决定 commit”与 `own_txn` 裸事务块；处于外层 CM 时自然 join，standalone 时自然提交。返回结构、SQL 字段与业务校验不变。

### 4.2 覆盖与证据

- 覆盖 `data/` 三个写模块、`core/health.py`、`handlers/combat_handlers.py` 及 managers 层全部现有同类写点，不只修 E1 原列的五处。
- 用真实 SQLite 做事件控制的确定性 interleaving：叶子的隐式事务已开启但未提交时，另一任务尝试 CM；修复前 red（BEGIN 冲突/隐式事务悬空），修复后 CM 等待、叶子提交、CM 随后 BEGIN/COMMIT。另钉反向等待、同任务 join 回滚、裸连接/raw BEGIN 兼容、异常与取消释放。
- 更新既有事务 AST/audit：禁止写后才决定归属的门控与叶子自有裸 BEGIN；保留 raw SQL 架构约束的既有范围，不把脚本/迁移机械改写纳入本项。

## 5. 验证矩阵

- 地板：历练 / 秘境应邀 / 宗门领取三入口；败/平均为 `max(引擎终值, HealthService 动态地板)`，历练平局仍保持 resolved_win/基础收益，胜场不保底；max_hp 下降时 clamp。
- 消费者：创角/突破/装备/功法/丹药/商店/GM/PvP/历练/秘境/传承/显示；audit 无 `Player.hp`（旧 Boss 白名单，E2 删除）。
- 暴击：玩家 missing/None/0/自定义值与怪物 0/None/自定义值均走同一配置口径，真实 resolve_combat 可运行；改 `base_crit_rate` → 玩家 fighter 与名册/专项组 fighter 同步变化；per-enemy 有值仍覆盖；第一季 28+4 默认 0.15；`_base_crit_rate` 不再死读取；旧 export 不断。
- 事务：dfb 确定性红绿回归；全局同类叶子首写前归属、跨任务互斥、同任务 join、异常/取消释放；原并发双击与既有 standalone/raw BEGIN 兼容用例保持绿。
- 质量门：完整 pytest + 产品范围 ruff + `audit_pve_redesign.py --scope e1` 为 0。

## 6. 回滚

地板与暴击均无 schema 变更，可单提交 revert；执行前备份 DB（RP1）。事务归属先用定向 red 钉住，若全局迁移暴露兼容问题，回退到上一个绿色检查点，不以 BEGIN 前强制提交作为规避。宗门/秘境写回变更用定向用例钉住，失败即回退该提交。
