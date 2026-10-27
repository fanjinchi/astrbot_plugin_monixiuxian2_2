# Design — 逃跑契约重拍落地

对应 PRD：`prd.md`（bd `-w07`）。设计权威：`design_docs/content-design/pve-enemy-design.md` §Q4（2026-10-19 重拍 + 2026-10-20 追记）。

本版已并入 2026-10-20 两轮子代理审查（技术事实 + 测试影响面）与主代理实锤复核的全部结论。

## 1. 改动总览（全部在 `managers/adventure_manager.py`，无 schema/配置数值变更）

| # | 位置（现状行号） | 改动 |
|---|---|---|
| D1 | `_offers_choice`（:1568-1580）+ `HIGH_RISK_LEVELS`（:139） | 去闸门：凡遇敌（snapshot 含 combat）且 `flee.enabled` 即给选择；删除 `HIGH_RISK_LEVELS` 常量（全仓库无其它消费方，已核） |
| D2 | `resolve_adventure_choice` fled 分支（:630）+ `_replay_terminal` fled 分支（:1391） | 新增 `_fled_rewards(snapshot)` helper：base_reward ×0.3 int 截断，两处共用（已核：全仓库仅此两处算 fled 收益） |
| D3 | `_grant_route_drops`（:1311）/ `_grant_legacy_trigger`（:1334） | 按终态门控：fled 不掉落；legacy 仅 `resolved_win` 执行 |
| D4 | `_render_pending`（:1433）+ fled `combat_msg`（:629）+ `handlers/adventure_handlers.py:32` + `handlers/misc_handler.py:144` | 4 处文案写清逃跑代价 / 全段口径（§4 草案） |
| D5 | `DEFAULT_FLEE_PARAMS` 注释（:127-129）、`:325/:334` 日志警告、「临时默认系数」表述、`data/default_configs.py:596-597` 注释 | 「临时默认/未封板」→ 封板口径（bd `-9hq` 零改动收口）；只动注释与日志文本，不动数值 |

## 2. 关键决策

### D3 的效果门控形态：claim 照记、本体跳过（不改成状态相关效果集）

**决定**：`SETTLEMENT_EFFECTS` 三件套与 `_effects_complete`（:564）不变。fled/loss 终态仍然 claim 全部三个效果，只是本体按终态跳过（返回空串）——沿用 `_grant_route_drops` 对 `hp_penalty` 的既有先例（「什么都不掉，但这次机会同样被 claim 消耗掉，重放不会补发」，:1316-1318）。

**理由**：`_effects_complete` 是「终态行是否还有欠账」的补发闸门（:551），改成状态相关效果集要动 claim 表语义与重放路径，只为少写两行 claim 记录，不值。已核：claim 表（adventure_effects）的消费方只有 `data/pve_repository.py:555/568` 与 `_effects_complete`，无 GM/渲染/审计读它，「claim 了但没发效果」对其它路径不可见。claim 照记还天然兼容过渡期的旧终态行：重放时已有 claim 的效果不会重发，未 claim 的按新契约跳过。

**实现**：`_grant_effects` 手里有 `row["state"]`，构造 effects 元组时把 state 传给两个本体（或在 lambda 闭包内判定）：
- `_grant_route_drops`：`if rewards.get("hp_penalty") or state == resolved_fled: return "", []`
- `_grant_legacy_trigger`：`if state != resolved_win: return ""`（连 roll 都不做，省一次子流派生）。

**接受的过渡行为**：改动前提交、崩溃在效果补发中途的旧 fled/loss 单，重放时按新契约不再补掉落/传承。窗口极小、影响可忽略，不迁移历史 claim。

### D2 的取整与系数出处

- `FLED_REWARD_RATIO = 0.3`（模块常量，注释引 §Q4「白跑大半趟」与附录 B 总账「后路溢价」行）。
- `int(base * 0.3)` 截断，对标败场修为取整先例（`managers/pve_combat_manager.py:272`）。
- **口径差注意**：败场只有修为 ×0.3，灵石直接归零（`:273`）；逃跑是修为/灵石都 ×0.3，比败场宽——§Q4「逃跑严格落在胜负之间」的原意，文案与验收不得写成「与败场完全同口径」。
- fled 不含 `bonus_exp`：快照 `base_reward` 只含 exp/gold（`_calculate_rewards` :1799-1816），bonus_exp 仅战胜 outcome 产生（`pve_combat_manager.py:281`），维持现状。

### D1 的触发判定（combat 存在性判定是承重的）

`_offers_choice(snapshot)` 新体：先查 `flee.enabled`（kill switch 不变），再查 `snapshot.get("combat")` 是否存在。**第二项不是保险是承重**：`_lock_encounter`（:720-806）对每个完成的 run 都调 `_offers_choice`，未遇敌 run 的 snapshot 没有 combat——未遇敌直通 `resolved_win` 全靠这个判定。删掉它，未遇敌完成也会挂 pending，契约直接崩。docstring 必须写明这一点。

## 3. 不变式守护（child C 骨架不动）

