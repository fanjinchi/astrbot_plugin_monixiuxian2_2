# 普通 PVE 持久结算与逃跑疲劳

## Goal

把历练遭遇从一次同步、内存疲劳的流程改为可重启恢复、幂等消费的 settlement，并落实持续气血、败场保底和高/极高风险战前一次逃跑。

## Dependencies

- 依赖玩家气血 child 的 `current_hp` / 动态 `max_hp` / transaction-friendly Health Domain。
- 依赖固定敌人目录 child 的稳定 enemy id 和完整 combat profile。
- 依赖持久化/事务基座 child 提供的 v36 settlement/effect/fatigue schema、CAS/幂等 repository、commit 纪律和 fatigue time-skip provider。
- **迁移版本授权（2026-10-12 review 决议）**：v36 的 `adventure_settlements` 只是事后事实账本，缺 `state`/`route_key`/快照列，承载不了 R1 的状态机。本 child 获准新增连续版本 **v39** 为 `adventure_settlements` 增列，但必须走 `data/migration.py` 的共享建表函数（`_create_adventure_persistence_tables`）以保持 fresh==upgrade parity，并同步 `tests/test_pve_persistence_foundation.py` 的版本矩阵断言（现 `LATEST_DB_VERSION == 38`）。不得改写 v36 已发布语义、不得复制共享表、不引入第二套 fatigue/effect 表。基座 child P 的 `design.md:13` 已预留「发现 SQLite 约束要求时拆为连续 v39…vN」。
- 权威数值/机制出处：`design_docs/content-design/pve-enemy-design.md` §5 Q4（败场惩罚与逃跑契约，:682-700）、附录 C.6（回血口径，:904-906）。逃跑概率参数封板后必须回写该文件，不得只留在代码里。
- 基座遗留的事务叶子门控技术债（bd `astrbot_plugin_monixiuxian2_2-qbo`）按「谁接入谁修」归属：`handlers/combat_handlers.py:75` 的裸 `await self.db.conn.commit()` 位于本 child 战斗结算将被 `db.transaction()` 包裹的调用图上，接线前必须先门控（与 world-boss child 共享此点，先接入方负责，后方仅确认已清零）。
- 本 child **不以正式名册 sync 为前提**（按 R3 的 legacy 身份口径落库）；名册内容的用户确认门仍属父计划 Batch 5 / child E 的激活检查点。

## Requirements

### R1. Settlement 状态机

- 所有风险档在历练开始时生成全局唯一 `adventure_run_id`，并持久化一条 settlement；该 id 同时作为完成请求、终态事实和所有下游副作用的幂等根键。
- **敌人锁定时点统一**：开始时只登记 run 与 `route_key`（现网 `managers/adventure_manager.py:233` 就只存 `route_key`）；敌人与 RNG 在**历练完成、进入结算的那一刻**锁定一次，之后迎战/逃跑/replay 一律复用该快照，不得重掷。
- 低/中风险不提供选择，但历练完成时仍先持久化已选定 enemy id/profile version、路线基础收益快照、RNG seed 和可消费状态，再运行战斗；不得走无记录的同步旁路。
- 高/极高风险在历练完成时进入 `pending_choice`，记录同样的稳定快照；**首版不设自动过期，也不新增「退出/取消历练」出口**（2026-10-12 用户拍板：无限期挂起本身就是设计，`逃跑` 就是留给玩家的后路）。
- **锁死不成立的闭环（必须照此理解，别再提出口指令）**：pending 只在高/极高风险出现，而这两档一旦出现 pending 就必然同时提供 `迎战` 与 `逃跑` 两条消费路径（逃跑默认开启，用临时默认值；人工 `enabled=false` 时则根本不产生 pending，见 R2）。因此「单据永久锁住活动」在任一时刻都不可能发生，无需期限、无需第三个出口、无需 GM 特判。
- **锁定范围是刻意的全玩法锁，不是缺陷**：忙碌拦截器（`handlers/utils.py:106-113`）对非白名单指令一律回「道友当前正在「历练中」，无法分心他顾」，挂 pending 期间修炼/采集/宗门等全部停摆。这是设计意图——战前决断必须当场做完，唯一出路就是 `迎战` 或 `逃跑`（后者即留给玩家的后路）。**禁止**为此再加超时、取消指令或 GM 特判。
- settlement 在重启后可查询；迎战/逃跑只能消费一次，并发或重试不得重复收益、重掷敌人或重复战斗。
- 非终态 settlement 保留本次历练 `ADVENTURING` busy，作用**仅是挡住「开始历练」**；终态提交时必须在同一结算边界 clear busy。busy 期间的气血恢复照常计时（见 R6），因此本 child **不需要**改写 `user_cd.scheduled_time`，也不得为此在 `BusyState` 之外手写忙碌行（AGENTS.md §2）。
- 不得复用进程内、零惩罚语义的 `EncounterStore`。

