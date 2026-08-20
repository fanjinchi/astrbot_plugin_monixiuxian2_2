# functional-test-suite Specification

## Purpose

Defines the repository-level functional testing harness for the cultivation plugin: where test cases and results live, how they are synced to the web test platform and archived, what coverage the suite must provide, and how player-vs-player battles verify content-design effects.

## Requirements

### Requirement: Canonical test asset directories
The repository SHALL maintain a canonical functional-test asset tree with a `cases/` subdirectory for source-of-truth case files and a `results/` subdirectory for archived test run results. Each versioned result run SHALL be placed under `results/<YYYY-MM-DD>_<target>/`, where `<YYYY-MM-DD>` is the local run date and `<target>` is a short human-readable test target (for example `pvp-effects`, `core-smoke`, `content-design`).

#### Scenario: A new functional test run is archived
- **WHEN** a functional test run for target `pvp-effects` completes on 2026-08-17
- **THEN** the run artifacts are stored under `functional_tests/results/2026-08-17_pvp-effects/` and include a summary plus per-case results

#### Scenario: A case file is stored in source of truth
- **WHEN** a developer adds a functional test case
- **THEN** the case file is stored under `functional_tests/cases/` using the test-platform-compatible JSON structure and is not written only to the platform data directory

### Requirement: Case sync and result export process
The repository SHALL provide a repeatable process (documented and, where practical, scripted) to deploy canonical case files into the web test platform's case directory and to export run records from the platform into a new result directory. Export SHALL include at least a summary of pass/fail per case and the platform run trajectory for each case. The execution pipeline SHALL support one-shot orchestration: validating that the platform copy matches the source of truth (`case check --source`), syncing (`--sync-from`), reloading the plugin under test (`--reload`), running a tagged subset (`run-all --tag`), and exporting results in a single command sequence, with results written to disk including a machine-readable summary.

#### Scenario: Cases are deployed to the platform
- **WHEN** the sync process is executed
- **THEN** all canonical case files under `functional_tests/cases/` are available to the test platform runner without manual copying errors

#### Scenario: Run results are exported to a dated result folder
- **WHEN** a test target has been executed on the platform and the export process is run against that run
- **THEN** a new `functional_tests/results/<date>_<target>/` folder is created and contains per-case pass/fail results and run trajectories

#### Scenario: Source drift is detected before a run
- **WHEN** a tester starts a tagged run with `case check --source`
- **THEN** any case whose platform copy differs from the canonical source is reported before execution, so stale cases are not silently run

#### Scenario: A tagged run is executed end-to-end in one shot
- **WHEN** a tester runs `case run-all --tag pvp --quiet --sync-from ./cases --reload <plugin> --export ./results`
- **THEN** cases are synced from source, the plugin is reloaded, the `pvp`-tagged subset runs, and results are exported to disk with a machine-readable summary
### Requirement: Functional test coverage across subsystems
The functional test suite SHALL include smoke and regression cases covering the plugin's major player-facing subsystems. The suite SHALL tag cases by functional domain so that a user can run a targeted subset via the platform's `run-all --tag` mechanism. At minimum, the suite SHALL cover player lifecycle, cultivation, breakthrough, equipment, pills, storage/shop, skills/loadout, PvP, sect, boss, bank/loan, bounty, adventure/rift, blessed land, spirit farm/eye, dual cultivation, and GM paths.

#### Scenario: Domain-tagged regression run
- **WHEN** a tester runs `case run-all --tag cultivation` after a cultivation change
- **THEN** all cultivation-domain cases execute and the run result indicates whether each passed or failed

#### Scenario: Unknown functionality has a smoke case
- **WHEN** a new user sends the basic startup command to a fresh test player
- **THEN** the suite has a case that verifies player creation and the first commands are reachable