- 终态 CAS、`rng_seed` 派生子流、事务外确定性计算、claim 恰好一次——全部沿用，本任务不改这些机制。
- 逃跑判定子流（`_seed_stream(seed, "flee")`）不受影响：fled 分支仍在 `_finalize` 前判定，只是 rewards 数值与效果门控变了。
- `_finalize` 的疲劳写入：fled 不加 +600s 是现行行为（:1100 注释），不动。
- 已核无需动的：「迎战/逃跑」已在 `BUSY_STATE_ALLOWED_COMMANDS`（`handlers/utils.py:71-72`），忙碌拒绝出路提示在 `core/busy_state.py:68`；GM 代打走 `resolve_adventure_choice(flee=False)`（`gm_manager.py:1175`），无自拼 fled 文案；「历练状态」复用 `_render_pending`（`check_adventure_status` :1665），改一处全覆盖。

## 4. 文案草案（R4，随 PRD 审；共 4 处）

**① pending 提示**（`_render_pending` 逃跑条目改为）：

```
· 发送「逃跑」尝试脱离，成算约 {chance}%（脱身后这趟白跑大半：收益只留三成，无掉落、无传承机缘）
```

**② 逃跑成功结算**（fled 分支 `combat_msg` 改为，仅 :629 一处）：

```
💨 你趁乱抽身，遁走了——这一趟白跑大半：收益只留三成，无掉落、无传承机缘。
```

收益行照常显示 ×0.3 后的实际数值，无需额外说明。其余文案（迎战条目、锁定提示、拒绝文案出路提示）不变。

**③ 历练信息**（`handlers/adventure_handlers.py:32`）：「/迎战 或 /逃跑 → 强敌拦路时的两个出口（仅高、极高风险路线）」→ 去掉风险段限定，如「→ 遇敌时的两个出口（逃跑收益只留三成）」。

**④ 修仙帮助**（`handlers/misc_handler.py:144`）：「迎战 / 逃跑 → 高、极高风险遇劲敌时的两个出口（未抉择不结算）」→ 同步全段口径。

## 5. functional_tests sect 域适配（R6 / AC6，3 条用例）

**会翻车的用例（实扫全量，共 3 条）**：`sect-bounty-lifecycle.json`（4 循环）、`sect-adventure-event-marker.json`（3 循环）、`sect-master-chain-gm.json`（1 次），均走「开始历练 巡山 → GM 触发历练结算」。不翻车的（已逐条核过）：`gm-time-tools.json`（只开始不结算）、`pve-smoke.json`（只入口）、`sect-master-task-chain.json`（无历练步骤）、`pvp/legacy-basic.json`（传承 PK 域）。

**GM 侧事实（已核）**：`cmd_force_adventure`（`core/gm_manager.py:1071`）走 `finish_adventure` 正常管线，无强制直通；遇敌挂 pending 时被 :1123 兜底拦下，回 `❌ 历练已推进到战前抉择，未能不战而结！💡 代玩家应战请发送「强制历练迎战 …」`，且**不执行 clear_fatigue**（:1134 只在成功路径上）。现成的 `强制历练迎战`（:1140-1185）= 代打 + `clear_fatigue` + 悬赏/师承进度推进一体；未遇敌分支回 `❌ 目标玩家当前没有等待应战的历练遭遇！`。

**否决方案一：GM 随机种子钉死「未遇敌」**——遇敌掷骰在全局流里的消费位置随循环次数漂移，选种子是经验活且脆。

**否决方案二：插玩家「迎战」步骤（休整洞，审查实锤）**——pending 分支 GM 结算失败返回、不清疲劳；玩家迎战落终态写入路线休整（巡山 300s，败场再 +600），bounty/event-marker 用例下一轮「开始历练」被「⚠️ 你刚历练回来，还需休整」拦死（`start_adventure` :398-403）。

**采用方案：每个「GM 触发历练结算」步骤后插一步 GM「强制历练迎战」，双分支断言**：
- 「GM 触发历练结算」步 match 放宽为 `已强制结算|未能不战而结`（未遇敌→前者且进度入账；遇敌→后者兜底文案）；
- 插入的「强制历练迎战」步 match 容纳双分支：未遇敌 → `没有等待应战的历练遭遇`；遇敌 → `已代【…】应战并结算历练`（其内联战报含 🚶 历练归来/💥 历练受挫两头，正则两头都要容，不依赖必胜）；
- 进度收敛：每循环进度恰好推进一次（未遇敌由结算步、遇敌由迎战步，三态 adventure_complete 都照常推进，契约口径）；终局断言（悬赏完成/师承解锁/事件标记计数）不变。
- **master-chain 特例**：「师承任务【采药历练】完成！」断言当前内联在 GM 结算步的回复里，双分支后它只出现在其中一条回复——按平台「每个 send 只配一个断言」约束，把该断言**移位**到收敛点（加一步 `#宗门 师承` 面板查询断【破境之礼】解锁）。
- 确定性框架修正：bounty 与 event-marker 是 deterministic+seed 42（每 send 重置种子），遇敌分支是**确定性的全遇或全不遇**，不是概率 76%；master-chain 才是真随机 30%。结论不变（双分支两种都活），但措辞与调试预期按此。
- fixture 强度背书：900000002 = 练气三阶（level_index=2），巡山普通怪对同级标模胜率 100%（附录 D.5，3000 场 0 败）；即便败场 adventure_complete 进度也照常推进，收敛不依赖胜负。

