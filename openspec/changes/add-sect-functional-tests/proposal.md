# Proposal: add-sect-functional-tests

## Why

配套 change `add-default-sects-and-sect-growth` 将新增默认宗门、宗门建设、师承任务链、职阶晋升与内容联动等玩家可见玩法。这些链路（拜入→任务→建设→晋升→出师回收）必须走真实消息管线验证，单元测试无法覆盖。本 change 按 `functional_tests/` 既有套件规范为宗门新玩法补齐功能测试用例，并通过网页测试平台执行与归档。

## What Changes

- 在 `functional_tests/cases/sect/` 新增宗门域功能测试用例（JSON，兼容测试平台 `loader.validate_case`），覆盖：默认宗门播种可见性、拜入/境界校验、师承任务链推进与奖励、建设任务与建筑升级、职阶晋升双门槛与签到福利、出师时宗门之宝回收与功法保留、绑定物禁赠、宗门悬赏/秘境/历练过滤、商店职阶折扣。
- 用例打 `sect` 域标签，纳入 `run-all --tag sect` 回归。
- 同步用例到测试平台（`scripts/test_suite_ctl.py sync-cases`）、执行、导出结果归档到 `functional_tests/results/<date>_sect*/`。
- 若验证过程触及平台能力缺口（如需要直接置玩家贡献/境界的 fixture、RNG 控制），更新 `functional_tests/platform-gap-report.md`，并视需要扩展 `scripts/test_suite_ctl.py fixture` 的宗门 profile。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `functional-test-suite`: 新增 Requirement——宗门系统功能测试覆盖（用例域、覆盖链路、执行与归档要求）。

## Impact

- **代码**：仅测试资产与（可选）fixture 脚本扩展；不改动插件玩法代码。发现玩法 Bug 时用 `bd` 登记，不在本 change 内修。
- **依赖**：必须在 `add-default-sects-and-sect-growth` 实施完成后执行用例；用例编写可与实施并行，但以最终指令名为准。
- **平台约束**：用例设计优先只依赖 `functional_tests/platform-gap-report.md` 中 Supported 能力（指令链路 + 消息断言）；RNG/时间加速/DB 直断类断言标注为受限并给出替代断言策略。
- **实施归属**：本 change 交由其他 agent 实施；本 change 的 artifacts 即交接依据。