### R2. 逃跑契约

- 玩家在高/极高风险战斗前可选择迎战或尝试逃跑一次。
- 成功：不进入战斗，`current_hp` 不变；历练机会已经消耗，路线基础收益照常；不产生怪物击败事实或战败疲劳。
- 失败：使用 pending 内同一 enemy id 立即开战；不得再次逃跑或重掷。
- 成功率是玩家/敌人身法关系的单调有界函数（身法 = `FighterState.agility`，代码里 身法/迅捷 已分别对应 `agility`/`speed`，见 `managers/combat_manager.py:330`）。先以配置槽和模拟收口参数，参数写回 `design_docs/content-design/pve-enemy-design.md` §Q4 后才允许启用；禁止工程手拍常数。
- **未封板时的 fail-closed 形态**：逃跑参数未获批则**整个战前选择面保持 disabled**——高/极高风险与低/中风险一样在完成时直接进入战斗结算（等同现网行为），不创建 `pending_choice`，不出现「只能发迎战」的空转步骤。状态机与列照常存在并待命，激活与否由配置开关决定（对齐父任务「新入口保持 disabled」的既有决议）。
- **交付边界（2026-10-12 两次拍板合并口径）**：本 child **不负责封板逃跑概率**（正式数值另开三档模拟决策，bd `-9hq`），但**必须交付一组临时默认成功率**用于过渡与功能验证：`config/adventure_config.json` 新增 `flee` 段 `enabled=true / base_rate=0.35 / slope=0.20 / floor=0.10 / cap=0.70`，公式 `p = clamp(base_rate + (身法_自 / 身法_敌 − 1) × slope, floor, cap)`（身法 = `FighterState.agility`）；同一组默认值同步进 `data/default_configs.py`（AGENTS.md §5 自动建配置路径）。用户口径原话：玩家体验不需要考虑还没上线的内容，功能要先能验证。临时值必须在 §Q4 与代码注释标注「未封板」，禁止当成已定平衡。`flee.enabled=false` 保留为人工 kill switch（关闭时走 disabled 分支：不产生 `pending_choice`）。
- **导入前必须确认项（写进设计提醒）**：本 child 交付的是**临时默认**成功率（0.35/0.20/0.10/0.70，已可用、可验证）；**正式封板仍须在敌人名册/内容同步导入前完成**——名册一固定，怪物 `agility` 分布就定了，地板/标模/天花板三档模拟才有确定输入，才能替换这两个配置点的数值（bd `-9hq`）。封板前玩家已有止损键，只是数值未经模拟。此提醒同步登记 §Q4。
- **入口指令（2026-10-12 定名）**：新增两个顶层指令 `迎战` / `逃跑`，按 AGENTS.md §1 走 `main.py` 的 `CMD_ADVENTURE_FIGHT` / `CMD_ADVENTURE_FLEE` 常量 + `@filter.command(...)` 外层 / `@require_whitelist` 内层 + 路由 docstring 格式。指令名无空格、纯中文。与秘境的「迎战」不冲突——后者是 `探索秘境 迎战` 传进来的 action 参数（`main.py:1336-1346`），不是注册指令。
- 两者必须登记进 `handlers/utils.py:22` 的 `BUSY_STATE_ALLOWED_COMMANDS`，否则 pending 期间被 `@player_required` 挡死。
- **两处出路提示（2026-10-12 用户拍板甲案，非可选项）**：
  1. **主动**：高/极高风险完成历练、进入 `pending_choice` 的那条回复里，必须当场写明遭遇对象（名称/境界/风险等号）与两条出路指令（发送「迎战」立即开战 / 发送「逃跑」尝试脱离，失败仍须与同一敌人开战）。不得只回「进入待选择状态」让玩家自己猜。
  2. **被动**：玩家挂着 pending 却发别的指令时，忙碌拦截器的固定回复（`handlers/utils.py:108-113`，现文案只提「我的信息」「签到」「银行」）必须补一句「可发送「迎战」或「逃跑」结束本次历练」。实现优先用 `BusyState.assert_idle(..., template=)` 既有能力或 `@player_required` 的 status 分支，**不新增公开 API、不改 `UserStatus`**。
  理由：pending 是全玩法锁，玩家若看不见出口就等于以为号废了；提示是「锁死是设计」这条决定的可用性下限。