## 6. pytest 改写清单（R6 / AC5，实扫定稿：共 16 条翻红）

**结构事实**：测试 harness `build_env` 默认 `_should_trigger_combat = lambda: True`（`tests/test_adventure_settlement_state_machine.py:374`，遭遇必触发），所以全段 pending 后**所有用 LOW_ROUTE 且 finish 的用例**都停在 `pending_choice`。逐条修法二选一：(a) 像 `test_low_risk_finish_settles_win_without_pending`（:511）那样显式关触发、保持「未遇敌直通」原意；(b) 补一步 `resolve_adventure_choice` 落终态后断言。逐条选择以实现时最贴近原测试意图为准。

**状态机文件 15 条**：

| 用例 | 旧前提 | 修法方向 |
|---|---|---|
| `test_start_creates_adventuring_row_with_unique_run_id` (:488) | LOW finish 后 clear_fatigue 为真、可再开 | (a) 关触发（测的是 run id 唯一性，与遇敌无关） |
| `test_finish_backfills_missing_run_row` (:537) | LOW 直通 resolved_win | (a) 或 (b) |
| `test_flee_success_records_fled_without_hp_loss` (:666/:684) | fled 全额 BASE_EXP | 改断 int(1000×0.3)=300 + 无掉落/传承；docstring 同步（现存唯一钉 fled 全额的断言） |
| `test_drops_follow_victory_and_are_skipped_on_defeat` (:879) 前半 | LOW 完成掉落 1 次 | (a) 或 (b) 落终态；后半 HIGH 败场不掉落断言新契约下仍成立 |
| `test_injury_event_no_longer_damages_player` (:897) | LOW 直通战斗看 hp | (a) 或先迎战再断言 |
| `test_defeat_adds_extra_fatigue_only_on_loss` (:909) 前半 | LOW 完成即写基础疲劳 | (a) 走未遇敌路径 |
| `test_global_fatigue_blocks_cross_route` (:925) | LOW 完成后疲劳拦人 | 先落终态（忙碌检查先于疲劳检查，文案前提已变） |
| `test_concurrent_finish_cas_is_exactly_two` (:1101) | 低风险 _offers_choice=False | 前提失效，重写（docstring 自述依赖旧闸门） |
| `test_crash_after_commit_before_claim_backfills_once` (:1151) | LOW 终态+补发 | (b) 落终态后保持原流程 |
| `test_effect_failure_is_visible_and_not_retried` (:1233) | LOW 结算执行效果 | (b) 同上 |
| `test_legacy_effect_fires_exactly_once_per_settlement` (:1257) | LOW 完成滚传承 | (a) 未遇敌完成仍属 resolved_win，传承照滚、原意保留 |
| `test_time_skip_clears_fatigue_gate` (:1287) | LOW 完成后快进再开 | 先落终态 |
| `test_legacy_in_flight_concurrent_finish_creates_single_fact` (:1495) | LOW 在途补建直通 | (b) 补建后同样停 pending |
| `test_revived_busy_self_heals_on_replay` (:1538) | LOW finish 有 reward_data | (a) 或 (b)（**上一版误列为「不动」，实锤必红**） |
| `test_replay_reissued_drops_survive_the_self_heal_write` (:1605) | LOW 完成掉落入戒 | (b) |

**跨文件 1 条**：`tests/test_sect_content_link.py::test_adventure_settlement_marks_sect_event`（:482-528）——真 AdventureManager + 真配置 + 真随机（巡山 30% 遇敌、不 stub），2 次 finish ≈ 51% 概率红。修法：monkeypatch `_should_trigger_combat` 为 False（用例只关心事件文案前缀，与遇敌无关）。

**反向盘点结论（实扫）**：现存**没有**任何用例钉「fled 照常滚掉落/传承」或「loss 照常滚传承」（harness 默认 item_chance=0、legacy_chance=0）——无需改旧断言，只需新补反向用例：fled ×0.3 精确值、fled/loss 三 claim 全记录但掉落/传承本体未执行（储物戒与传承表无变化）、win 传承不变、`flee.enabled=false` 全段直通（现有 `test_kill_switch_skips_pending_entirely` 只覆盖 HIGH，补 LOW 段）、低/中风险遇敌挂 pending 正向用例。

**命名卫生（建议级）**：`test_low_risk_finish_settles_win_without_pending`（:511）因显式关触发仍绿，但用例名/docstring「低风险不停在抉择」语义已过时，改名/改 docstring 为「未遇敌直通」口径。

**确认不受影响的**：`test_rift_adventure_narrative.py`（直调 `_maybe_trigger_legacy`，不经新门控）；`test_gm_manager.py`（mock adventure_manager）；`test_feature_switches.py:221`（只开始不结算）。

## 7. 回滚

单提交可整体 revert。无 DB 迁移、无 config 数值变更；行为回滚 = 回到首版契约，无数据残留问题（claim 表语义未变）。
