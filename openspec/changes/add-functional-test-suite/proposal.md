## Why

修仙插件已经拥有贴近真实管线的网页测试平台，但目前缺少**项目内统一、可版本化、可归档**的功能测试用例与测试结果存放规范；同时 content-design 中大量功法/心法/大招/持续状态效果已入库，尚未系统性地通过**玩家互相对战**验证各效果是否真实触发。没有这套资产，功能回归只能靠临时手工发消息，效果引擎出现静默不触发/数值偏差时难以及时发现。

## What Changes

- 在项目仓库内新增统一测试资产目录 `functional_tests/`，作为**用例源文件与测试结果的唯一归档地**：
  - `functional_tests/cases/`：结构化功能测试用例 JSON（source-of-truth，按功能域分子目录）；
  - `functional_tests/results/<YYYY-MM-DD>_<测试目标>/`：每次测试运行新增一个结果目录，内含该次运行摘要、逐用例结果与消息轨迹导出；
  - `functional_tests/README.md`：目录规范、命名规则、运行与归档流程。
- 新增/落地用例同步与结果导出脚本（基于测试平台现有 REST/CLI）：
  - 将 `functional_tests/cases/` 部署到测试平台数据目录 `data/plugin_data/astrbot_plugin_testplatform/cases/`；
  - 运行后从平台拉取 `case_runs` 轨迹，按结果目录规范写入 `functional_tests/results/`。
- 将上述流程写入 `AGENTS.md` 测试章节：如何添加用例、如何运行、结果如何归档、测试结果目录命名规范。
- 编写第一批**功能测试用例**，覆盖当前架构中的主要子系统：玩家创建/信息、闭关/出关、突破、装备/卸下、丹药/丹阁、商店/储物戒、技能/功法激活与卸下、切磋/决斗/传承PK、宗门、Boss、银行/贷款、悬赏、历练/秘境、洞天/灵田/灵眼、双修、GM 工具等。
- 编写**玩家互相对战用例**，专门验证 `design_docs/content-design/` 中已设计的机制是否在真实管线中触发：
  - 心法被动（`hp_percent`/`damage_percent`/`agility_percent`/`speed_percent`/`armor_value`/`route_multiplier`）；
  - 功法触发技（damage_bonus/combo/stun/counter/damage_reduction/heal/vampire/dot/buff/debuff/unavoidable/pierce/reflect/fatigue/survive）；
  - 大招（必放制、解锁门槛、单场一次）；
  - 战报合并、冷却、忙碌状态拦截等战斗外围行为。
- 产出**测试平台能力差距报告**（`functional_tests/platform-gap-report.md`）：逐项分析当前平台能验证哪些测试、不能验证哪些（如确定性随机数、直接数据库断言、时间加速、批量结果导出、精确战斗数值采集等），并提出平台后续增强建议。
- 使用当前可用的平台能力先运行已覆盖的用例，将结果归档到 `functional_tests/results/`；发现的功能性 Bug 单独登记 bd issue，不在本变更中直接修游戏代码。

## Capabilities

### New Capabilities

- `functional-test-suite`: 项目内功能测试套件能力——统一用例/结果目录规范、用例同步与结果导出流程、功能回归用例库、PvP 战斗效果验证方案、测试平台能力差距报告。该能力描述的是开发/测试侧的行为契约，不改变游戏运行时行为。

### Modified Capabilities

（无。本变更不修改游戏玩法、不改变既有 spec 的行为；测试平台仅作为被测系统外部工具被调用，需要的新能力通过差距报告提出，不在本变更实现。）

## Impact

- **新增代码/文件**（均不影响游戏运行时）：
  - `functional_tests/` 目录（`cases/`、`results/`、`README.md`、`platform-gap-report.md`）；
  - `scripts/sync_test_cases.py`、`scripts/export_test_results.py`（或合并为一个 `scripts/test_suite_ctl.py`）。
- **既有文件修改**：
  - `AGENTS.md`：新增“功能测试套件”章节；
  - `design_docs/README.md`：登记新增测试套件资料（如需要）；
  - `design_docs/test-platform.md`：补充“项目内用例/结果归档”衔接说明（如需要）。
- **不修改**：游戏插件运行时代码（`main.py`/`handlers/`/`managers/`/`core/`/`data/`/`config/`）、`metadata.yaml`、游戏数据库结构、测试平台插件代码。
- **依赖**：复用已存在的测试平台 REST/CLI；Python 标准库 + 已有 `uv` 环境，不新增第三方依赖。
- **产出物**：第一批功能测试用例、PvP 效果验证用例、平台能力差距报告、首轮测试结果归档；若测试暴露游戏 Bug，另开 bd issue 跟踪修复。