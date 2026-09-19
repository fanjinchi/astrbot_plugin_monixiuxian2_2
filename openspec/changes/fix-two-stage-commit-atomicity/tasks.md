> 范围：bd `astrbot_plugin_monixiuxian2_2-2w1` 的 9 例 + 用户拍板纳入的同族未登记 spot `bounty_manager.abandon_bounty`（登记为 **S10**），共 **10 例（S1-S10）**。三项 Open Question 已于 2026-09-19 全部关闭（见 design 文末），本文件不再保留“最小范围跳过”类条件分支。

> **锚点回写（任务 1.1/1.2 的产物，apply 实测行号）**：提案中的行号已整体漂移，实施按下列当前锚点执行——
> - `managers/spirit_farm_manager.py`：`create_farm`:79（CM :93）、`plant_herb`:114（裸 commit :144，Non-Goal）、`harvest`:153（CM :200）、`upgrade_farm`:249（CM :269）
> - `managers/spirit_eye_manager.py`：`spawn_spirit_eye`:45（裸 commit :66，Non-Goal）、`claim_spirit_eye`:70（原有 CM :72）、`collect_spirit_eye`:120（CM :143）、`release_spirit_eye`:161（裸 commit :174，Non-Goal）
> - `managers/blessed_land_manager.py`：`purchase_blessed_land`:72（CM :101）、`upgrade_blessed_land`:131（CM :162）、`collect_income`:182（CM :213）
> - `managers/dual_cultivation_manager.py`：`_create_request`:118（裸 commit :137，Non-Goal）、`_get_pending_request`:143（门控 :154）、`_delete_request`:177（门控 :185）、`accept_request`:243（CM :292）、`_set_last_dual_time`:340（门控 :353）
> - `core/gm_manager.py`：`cmd_clear_cooldowns`:1188 起（原有 CM）、`cmd_clear_all_cooldowns`:1204（CM :1234）
> - `managers/bounty_manager.py`：`abandon_bounty`:530（CM :549）、`check_and_expire_bounties`:649（裸 commit :656，Non-Goal）、`complete_bounty`:437（已声明设计，不动）
> - `data/database_extended.py`：`cancel_bounty`:1087（门控 :1095）、`set_system_config`:1108（门控 :1121）
> - `BEGIN` 复核：6 个实施文件内**无**手工 `BEGIN IMMEDIATE`（裸 BEGIN 仅存在于 `data/database_extended.py` 的 own_txn 回退分支），无 CM 嵌套冲突。

## 1. 锚点复核与前置确认（apply 首步，必做）

- [x] 1.1 逐 spot 复核当前 file:line 与分段边界（以 design D1 表为对照）：`grep -n "conn.commit()" managers/spirit_farm_manager.py managers/spirit_eye_manager.py managers/blessed_land_manager.py managers/dual_cultivation_manager.py core/gm_manager.py managers/bounty_manager.py`；确认与本 change 的 10 例清单（S1-S10）一一对应（不扩不缩），漂移的锚点在本文件回写为实际行号
- [x] 1.2 检查 10 处函数体内是否**没有**手工 `BEGIN IMMEDIATE`（CM 不得嵌在裸 BEGIN 块内）：`grep -n "BEGIN" <6 文件>`；有冲突则停下并在 design D1 补记
- [x] 1.3 复跑依赖的叶子门控清单（design Context 所列）确认仍然存在：`grep -rn "D2 ownership gate" data/ core/`；若某叶子门控已被删除/改写，先修正 design 再开工
- [x] 1.4 登记活跃 change 落地状态：`git log --oneline -5 -- core/gm_manager.py managers/dual_cultivation_manager.py managers/bounty_manager.py tests/test_transaction_atomicity.py`；据 design D6 判断 S8/S9/S10 是否需按新形态锚定（`busy-state-owner` 落地则步骤 1 已是 `clear(player)`；`gm-time-skip-registry` 落地则 S9 步骤 3 的 SQL 可能已迁属主模块）
- [x] 1.5 采集本 change 的失败基线：`uv run python -m pytest tests/ -q`（应为 `872 passed, 1 xfailed`），记录为验收对照

## 2. S1-S3：`managers/spirit_farm_manager.py`（灵田 3 处）

