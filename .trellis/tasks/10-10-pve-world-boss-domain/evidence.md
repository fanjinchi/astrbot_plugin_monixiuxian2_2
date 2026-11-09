# Completion Evidence — child D 世界 Boss 生命周期与原子挑战（2026-11-09）

范围声明：本 child 只交付领域服务 + 事件 dispatcher + 测试 + AC9 验收门。**未注册 poller、未切 handler、未删旧 Boss 实现、未启用固定名册**（切流与旧实现整删归 E2）；**不新增 migration 版本**（消费 P 已冻结的 v37/v38）；**未改任何 config/CSV 内容、未做版本号更新**（版本清单归 E1/E2）。

## 1. Schema / catalog 契约扩展（R7 输入端）

- core/enemy_schema.py：
  - 新增常量 WB_NARRATIVE_TEXT_COLUMNS = ("spawn_text","phase2_text","phase3_text","kill_text","dissipate_text")；
  - build_world_boss_profile 产出五文案（strip，缺列记空串）+ narrative_approved（经 _to_wb_approval：缺省 False，接受 true/1/yes 与 false/0/no，其余值记错误）；approved=True 但文案空 → 记错误（fail closed）；
  - _WB_PROFILE_REQUIRED_KEYS 追加 5 文案键 + narrative_approved；validate_enemy_document 增补类型校验（narrative_approved 必须 bool；文案必须 str；批准为真时文案非空）。
- managers/enemy_catalog.py：WorldBossProfile 追加 profile_version 与五文案 + narrative_approved 七个字段；from_dict 补 profile_version（此前丢弃，导致实例/台账版本恒 0），五文案用 entry[key] 直接索引（缺键 KeyError = fail closed），narrative_approved 取 bool。
- 兼容性：既有 tests/test_enemy_sync_gate.py / test_enemy_catalog_runtime.py 不改即通过（preview 28+4 行、validator 零错误）。

## 2. 仓储只读查询（消费 v37/v38，不改 schema）

data/pve_repository.py 新增（全部只读，_commit_if_standalone 语义不变）：
- WorldBossRepository.get_latest_terminal_instance()：WHERE state IN ('defeated','dissipated') ORDER BY terminated_at DESC, rowid DESC LIMIT 1 —— 这是 spawn_epoch 的唯一来源（禁 MAX(next_spawn_at)）；
- OutboxRepository.list_events_since(occurred_at_from, limit)：对已提交事件做固定窗口（600s）恢复扫描；
- OutboxRepository.list_deliveries_for_event(event_id)：用于判断事件是否已有 delivery（幂等补展开）。

## 3. WorldBossService（managers/world_boss_service.py，1052 行）

装配：WorldBossService(db, catalog, health_service, busy_state, combat_manager, config_manager=None, *, clock=time.time, rng=None, max_conflict_retries=3)；computed properties instances/outbox 每次新建仓储（DataBase.connect 会换 conn）；enabled = catalog 非空且有 world_boss profiles。

- R1 ensure_spawn(profile_id=None) → (instance, created, profile_id)：
  - 全程在单个 db.transaction() 内：先 _consume_expired_active(now) 幂等转换到期 active（CAS expected cas_version+state=active，写 state=dissipated/terminated_at=expires_at/next_spawn_at=expires_at+respawn*3600 并 append dissipated 事件），再查 active 行复用；
  - 再生资格：最近终态行的 next_spawn_at（无终态取 now）；未到期拒绝（事务外抛出，保证同事务内的到期消散不因回滚丢失）；
  - 选段：常规路径用注入 rng 的 seed 从 4 个境界段全随机（seed/selected_profile_id/selection_source/scheduled_epoch 全部写入出生快照，selection_source=seed 对齐 prd AC1）；GM 强制 profile_id 三分支：未知档案或 catalog=None 明确失败；无 active + forced 跳过资格立即生成（selection_source=forced、seed=0，出生记 logger.warning）；有 active 一律复用（forced 不同时 logger.warning，返回实际 profile_id）；
  - instance_id = "wb_{profile_id}_{spawn_epoch}"；insert_instance created=False 时回读必须仍 active，否则抛 WorldBossSpawnRejected("❌ 世界 Boss 生成冲突，请稍后重试。")；只有 created=True 才 append world_boss_spawn 事件。
