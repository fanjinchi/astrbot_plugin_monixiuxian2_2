# PVE 怪物与世界 Boss 重做总规划

## Goal

把 `design_docs/content-design/pve-enemy-design.md` 已封板的 PVE 设计落成工程任务：固定敌人名册、玩家持续气血、普通 PVE 结算、世界 Boss 生命周期与内容激活，最终与设计验收口径一致。

用户价值：敌人强度不再由旧经验公式派生；战斗损耗跨场保留并自然恢复；世界 Boss 成为有限次数、多人累计贡献、可恢复生命周期的全服玩法。

## Background and Confirmed Facts

- 设计已封板 Step 0–6（`pve-enemy-design.md:31-51`）：28 只普通/精英/组内 Boss、3 只动态守护者、4 只世界 Boss；地板/标模/天花板验收矩阵与模拟器见 `:346-417`。
- Step 7 奖励经济**未**封板（`:624-637`）：本轮不实施新掉落/分账数值，只产出稳定结算事实。
- `enemies.csv` / `world_bosses.csv` 仍 `status=draft`、叙事占位（`AGENTS.md` §15）：未经用户确认不得同步正式配置。
- child A 已交付 `base_hp`/`current_hp`/`max_hp` 三层气血与 Health Domain；child B 已交付内容管线与不可变 catalog（真实 CSV → preview 28+4 四层一致）。
- `config/enemies.json` 仍是 v1：只有 `enemy_groups`（5 组旧模板：low/mid/high/top/legacy_guardian）、`drop_tables`、`naming`；普通 PVE 仍走旧经验派生。
- 旧 Boss 为独立旧实现（`managers/boss_manager.py` 等），2026-10-28 用户拍板直接放弃、不迁移不归档，随 E2 整删。

## Requirements

### R1. 规划与内容治理

- 总任务拆为 8 个可独立验收的子任务：A 气血（已归档）、B 固定目录（已归档）、P 持久化/事务基座（已归档）、F 逃跑契约重拍（已归档）、C 普通 PVE 结算（已归档）、D 世界 Boss、E1 跨系统收口、E2 内容激活与旧 Boss 整删切流。
- 封板数值与占位叙事分开标识：工程实施不得默认为内容定稿。
- 正式敌人内容只能经 `scripts/sync_content_to_config.py` 从 `design_docs/` 导入，禁止手改生成配置。
- 守护者继续走动态匹配兼容路径，本轮不宣称守护者胜率锚。

### R2. 玩家持续气血

- `base_hp` 永久基础、`current_hp` 当前资源、`max_hp` 运行时上限；旧 `hp` 已无损迁移且不保留 alias。
- 恢复 = 每分钟动态 `max_hp` 的 1%，**全时段计时**（2026-10-12 取消「仅空闲」闸门），不依赖常驻定时器。
- 动态上限下降时 `current_hp` 钳制到 `[0, max_hp]`；突破只增长 `base_hp`。
- PVE 败场地板见 `10-10-pve-cross-system-integration/design.md` §2（`defeat_hp_floor`），胜场不保底；历练与世界 Boss 统一适用（2026-10-12 由 25% 下调）。

### R3. 固定敌人名册运行时

- 28 只名册按设计段位与绝对面板生成，不再由 `exp_needed`、类别倍率、随机等级或 ±10% 抖动重建。
- 运行时档案完整携带 `level_index`、暴击、词缀、触发技、护甲与五维，映射收敛到唯一 mapper。
- `difficulty_coefficients` 等无消费者旧路径移除；全局难度活旋钮只乘伤害。
- 守护者与秘境定向组不因普通名册切换而退化；CSV→config→Enemy→Fighter 四层一致性有测试。

### R4. 普通 PVE 规则

- 选择、胜负、TTK、气血回写、保底、疲劳、逃跑按封板执行；逃跑为**全风险档**战前一次选择（2026-10-19 重拍，见设计 §Q4）。
- 疲劳：路线基础 300/600/900/1200 秒（按路线）+ 仅真实战败再 +600；**每人一份全局窗口**（乙案），纳入 GM 时间快进。
- 运行时验收复用设计模拟器的标模与统计口径；Step 7 完成前不得以临时数字冒充正式经济。

### R5. 世界 Boss 生命周期

- 4 只固定档案、境界段随机、48h 存活、击杀 12h / 消散 24h 后再生资格（**细节归 D**）。
- 每名玩家每 `Asia/Shanghai` 自然日 3 次；绝对时间戳纳入 GM 时间快进，`date_key` 不登记。
- 每场原子更新 Boss 气血、当日次数、真实伤害、累计贡献与阶段；并发不超扣、末击者唯一。
- 阶段 60%/20%，倍率 ×1.10 / ×0.90 / 护甲 ×0.50；阶段/击杀/消散先产生唯一业务事件，再按 platform/group 建 per-destination delivery。
- 本轮只落台账与末击事实，不发奖励（Step 7 前）。

### R6. 奖励边界（仅预留）