- [x] 2.1 `create_farm`（:79，裸 commit :99）：写段包 `async with self.db.transaction():`，删 :99 裸 commit；校验读（`get_user_farm`、灵石检查）留在 CM 外（实测 CM :93）
- [x] 2.2 `harvest`（:149，裸 commit :216）：包住"发奖 `update_player` + `store_item` 循环 + `UPDATE spirit_farms SET crops`"，删 :216；`store_item` 失败分支的文案逐字保留（用户已拍板 all-or-nothing，储物戒满仍在同一事务内提交，不改该分支）（实测 CM :200）
- [x] 2.3 `upgrade_farm`（:241，裸 commit :265）：包住"扣费 + 等级 UPDATE"，删 :265（实测 CM :269）
- [x] 2.4 核验：`grep -n "conn.commit()" managers/spirit_farm_manager.py` 只应剩下 `plant_herb`（实测 :144，单语句自包含，Non-Goal）；本文件其余 3 处裸 commit 归零

## 3. S4：`managers/spirit_eye_manager.py`（灵眼 1 处）

- [x] 3.1 `collect_spirit_eye`（:120，裸 commit :147）：包住"发修为 `update_player` + `UPDATE spirit_eyes SET last_collect_time`"，删 :147；冷却校验（`hours_passed < 1`）留在 CM 外（实测 CM :143）
- [x] 3.2 核验：本文件裸 commit 只剩 `spawn_spirit_eye` 与 `release_spirit_eye`（实测 :66 / :174，均为单语句自包含，Non-Goal）；`claim_spirit_eye`:70-72 已是 CM，不动

## 4. S5-S7：`managers/blessed_land_manager.py`（洞天 3 处）

- [x] 4.1 `purchase_blessed_land`（:72，裸 commit :116）：包住"扣费 + `INSERT INTO blessed_lands`"，删 :116（实测 CM :101）
- [x] 4.2 `upgrade_blessed_land`（:127，裸 commit :164）：包住"扣费 + `UPDATE blessed_lands`（level/exp_bonus/gold_per_hour）"，删 :164（实测 CM :162）
- [x] 4.3 `collect_income`（:174，裸 commit :208）：包住"发灵石/修为 + `UPDATE blessed_lands SET last_collect_time`"，删 :208；`max_exp_per_hour` 上限逻辑与文案不动（实测 CM :213）
- [x] 4.4 核验：`grep -n "conn.commit()" managers/blessed_land_manager.py` 应无命中（实测 0 命中）

## 5. S8：`managers/dual_cultivation_manager.py`（双修四叶提交）

- [x] 5.1 三个叶子补 D2 门控（照 `data/data_manager.py:322-325` 的形态，含注释）：`_get_pending_request`（实测 :143 → 门控 :154）、`_delete_request`（:177 → :185）、`_set_last_dual_time`（:340 → :353）
- [x] 5.2 `accept_request`（:237）：把"`update_player(initiator)` + `update_player(acceptor)` + `_set_last_dual_time` ×2 + `_delete_request`"整段包进一个 CM；确认无"CM 内 return"（4 处早退分支全部前置在 CM 外），故不需要 `txn.abort()`（实测 CM :292）
- [x] 5.3 核验 CM 外调用方语义不变：`send_request`（:181）与 `reject_request`（:311）在无 CM 时叶子仍独立提交（fail-open 默认 `_txn_depth == 0`）
- [x] 5.4 核验：`grep -n "conn.commit()" managers/dual_cultivation_manager.py` 只剩门控式提交（`_create_request` 实测 :137 保持原样——不在 `accept_request` 路径上、单语句自包含）

## 6. S9：`core/gm_manager.py` 清除全部冷却（GM cosmetic；已拍板纳入）

- [x] 6.1 `data/database_extended.py` 的 `cancel_bounty`（实测 :1087 → 门控 :1095）与 `set_system_config`（实测 :1108 → 门控 :1121）补 D2 门控（fail-open，形态同 `update_player`）；**必须在包 S10 之前完成**（S10 复用这两个门控）
- [x] 6.2 `cmd_clear_all_cooldowns`（实测 :1204）：步骤 1-5 的 DB 写段包进 CM（实测 :1234），删原裸 commit；步骤 2 `combat_cooldowns`、步骤 3 `dual_cultivation` 的 UPDATE 改为 CM 内执行
- [x] 6.3 步骤 6 的**内存态**历练路线休整冷却弹出（`adventure_manager._route_cooldowns.pop`）移到 CM 块退出**之后**（内存不可回滚，回滚时不得弹）
- [x] 6.4 语义核验：清除范围、`cleared` 行文案、幂等性、`没有可清除的冷却状态！` 分支逐字不变；步骤 1 若 `busy-state-owner` 已落地则包裹其 `clear(player)` 调用形态

## 7. S10：`managers/bounty_manager.py` `abandon_bounty`（同族未登记 spot；已拍板纳入）