- R2 生命周期：active → defeated | dissipated；终态与 next_spawn_at 同批写（击杀 12h / 消散 24h，出生快照可覆盖）；到期转换幂等（CAS 失败返回 False 不重复写事件）；TIME_SKIP_ENTRIES 由 P 在 managers/boss_manager.py 登记，本 child 只保证 next_spawn_at 可被快进（未重复声明，测试静态断言）。
- R3 每日次数：date_key 走 shanghai_date_key(clock)（ZoneInfo("Asia/Shanghai")，UTC 15:59/16:00 边界测试）；increment_daily_attempts 单语句上限内自增，超限返回 None 且不扣次数；失效/过期/忙碌/幂等重放路径都不扣。
- R4 原子挑战 challenge(player=…, challenge_id=…)：
  - 幂等：先 get_challenge(challenge_id)，已存在直接返回「✅ 本次世界 Boss 挑战已结算，无需重复提交。」；busy_state.assert_idle(user_id, template="❌ 你当前正忙，无法挑战Boss！")；
  - 短事务 prepare（get_player_by_id → health_service.settle → 重读玩家 → 实例 active/expires 校验 → date_key/每日次数校验），不含战斗；
  - 事务外固定 RNG 战斗：seed 由 rng_seed 或 sha256(challenge_id)[:16] 派生，保存/恢复全局 random state（沿用 pve_combat_manager 范式）；Boss Fighter 由实例面板包成 Enemy 后经 build_enemy_fighter 构建（不重建满血 profile、不自建 FighterState，E1 base_crit_rate 形参未落地故不传）；难度倍率取出生快照 difficulty_multiplier（出生时读 pve.difficulty_multiplier），按阶段择一相乘（P2 ×→phase2_damage_multiplier、P3 ×→phase3_damage_multiplier），P3 护甲 ×phase3_armor_multiplier；
  - 单笔短事务提交：实例 CAS（expected cas_version/state/current_hp）→ increment_daily_attempts → 重读玩家校验 (current_hp, health_recovered_at) 前像 → cas_update_player_health → record_challenge（created=False 视为已结算）→ record_ledger → accumulate_contribution → 阶段事件（phase_before+1..phase_after 各一条，copy_key 取 phase2_text/phase3_text）→ 末击 defeated 事件（kill_text）→ 回读实例；任一 False 立即 txn.abort()，最多 max_conflict_retries=3 次有界重算；只有成功 CAS 消耗次数；
  - 伤害 = max(0, hp_before - hp_after)（禁 max_hp-final_hp 重算）；玩家写回 max(engine_remaining_hp, defeat_hp_floor)（能力探测 health_service.defeat_hp_floor，E1 未落地回退 1，不引入第二常量；回退 1 只可能在有人绕过 E1 直接调 service 时出现，玩家入口切流在 E2 且 E1 先行，生产不会命中）；fled 恒 0；不写 fatigue、不收门票；
  - 失败文案：无 Boss / 已不在挑战期 / 已消散 / 次数用完（每日 N 次）/ 结算冲突，均为中文。
- R5 阶段：_next_phase 用剩余 HP 比例对 profile phase_thresholds（0.6/0.2 分数）判定，max(持久 phase, 目标) 只升不降；一次跨两阈值同一提交按 phase 2、3 各插一条唯一事件。
- R6 台账：world_boss_challenges / world_boss_ledger（UNIQUE instance+challenge）/ world_boss_contributions（total_damage、attempt_count、first/last_hit_at、is_last_hit=MAX）与挑战同事务写；不引用 stone_reward、不调用旧即时奖励（测试静态断言）。