- 顺带清理：该清单现有 `"结束历练"`、`"结束秘境"` 匹配不到任何已注册指令（真实指令是 完成历练/完成探索/退出秘境），属死条目，删除或换成真实指令名。
- `历练状态` 必须显示待选择态（敌人快照、可执行指令提示），让玩家重启后知道该发什么。

### R3. 战斗与气血

- 玩家 Fighter 从当前 `current_hp` 和动态 `max_hp` 构建；战后只通过 Health Domain 写回 current。
- 战败后当前气血保底为 `ceil(1% * max_hp)`（2026-10-12 由 25% 下调），取和引擎剩余值中合法较高值；不再写旧绝对 `hp=1`。胜场不保底，按引擎实际剩余写回。
- Enemy→Fighter 复用目录 mapper；普通、精英和组内 Boss 的选择/结果事实带稳定 profile id/version。
- **名册未获批期间的身份口径（2026-10-12 定）**：历练敌人现仍来自 `enemy_manager.spawn_enemy(level, category)` 的旧派生（`managers/pve_combat_manager.py:331`），`config/enemies.json` 只有 3 条专项组条目，28 只固定名册仍是 draft CSV、正式 sync 由父计划 Batch 5 的用户内容门控制（child B 的 AC3 同样把正式链路复验留给 Batch 5）。因此本 child 阶段 `profile_id`/`profile_version` 允许留空/0，`encounter_id` 记 legacy 身份（敌人名称+境界+锁定 seed）；**留空不是 bug**，名册切流后由同一张表自然填上。严禁为了让字段有值而手改 `config/`（AGENTS.md §15）。
- 秘境兽/传承守护入口迁移 current HP，但不强制使用本历练 pending/逃跑流程。

### R4. 持久疲劳

- 以 `adventure_fatigue` 持久时间戳替代 `AdventureManager._route_cooldowns` 权威，**读写两端都要换**：写端 `managers/adventure_manager.py:337-344`，读端（开始历练的休整闸门）`managers/adventure_manager.py:224-229`。
- **疲劳粒度 = 每人一份全局窗口（2026-10-12 用户拍板乙案）**：沿用基座现成的单行 API（`get_fatigue(user_id)` / `cas_clear_fatigue(user_id)`，`data/pve_repository.py:444-505`），`adventure_fatigue.user_id` 主键**不动**，v39 不为疲劳表做任何重建。路线的 `fatigue_cooldown` 只决定**这次**休整多久，休整期内**任何路线都不能开**（打完九死一生 1200s，巡山问道 300s 同样被挡）。
  - 这是对旧实现「按路线独立休整」（内存 `_route_cooldowns[user][route]`）的**有意玩法收敛**：旧语义从未在设计文档成文，只有配置字段结构与玩家文案暗示它。新语义已在规划阶段写进 `design_docs/content-design/pve-enemy-design.md` §Q4（:684-693）。
  - **随之必须改玩家文案**：`managers/adventure_manager.py:229` 的「⚠️ 该路线尚在休整中，请 X 分钟后再试」与 :344 的「⏳ 该路线休整：X 分钟」不得再暗示按路线独立，改为全局表述（例：「你刚历练回来，还需休整 X 分钟」/「⏳ 历练休整：X 分钟」）。
  - 明确放弃的备选：甲案（v39 把主键重建为 `(user_id, route_id)` 保住 per-route）、丙案（保留单主键、把多路线塞进一个 JSON 列，重蹈把状态藏进字符串的老路）。若日后要恢复 per-route，属新的玩法决策，另开任务。