- [x] 7.1 `abandon_bounty`（实测 :530）：写段（`cancel_bounty` 调用 + `set_system_config` 调用）包进一个 CM（实测 :549）；读与两处早退校验（`get_active_bounty`、`_scope_mismatch_message`）留在 CM 外；返回值与文案（`已放弃悬赏：…⚠️ 30分钟内无法接取新悬赏`）逐字不变
- [x] 7.2 核验：`grep -n "conn.commit()" managers/bounty_manager.py` 只剩 `check_and_expire_bounties`（实测 :649 def / :656 commit，单语句自包含，Non-Goal）；**不碰** `complete_bounty`（:437）事务内结算 + 事务外 best-effort 掉落的已声明设计
- [x] 7.3 核验 CM 外调用方：其它调用 `cancel_bounty` / `set_system_config` 的路径（`complete_bounty` 结算、GM 清除、其它域的到期键写入）在无 CM 时仍独立提交（fail-open）

## 8. 测试：`tests/test_transaction_atomicity.py` 追加 §8（append-only）

- [x] 8.1 追加 §8 章节头（说明覆盖 S1-S10 两段式/四叶提交的原子性契约，引用本 change 与 bd `-2w1`）
- [x] 8.2 S1-S7 逐 spot 三条断言：第 2 段写注入异常 → 第 1 段回滚；正常路径两段都落盘且退出后 `db.conn.in_transaction is False`；`_spy_in_transaction` 断言 CM 内每个叶子调用 `_txn_depth > 0`（S1-S7 共 14 条用例）
- [x] 8.3 S8 断言：最后一个 `_delete_request` 注入异常 → 双方修为、`dual_cultivation` 时间戳、请求行全部保持操作前状态；正常路径 = 修为已加、时间戳已写、请求已删、退出后已提交（2 条用例）
- [x] 8.4 S9 断言：步骤 3 的 `dual_cultivation` UPDATE 注入异常 → `combat_cooldowns` 状态未被清且**内存态修炼路线冷却未被弹出**；正常路径 = 全清（含 `cleared` 各行文案）、退出后由 CM 提交（2 条用例）
- [x] 8.5 S10 断言：`cancel_bounty` 之后、`set_system_config` 写入时注入异常 → `bounty_tasks` 行仍为 status 1（悬赏未被放弃）且 `bounty_abandon_cd_*` 键不存在；正常路径 = status 0 + 冷却键已写、返回值/文案逐字不变（2 条用例）
- [x] 8.6 门控叶子回归：`_set_last_dual_time`/`_delete_request`/`_get_pending_request`（及 S9/S10 的 `cancel_bounty`/`set_system_config`）在 **CM 外**独立调用仍提交（fail-open 语义不变）（2 条用例）
- [x] 8.7 跑本节测试：`uv run python -m pytest tests/test_transaction_atomicity.py -v`（50 passed）

## 9. 质量门与验收

- [x] 9.1 `uv run ruff format .`（89 files left unchanged）
- [x] 9.2 `uv run ruff check .`（All checks passed!）
- [x] 9.3 `uv run python -m pytest tests/ -v`：全绿（`894 passed, 1 xfailed` = 基线 872 + §8 新增 22），无新增 warning/失败
- [x] 9.4 裸 commit 闸门：`grep -rn "await self.db.conn.commit()" managers/ core/ | grep -v tests` 与 1.1 的快照对比——本 change 的 9 处裸 commit（S1-S7、S9 ×2）全部消失，`database_extended.py` 两个叶子改为门控式提交，剩余 8 处命中全部为既有 Non-Goal（farm `plant_herb`、eye `spawn`/`release`、dual `_create_request`、bounty `check_and_expire_bounties`），且**未引入**其它改动
- [x] 9.5 `uv run openspec validate --changes fix-two-stage-commit-atomicity` 通过（且 `--all` 基线 23 items 仍全过）

## 10. 关闭与文档同步

- [ ] 10.1 bd 关闭：`bd close astrbot_plugin_monixiuxian2_2-2w1 --reason "9 例 + 同族 S10 共 10 例 CM 收编完成，commit <hash>，测试 §8 覆盖" --json`
- [ ] 10.2 conventional commit 提交（按阶段分块，如 `fix(transaction): wrap two-stage commits of 10 spots in unit-of-work CM`），**不 push**
- [ ] 10.3 文档同步核对：本 change 不改数值/玩法 → `design_docs/` 与 `design_docs/content-design/` 无需改动；核对 AGENTS.md §3 的转换规则段落无需新增（前置 change 已写入），`git status` 干净