## 4. WorldBossEventDispatcher（managers/world_boss_events.py，362 行）

- 事件类型 world_boss_spawn / _stage / _defeated / _dissipated，aggregate_type=world_boss_instance；business key = world_boss:{kind}:{instance_id}[:phase]（business_key UNIQUE 幂等）。
- render_event_text(event, instance)：只读实例出生快照的五个文案 + narrative_approved；未批准/缺 copy_key/坏 JSON/聚合类型不符一律返回 None（禁播，无 narrative_config/copy_variants/代码 fallback）。
- expand(event_id)：按发送时目标快照逐个 add_delivery（UNIQUE event+platform+group 幂等），返回新建数；非本域事件 0。
- dispatch_pending(now)：先 list_events_since(now-600) 对已提交但无 delivery 的事件补展开（固定 10 分钟窗口，不加 schema 列/配置项），再 list_deliveries → claim_delivery（只认 queued，owner+lease）→ 事务外 await sender：
  - 成功 → sent；已知失败 → attempt_count<max_attempts 时 queued（retry_at=now+backoff*attempts），否则 uncertain；
  - DeliveryUncertain（超时/结果不明）→ uncertain，永不自动重试（人工处置）；
  - 未批准/渲染失败 → uncertain，last_error 说明；
  - 已 sent destination 不因其他失败重播；陈旧 dispatching 由 list_stale_dispatching 暴露（测试覆盖）。
- 未注册 poller（main.py 只装配服务），网络 await 全在 DB 事务外。

## 5. main.py 装配

_wire_core_services：load_catalog(config/enemies.json) → EnemyCatalog|None；WorldBossService(self.db, enemy_catalog, health_service, busy_state, combat_mgr, self.config_manager) 加入返回 dict（enemy_catalog / world_boss_service）。config 仍是 v1 文档或缺文件时 catalog=None → 领域整体 disabled（prd R1）。不注册 poller、不改 handler、不接旧 broadcast_callback。

## 6. 测试（定向 43 例 + catalog 加载降级 1 例，真库 :memory: + 迁移 v39 + 固定时钟 + 脚本化战斗）

- tests/test_world_boss_domain.py（30 例，R1–R6 / AC1–AC5 / AC7）：单 active 与快照冻结、二次 ensure、forced 三分支、未知档案/未启用、击杀后未到再生时间拒绝、12h 后新实例 id、到期消散 + 72h 再生、两次 poll 单 active、可复现选段、难度出生固化（改配置不影响当前实例、下一实例生效）、challenge 结算台账贡献、每日 3 次封顶、过期拒绝不扣次数、阶段只升不降与两事件、末击唯一与终态挑战拒绝、challenge_id 幂等重放、地板写回（有 E1 API / 无 E1 API 两态）、忙碌守卫、北京日界（23:59:59 / 次日 00:00）、陈旧快照 CAS 失败、AC4 故障注入整笔回滚（实例 CAS 后次数递增失败）、AC8 并发 ensure 单行、AC8 并发挑战上限不超扣（台账累计 = 面板掉血恒等）、AC6 profile 文档 builder→validator→from_dict 往返、重启恢复（新服务实例复用 active Boss 并恢复次数/气血）、无 DEFEAT_HP_FLOOR_RATIO 与 stone_reward 静态断言、TIME_SKIP 映射静态断言。
- tests/test_world_boss_events.py（13 例，R7 / AC6）：renderer 批准/未批准/空文案/缺 copy_key/坏 JSON/外来事件；copy_key 阶段映射；expand 幂等；dispatch 单目标 sent 与 claim_owner 清空；恢复扫描窗口内补展开、窗口外不展开；partial success（一个目标失败不影响已 sent，恢复后只重发失败目标）；重试耗尽转 uncertain；DeliveryUncertain 不自动重试；未批准 → uncertain 且 sender 未被调用；外部 claim 不被抢、list_stale_dispatching 可见。
- 运行：/home/guigui/code/AstrBot/.venv/bin/python -m pytest tests/test_world_boss_domain.py tests/test_world_boss_events.py -q -p no:cacheprovider → 43 passed；tests/test_enemy_catalog_runtime.py 新增坏 JSON 降级用例（load_catalog 返回 None，不再炸启动）。