- **疲劳构成（2026-10-12 定，保留基础休整）**：时长 = `route.fatigue_cooldown`（现网 `config/adventure_config.json` 四条路线 = scout 300 / journey 600 / hunt 900 / peril 1200 秒，**胜负都追加**）**＋ 仅在真实战败时 +600 秒**；写入 `fatigue_until = max(现有值, now + 时长)`，不回退已生效的休整。删除现网 `event.get("injury")` 触发的 +600 分支（现网 :335，13 个路线事件里仅 `ambush_fail` 带它）——败场疲劳只由实际战斗失败产生，逃跑成功与未触发战斗不产生。
- 基础疲劳与疲劳粒度此前**都从未在 design_docs 记载**（`pve-enemy-design.md` 只提「路线疲劳 600s」，:21/:799），属 AGENTS.md §14 缺口：新口径已在规划阶段补写进 `pve-enemy-design.md` §Q4（:684-693）与父 PRD R4；实现时须核对代码与成文口径逐项一致（时长取值、+600 条件、injury 分支已删、`max` 不回退、每人一份、文案改全局）。
- 疲劳结束时间登记 GM time-skip（基座已在 `managers/adventure_manager.py:83` 的 `TIME_SKIP_ENTRIES` 声明，无需新登记）；重启后仍阻止非法重复路线。
- 玩家保存、busy 清理、pending 终态、路线基础收益与疲劳必须形成明确且可重试的结算边界，不能留下收益已发但 pending 未消费的状态。

### R5. Settlement facts 与奖励边界

- 输出 `adventure_run_id`/settlement id、enemy id/version、风险、战斗结果、current HP 差、是否逃跑、是否击败等稳定事实。
- **幂等键按基座实际写**：`adventure_effects` 的唯一键是 `(consumer_name, settlement_id, effect_type)`（`data/migration.py:214-227`、`data/pve_repository.py` 的 `claim_effect`），不是 `(adventure_run_id, effect_type)`；run→settlement 是 1:1，所以等价，但文档与实现一律用实际键，`consumer_name` 取值必须枚举。
- **消费模型（2026-10-12 定）：提交后 inline claim，不建真 outbox**。`adventure_effects` 是消费日志（只有 `claimed_at`，无 state/next_retry），而带 `queued/dispatching/sent/uncertain` + claim lease 的 v38 `business_events`/`event_deliveries` 是**群广播投递** outbox，用途不同。历练的副作用消费者全是本地函数调用、无网络订阅者，套投递队列是过度设计；正确形态是：终态事务提交成功后逐项 `claim_effect(...)`，claim 成功才执行，崩溃窗口靠「重放只读已提交状态 + claim 幂等」兜住，并用故障注入测试钉住。
- **claim 成功但执行失败的语义（2026-10-12 拍板：不重发 + 前台提示）**：inline claim 先划账、后执行；若执行阶段抛异常（例如 `_handle_drops` 写储物戒失败），**不回滚 claim、不自动重试**，结算照常进入终态。但玩家不能看到「静默丢失」：必须在本次历练结算输出里追加一条可见的中文提示（例：「⚠️ 部分奖励发放失败，请联系管理员（结算单 {settlement_id}）」），同时写 error 级日志并带 `settlement_id`/`effect_type`/异常，保证玩家有抓手、管理员能定位。理由：历练掉落不是付费权益，补偿机制的成本远高于一件物品的损失；但「什么都不说」属于可感知缺陷。
- 必须登记为 effect 的副作用（`consumer_name` 固定 `adventure_settlement`）：`base_reward`（经验/灵石）、`route_drops`（现网 `_handle_drops`，`managers/adventure_manager.py:313`）、`legacy_trigger`（现网 `_maybe_trigger_legacy`，:322，仍写内存 `EncounterStore`，本轮不改其持久化语义）。悬赏进度与师承 `adventure_complete`/`win_pve` 保持在 `main.py:1418-1460` 的结算外推进，不进本表（现状即如此，见 design §2；2026-10-12 用户确认维持）。**已知取舍**：终态事务已提交、推进尚未执行时进程崩溃 → 这一次进度丢失（重复不会发生，重复请求被终态 CAS 挡住）。后果轻微，刻意不扩 `effect_type`、不加补偿；此句即 AC5 的豁免说明，日后不得当 bug 追查。终态响应 replay 只读取已提交结果/副作用状态，不得再次直接推进。
- 保持已存在的路线基础收益；不得加入 Step 7 新掉落、材料、丹药或临时正式经济数值。