### Requirement: Player-vs-player content-design effect verification
The functional test suite SHALL include group-chat PvP battle cases that use two distinct test players to verify effects designed in `design_docs/content-design/`. The suite SHALL cover heart-method passives, weapon/technique trigger skills, ultimate moves, and battle-status effects (dot/buff/debuff/fatigue/survive/reflect/pierce/unavoidable) by asserting observable battle-log evidence. Each PvP effect case SHALL document the expected evidence and SHALL apply a deterministic-first verification strategy: cases exercising stochastic effects SHALL declare case-level `deterministic: true` with a fixed `seed` so the random pool draw is reproducible, and use `--repeat` sampling only as a statistical fallback when determinism cannot be guaranteed. Cases with multi-reply flows SHALL use cross-message matching (`combine`) instead of per-message assertion where supported. PvP domain cases SHALL be tagged `pvp` (and `effect-matrix`/`content-design`/`sampled` as applicable) so a targeted regression run via `run-all --tag pvp` is possible.

#### Scenario: A heart-method passive is observed in battle
- **WHEN** two prepared players with known heart methods/equipment fight via 切磋
- **THEN** the returned battle log contains evidence that the heart-method bonuses are reflected in fighter attributes or battle outcomes

#### Scenario: A trigger-skill effect is verified
- **WHEN** a player equipped with a skill that has `effect_type=stun` fights another player
- **THEN** the suite attempts to capture a battle log line showing the stun/skip effect, and the case documents whether the effect is deterministic or sampled over repeated battles

#### Scenario: Ultimate unlock gate is verified
- **WHEN** a player with an ultimate that has `min_action_index` and/or HP thresholds fights a sufficiently long battle
- **THEN** the battle log eventually contains the ultimate activation only after the unlock conditions are met

#### Scenario: A stochastic effect is verified deterministically
- **WHEN** a case with `deterministic: true` and a fixed `seed` executes a battle where a random effect (for example pierce or counter) may trigger
- **THEN** the run is reproducible: the same case with the same seed yields the same battle outcome, and the case does not rely on large `--repeat` counts to observe the effect
### Requirement: Platform capability gap report
The repository SHALL maintain a platform capability gap report under `functional_tests/platform-gap-report.md` that classifies each test capability as fully supported, partially supported, or unsupported by the current web test platform. For each unsupported or partial capability, the report SHALL state the concrete limitation, why it blocks verification, and a recommended platform enhancement. Platform capabilities that have shipped since the last report update SHALL be reclassified as supported and their former workaround rows SHALL be removed from the report.

#### Scenario: A blocking capability is reported with evidence
- **WHEN** a desired PvP test cannot deterministically verify a random effect because the platform cannot seed RNG
- **THEN** the gap report lists that limitation under unsupported capabilities with the exact reason and a suggested enhancement

#### Scenario: Supported capabilities are separated
- **WHEN** the gap report is read
- **THEN** capabilities that the platform already supports (for example message injection, group conversations, `expect` matching, run trajectory storage) are listed separately from gaps so that the first case batch only relies on supported ones

#### Scenario: A platform capability is reclassified after release
- **WHEN** the test platform ships RNG seeding (`deterministic`/`seed`), negative assertion (`expect_not`), cross-message matching (`combine`), or one-shot orchestration flags
- **THEN** the gap report moves the corresponding rows to supported, removes the workaround text that referenced the old limitation, and the reclassification is noted in the report update
### Requirement: AGENTS.md testing process documentation
`AGENTS.md` SHALL document the functional-test-suite process: where canonical cases are stored, how to synchronize them to the platform, how to run them, where and how results are archived, and the result directory naming rule.

#### Scenario: A new contributor follows the documented process
- **WHEN** a contributor reads the AGENTS.md testing section after completing a gameplay change
- **THEN** they can determine where to add a case, which tag to use, how to run the case, and where the result folder will be created

### Requirement: 宗门系统功能测试覆盖

功能测试套件 SHALL 包含 `sect` 域标签的用例，覆盖默认宗门玩法的完整玩家链路：默认宗门在「宗门列表」可见且不可被玩家创建同名宗门；拜入（含境界区间校验拒绝）、师承任务链的阶段推进与奖励、宗门建设任务与建筑升级生效、职阶晋升的贡献+境界双门槛及签到福利加发、出师时宗门之宝回收且已习得宗门功法保留可用、绑定功法不可赠予他人、改换门庭后原宗门功法仍可使用、宗门悬赏/秘境/历练内容的成员过滤、商店职阶折扣结算。用例 SHALL 存放于 `functional_tests/cases/sect/` 并兼容测试平台校验，执行结果 SHALL 归档至 `functional_tests/results/<date>_<target>/`。需要平台不支持能力的断言 SHALL 记录到平台能力差距报告并采用替代断言策略。

