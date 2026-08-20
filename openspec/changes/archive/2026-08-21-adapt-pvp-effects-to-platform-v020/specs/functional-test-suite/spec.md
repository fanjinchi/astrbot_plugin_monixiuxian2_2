## MODIFIED Requirements

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