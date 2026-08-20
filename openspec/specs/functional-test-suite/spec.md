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
The repository SHALL provide a repeatable process (documented and, where practical, scripted) to deploy canonical case files into the web test platform's case directory and to export run records from the platform into a new result directory. Export SHALL include at least a summary of pass/fail per case and the platform run trajectory for each case.

#### Scenario: Cases are deployed to the platform
- **WHEN** the sync process is executed
- **THEN** all canonical case files under `functional_tests/cases/` are available to the test platform runner without manual copying errors

#### Scenario: Run results are exported to a dated result folder
- **WHEN** a test target has been executed on the platform and the export process is run against that run
- **THEN** a new `functional_tests/results/<date>_<target>/` folder is created and contains per-case pass/fail results and run trajectories

### Requirement: Functional test coverage across subsystems
The functional test suite SHALL include smoke and regression cases covering the plugin's major player-facing subsystems. The suite SHALL tag cases by functional domain so that a user can run a targeted subset via the platform's `run-all --tag` mechanism. At minimum, the suite SHALL cover player lifecycle, cultivation, breakthrough, equipment, pills, storage/shop, skills/loadout, PvP, sect, boss, bank/loan, bounty, adventure/rift, blessed land, spirit farm/eye, dual cultivation, and GM paths.

#### Scenario: Domain-tagged regression run
- **WHEN** a tester runs `case run-all --tag cultivation` after a cultivation change
- **THEN** all cultivation-domain cases execute and the run result indicates whether each passed or failed

#### Scenario: Unknown functionality has a smoke case
- **WHEN** a new user sends the basic startup command to a fresh test player
- **THEN** the suite has a case that verifies player creation and the first commands are reachable

### Requirement: Player-vs-player content-design effect verification
The functional test suite SHALL include group-chat PvP battle cases that use two distinct test players to verify effects designed in `design_docs/content-design/`. The suite SHALL cover heart-method passives, weapon/technique trigger skills, ultimate moves, and battle-status effects (dot/buff/debuff/fatigue/survive/reflect/pierce/unavoidable) by asserting observable battle-log evidence. Each PvP effect case SHALL document the expected evidence and, for stochastic effects, the repetition or deterministic setup strategy used to make the check meaningful.

#### Scenario: A heart-method passive is observed in battle
- **WHEN** two prepared players with known heart methods/equipment fight via 切磋
- **THEN** the returned battle log contains evidence that the heart-method bonuses are reflected in fighter attributes or battle outcomes

#### Scenario: A trigger-skill effect is verified
- **WHEN** a player equipped with a skill that has `effect_type=stun` fights another player
- **THEN** the suite attempts to capture a battle log line showing the stun/skip effect, and the case documents whether the effect is deterministic or sampled over repeated battles

#### Scenario: Ultimate unlock gate is verified
- **WHEN** a player with an ultimate that has `min_action_index` and/or HP thresholds fights a sufficiently long battle
- **THEN** the battle log eventually contains the ultimate activation only after the unlock conditions are met

### Requirement: Platform capability gap report
The repository SHALL maintain a platform capability gap report under `functional_tests/platform-gap-report.md` that classifies each test capability as fully supported, partially supported, or unsupported by the current web test platform. For each unsupported or partial capability, the report SHALL state the concrete limitation, why it blocks verification, and a recommended platform enhancement.

#### Scenario: A blocking capability is reported with evidence
- **WHEN** a desired PvP test cannot deterministically verify a random effect because the platform cannot seed RNG
- **THEN** the gap report lists that limitation under unsupported capabilities with the exact reason and a suggested enhancement

#### Scenario: Supported capabilities are separated
- **WHEN** the gap report is read
- **THEN** capabilities that the platform already supports (for example message injection, group conversations, `expect` matching, run trajectory storage) are listed separately from gaps so that the first case batch only relies on supported ones

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