## 7. AC9 HP 锚（验收门 + 实测）

- 新增 design_docs/content-design/sim_world_boss_anchor.py（230 行，常驻门）：world_bosses.csv preview → EnemyCatalog → 生产 mapper build_enemy_fighter，T2 双路线、三阶段 40/40/20 加权、2000 场/格、占位 HP 1e9，对附录 F 锚 228/393/1035/1123 ±10% 断言，非零退出码。已登记 content-design/README.md 脚本表与 design_docs/README.md 资料清单。
- 实测（2000 场/格，50.2s）：朱厌 -1.0%、罴王 -1.3%、巴蛇 -0.1%、鼍龙 -0.8%，PASS 4/4（详见 research/ac9-hp-anchor.md）。

## 8. 质量门

- ruff format（本 child 触及文件）+ ruff check 产品范围（main.py core/ managers/ handlers/ data/ utils/ models.py models_extended.py tests/ + AC9 脚本）→ All checks passed；仓内既有 70 处告警全在 .trellis/scripts/**（vendored，非本 child）。
- 完整 pytest tests/ → **1224 passed in 6.24s**（评审修复 + 重启用例后复跑一致）。
- python3 scripts/audit_pve_redesign.py --scope all → 64 findings，逐条归属 e1（base_crit_rate 未物化、crit 双侧未接线、部分裸 commit）与 e2（旧 Boss 符号/配置/文案/时间快进属主），**无一条指向世界 Boss 新模块**；两者均为 E1/E2 范围。

## 9. 遗留 / 交接

- E1：base_crit_rate 物化后市 Boss 构建改传 base_crit_rate；defeat_hp_floor 落地后自动生效（能力探测已就绪）；文档与版本清单归 E1。
- E2：注册 poller（ensure_spawn + dispatch_pending 调用顺序见 E2 design §4）、切 挑战Boss/世界Boss/生成Boss 三指令到新领域、整删旧 BossManager/boss_handlers/BOSS_CONFIG/boss_config.json 与旧表迁移、正式 sync 启用固定名册（需用户内容批准，AI 不得代批）。
- 真实 webtest 回归由用户发起（项目约定）；本 child 未跑平台用例。
- 未 commit：本地改动待用户确认后分批提交（work commit → archive → journal 三段流）。

## 10. 双轴代码评审与修复（2026-11-09，code-review skill）

两个子代理并行审查（Standards / Spec，均 0 阻塞级），确认后修复：

- [Standards 中] 坏 JSON 会让插件加载崩溃：read_document 的 docstring 承诺 EnemyCatalogError，但 json.load 抛 JSONDecodeError（ValueError）；已在 managers/enemy_catalog.py 把 ValueError 包成 EnemyCatalogError，并补 catalog 加载降级用例。
- [Standards 中] dispatcher 构造时缓存仓储，DataBase.connect() 重连会换 conn：managers/world_boss_events.py 的 outbox/instances 改为每次现建 property（与 service 一致，E2 长驻 poller 安全）。
- [Spec 低] selection fact 键名对齐 prd：selection_source 常规路径改 "seed"、快照键 selection_seed 改 seed（AC1 字面值）；forced 出生改记 logger.warning（R1 要求 warning）。
- [Spec 中] 补 3 个验收用例：AC4 故障注入全回滚、AC8 并发 ensure/并发挑战、AC6 profile 文档往返；catalog 坏 JSON 降级 1 例。
- [两轴低] 地板回退 1：保留能力探测方案并注明 E1/E2 门禁（E1 先落地、玩家入口切流在 E2，生产不会命中 1 HP 语义），不引入第二常量、不跨域引用 adventure_manager 私有实现。