### R6. 气血恢复改为全时段计时（2026-10-12 用户拍板，本 child 交付）

- 删除 Health Domain 的忙碌闸门：`core/health.py:104-115` 的 `_is_busy()` 与 `settle()` 中 :147-152 的「busy 只前移锚点、不恢复」分支。惰性恢复只按经过时间线性回血，1% 动态 `max_hp`/分钟不变，**历练/修炼/秘境/待选择 pending 期间一律照常计时**。
- 直接后果（已知情）：① pending 等待不再需要 `scheduled_time=0` 之类的忙碌窗口改写（R1 已相应简化）；② 无限忙碌的闭关（`CULTIVATING`，`scheduled_time=0`）也不再阻断回血，长期闭关出关接近满血；③ 附录 C.6 的「连刷税 14-17%」是按仅空闲计时算的，全时段计时后实际税负更低（本轮只简化机制，不调速率；要收紧税率另开数值决策）。
- 必须同步的口径文件：父 PRD R2「仅空闲状态按每分钟 1%」→ 全时段；`design_docs/content-design/pve-enemy-design.md:813`「仅空闲计时」与附录 C.6 `:906`「历练/修炼/战斗中不走表」→ 改为全时段并注明变更；child A 归档 PRD 的 R4/AC4 由本条显式覆盖（在 C 的 design 里注明，避免下个会话按归档口径重做）。
- 测试：`tests/test_player_health_foundation.py:391-403`（`busy player never heals`）与 :406-413（过期忙碌视为空闲）随闸门删除一并反转/移除，改为断言「忙碌期间仍按分钟恢复」。

## Acceptance Criteria

- [ ] AC1：所有风险档都以唯一 `adventure_run_id` 持久化 settlement；高/极高风险 pending 可跨重启恢复，任意档完成/迎战/逃跑的并发重试只产生一个终态和一次路线收益。
- [ ] AC2：逃跑成功完整满足“无战斗、血量不变、基础收益、无击败/疲劳”；失败锁定同敌人且只战斗一次。
- [ ] AC3：概率函数在 `clamp` 上下界内对身法比单调不减、只消费稳定快照中的 `agility`；`flee` 段临时默认值已写入 `config/adventure_config.json` 与 `data/default_configs.py` 且两处一致；配置段缺失时整段回退默认 + warning 日志（不按 disabled、不向玩家报错）；人工设 `enabled=false` 时不产生 `pending_choice`。
- [ ] AC4：胜负均只经 Health Domain 写 `current_hp`；战败保底 `ceil(1% * 动态 max_hp)` 生效、旧绝对 `hp=1` 路径已移除（`managers/adventure_manager.py:306`），且**胜场不保底**（按引擎实际剩余写回，可低于 25%）。
- [ ] AC5：重启、stale resolution 恢复、GM time-skip、事务异常和终态重复请求不造成路线收益、掉落、传承、击败事实、悬赏/师承进度或疲劳重复；`effect_type` 三个取值各有 claim 冲突测试；claim 划账后执行失败时结算仍进终态、玩家看到「部分奖励发放失败」提示且 error 日志可定位（不回滚 claim、不自动重发）。
- [ ] AC6：普通/精英/组内 Boss 回归与设计 TTK/胜率/资源税口径一致；秘境兽/守护者 current HP 回归通过。
- [ ] AC7：无 Step 7 新经济数值；定向及完整 ruff/pytest 质量门通过。
- [ ] AC8：疲劳构成为「路线 `fatigue_cooldown` 300/600/900/1200 恒定 + 仅真实战败 +600，写入取 `max` 不回退」，injury 分支已移除；休整闸门读端已切 `adventure_fatigue`（**每人一份全局窗口，休整期内任何路线都不能开**，基座表与单行 API 不改），重启后仍生效，GM time-skip 能跳过；两处「该路线」玩家文案已改为全局表述并有测试/输出证据。
- [ ] AC9：`迎战`/`逃跑` 已注册并进入 `BUSY_STATE_ALLOWED_COMMANDS`（死条目已清理），`历练状态` 能显示待选择态；`/修仙帮助`、`metadata.yaml` version、README 日志按 AGENTS.md §7 同步。
- [ ] AC10：气血恢复不再判断忙碌（`_is_busy` 已删除），历练/闭关/pending 期间按 1% 动态 `max_hp`/分钟持续恢复；父 PRD R2、`pve-enemy-design.md` §Q4 与附录 C.6 口径已同步。
- [ ] AC11：pending 的出路提示两处齐备——进入 `pending_choice` 的结算回复含遭遇对象 + 「迎战/逃跑」两条指令；挂 pending 时发任意非白名单指令，回复文案出现「迎战」「逃跑」出路提示。其它忙碌状态（修炼/闭关等）的拦截文案逐字不变。