- Step 7 的丹药/材料/掉落/分账数值延后到正式秘境设计完成后统一规划；本轮不填临时正式数值。
- 只定义稳定结算输出与贡献/末击事实，使后续奖励无需重写战斗事务；后续发放须可幂等重试并经用户确认同步。

### R7. 兼容、文档与质量

- 迁移覆盖 v34→latest，版本只在成功后推进，fresh 与升级 parity。
- 旧 Boss 数据与结构直接放弃（2026-10-28），旧表/旧 key/旧实现/旧测试在内容批准后的同一激活检查点整删（归 E2）。
- 玩法与架构文档（`design_docs/`）与实现保持一致，新增 API 登记 `api-overview.md`。
- 质量门：`uv run ruff format .` + **产品范围** ruff（`core managers handlers data utils main.py models.py models_extended.py tests`）+ `uv run python -m pytest tests/ -v`；机械清理判据一律跑 `python3 scripts/audit_pve_redesign.py --scope all`（文档不再抄 grep）。
- 真实 webtest 仅在用户明确要求时运行。

## In Scope

- 内容状态与运行时契约封板、气血三层与全消费者迁移、固定名册运行时与战斗接线。
- 普通 PVE 战后规则、世界 Boss 实例/阶段/次数/台账/广播/重启恢复。
- 旧 Boss 实现/表/键/测试整删（随 E2 激活检查点）、单元/配置/迁移/功能用例补强。

## Out of Scope

- `-6ow` 正式秘境生态、Step 7 经济总账、`-lky` 叙事创作、三守护者胜率重标、第二季 top 三兽、战斗引擎通用再平衡、未经用户要求的 webtest。

## Acceptance Criteria

- [x] AC1：拆为 8 个有依赖/验收门/回滚点的子任务（A/B/P/C/F 已归档；D/E1/E2 见各自任务）。
- [ ] AC2：旧玩家迁移后气血无损、当前气血合法；全 HP 消费者经新契约与回归（**child A 已交付迁移与 Health Domain**；全消费者组合复核归 E1）。
- [x] AC3a：28 只名册四层逐项一致，守护/秘境兼容测试通过（child B 已交付并归档）。
- [ ] AC3b（**外部门：用户内容批准**）：正式 v2 config 生效、运行态旧派生不再被普通 PVE 命中（代码静态保留为回落）、28 名册经 E2 AC2 可达。
- [ ] AC4（地板边界甲案）：历练 1% 地板由 C 落地（已归档）；秘境兽/传承守护者（含宗门领取）由 E1 统一；PvP 不适用；败场气血、疲劳、逃跑可观察验证。（**数值回归不在本 AC**：普通/精英/组内 Boss 的胜率·TTK·资源税移交 bd `-9u2`；资源税口径以附录 C.6 为准。）
- [ ] AC5：世界 Boss 在重启/跨日/过期/并发下单一合法状态；次数、真实伤害、累计、阶段、唯一末击可验证；地板 1%（每场按败场口径、含末击场）；HP 锚以 D AC9 为准并由 E2 复跑。
- [ ] AC6：阶段/击杀/消散事件唯一，per-destination partial success 隔离，已 sent 不重播、uncertain 可审计；只持久化贡献/末击事实，不引入未确认经济数值。
- [x] AC7a：迁移、定向、完整 pytest、产品范围 ruff 通过；文档与实现一致。
- [ ] AC7b（**外部门：用户内容批准**）：双闸门（combat/narrative 独立批准 + manifest/hash/列范围）通过后激活；未批准以「代码就绪、内容待批」结案（归 E2）。

## Resolved Product Decisions

- 未上线：一次性明确迁移，不做长期双写/alias；正式内容未批准前旧入口维持原状，获批后原子停旧启新。
- Step 7 延后到正式秘境设计完成后统一规划；本轮只产稳定结算事实。
- 世界 Boss 每日次数以 `Asia/Shanghai` 自然日为唯一边界。
- 气血三层命名，旧 `hp` 不保留 alias。
- 逃跑全风险档一次判定：成功 ×0.3、不掉落不滚传承、不产生击败事实；失败锁定同敌人开战；参数 2026-10-19 封板。
- 2026-10-12：①恢复全时段；②基础疲劳 300/600/900/1200 保留，仅取消路线 `injury` 的 +600；③C 获准 v39（`adventure_settlements` 状态机列）；④历练副作用用提交后 inline claim 而非广播 outbox；⑤迎战/逃跑指令定名；⑥疲劳粒度乙案（全局窗口）；⑦参数未封板时战前选择面整体 disabled（已被 10-19 重拍覆盖）。
- 2026-10-28：①旧 Boss 数据与结构直接放弃，表/key/实现/测试/配置三元组/`lint_narrative` 脱钩在同一激活检查点整删（归 E2）；②E 拆为 E1（代码收口）+ E2（内容激活）；③AC3/AC7 拆「可关闭/外部门」，胜率·TTK·资源税移交 bd `-9u2`；④世界 Boss 5 个叙事文案随 profile 契约携带。