#### Scenario: 宗门域回归执行

- **WHEN** 宗门功能变更后执行 `run --tag sect`
- **THEN** 全部宗门域用例经测试平台真实消息管线执行，逐用例给出通过/失败结果

#### Scenario: 拜入与出师回收链路验证

- **WHEN** 测试玩家依次执行加入默认宗门、完成师承阶段、退出宗门
- **THEN** 用例断言各步骤消息反馈符合预期，且退出后宗门之宝回收的提示出现、已习得绑定功法仍可正常使用

#### Scenario: 受限能力断言有替代策略

- **WHEN** 某验证点需要平台不支持的能力（如直接设置玩家贡献点）
- **THEN** 用例改用可达路径铺底（如 GM 指令或捐献指令累积），并将该限制登记到 `functional_tests/platform-gap-report.md`

### Requirement: 宗门指令统一与新专属内容的功能测试覆盖

功能测试套件 SHALL 随宗门指令统一变更同步演进：`functional_tests/cases/sect/` 中引用已移除旧指令的用例步骤 MUST 全部改写为「宗门」子命令形式，断言文案 MUST 与新回复模板一致，保证 `--tag sect` 回归在变更落地后全绿。套件 SHALL 新增用例覆盖：「宗门」无参数导航帮助与未知子命令拒绝、带参数子命令缺参提示；宗门悬赏独立入口的完整生命周期（查看/接取/进度/完成/放弃）与全局悬赏指令对宗门悬赏的拒绝分流；宗门专属秘境的可见性（本宗成员可见可进、非本宗不可见）；宗门商店（列表展示、贡献点购买成功、贡献不足拒绝、职阶门槛、无宗门拒绝）；历练结算中宗门事件的「🏯 宗门际遇」标记。随机性验证点（宗门事件触发、悬赏随机池）SHALL 优先采用用例级 `deterministic: true` + `seed` 确定性策略（send 注入前重置全局随机种子，尽力而为可复现），辅以 GM 强制结算与 `--repeat` 采样计数统计兜底，并在用例 `description` 中注明。执行与归档 SHALL 使用平台 one-shot 编排（`case check --source` 校验源与平台副本同步、`run-all --tag sect --quiet --sync-from --reload --export`），防遗漏同步导致跑旧用例。

#### Scenario: 存量用例迁移后回归全绿

- **WHEN** 宗门指令统一变更实施完成并热重载后执行 `run --tag sect`
- **THEN** 全部宗门域用例（含迁移后的存量用例）经真实消息管线执行通过，无残留引用旧指令的步骤

#### Scenario: 悬赏拆分双向分流验证

- **WHEN** 非宗门成员执行全局「接取悬赏 <宗门悬赏编号>」、宗门成员执行「宗门 悬赏」系列子命令
- **THEN** 用例断言全局入口拒绝并提示宗门悬赏入口，宗门入口各生命周期步骤反馈符合预期

#### Scenario: 宗门商店购买链路验证

- **WHEN** 测试玩家经 GM 指令预置贡献点后执行「宗门 商店 购买 <商品>」
- **THEN** 用例断言购买成功反馈与商品到账提示；贡献不足与职阶不足场景分别断言对应拒绝文案

#### Scenario: 秘境对非本宗成员不可见

- **WHEN** 非本宗成员查看秘境列表并尝试探索宗门专属秘境
- **THEN** 用例以 `expect_not` 负向断言列表不含该秘境（平台 v0.2.0 已支持），"探索被拒"的入口拦截消息仅作兜底；该能力在 gap 报告标记为已支持

#### Scenario: 宗门事件标记确定性验证

- **WHEN** 用例声明 `deterministic: true` + `seed`（默认 42）后对宗门成员以 GM 强制历练结算，必要时 `--repeat N` 采样统计
- **THEN** 用例断言「🏯 宗门际遇」标记出现（确定性路径优先；采样时记录触发次数证据），普通事件结算文案不含该标记