## Decisions (2026-10-12 用户拍板)

- 路线基础疲劳**保留**（不砍成仅败场税）。
- 战前选择指令定名 `迎战` / `逃跑`。
- 惰性气血恢复**取消忙碌判断**，改全时段计时（→ R6）；连带 pending 不需要改写忙碌到期时间。
- v39 增列承载状态机、inline claim 消费、profile 留空的 legacy 身份口径：按本 PRD/design 推荐落地。
- 疲劳粒度取**乙案**：每人一份全局休整窗口（见 R4），不重建 `adventure_fatigue` 主键、不改基座仓储签名。
- pending **不设自动过期、不加取消指令**：全玩法锁是设计意图，`迎战`/`逃跑` 即全部出口（→ R1）。
- 逃跑参数**先给临时默认值过渡**（`enabled=true`，0.35 / 0.20 / 0.10 / 0.70）以便跑通功能与用例；正式封板另开模拟（bd `-9hq`），**玩家体验不考虑尚未上线的内容**（2026-10-12 用户拍板，取代此前「不留默认值、以 disabled 起步」口径）。
- claim 划账后执行失败：不重发、不回滚，但**前台必须有玩家可见提示** + error 日志（→ R5）。
- 败场气血地板由 25% 改为 **1%**（`ceil(1% * 动态 max_hp)`），**胜场不保底**（→ R3）。
- 悬赏/师承继续留在结算外推进，崩溃窗口允许丢一次（→ R5）。

## Resolved Open Question

- ~~疲劳主键甲/乙案~~ → **已决乙案（2026-10-12）**：全局一份疲劳，作为有意的玩法收敛并成文进 `design_docs`。
- ~~pending 是否需要超时/取消出口~~ → **已决：不要**（2026-10-12）：全玩法锁即设计，逃跑是后路。
- ~~1% 地板是否只适用于历练~~ → **已决（2026-10-12）：Q4 地板全局统一 1%**，历练与世界 Boss 同口径；child D 与 `pve-enemy-design.md` :43/:552 的 25% 已同步改写，bd `-7ud` 关闭。
- 剩余外部前提：逃跑**正式封板**（bd `-9hq`，须在名册/内容导入前完成）。本 child 交付临时默认值（过渡 + 验证用），封板后只改配置里的系数，代码与状态机不动。

## Out of Scope

- 世界 Boss 生命周期。
- Step 7 正式奖励。
- 守护者独立胜率重标。
- **秘境兽/传承守护者的气血地板与结算收口**（2026-10-12 用户拍板甲案）：由 child E 的「PVE 气血地板收口」步骤负责，本 child 不动 `managers/pve_combat_manager.py:416/:469`；过渡期允许「历练有 1% 地板、秘境/守护者裸写引擎终值」并存。
