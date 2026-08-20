# Proposal: update-sect-functional-tests

## Why

配套 change `unify-sect-commands` 将移除 18 个旧宗门顶层指令、拆分宗门悬赏、收窄宗门秘境可见性，并新增宗门专属商店与历练宗门事件标记。现有 `functional_tests/cases/sect/` 的 12 条用例全部建立在旧指令之上，变更落地后会整域失效；新功能也没有任何功能测试覆盖。本 change 同步改写存量用例并补齐新功能用例，保持 `sect` 域回归可用。

## What Changes

- **存量用例迁移**：`functional_tests/cases/sect/` 下引用旧指令（创建/加入/退出宗门、我的宗门、宗门列表/捐献/晋升、师承任务等）的用例步骤全部改写为 `/宗门` 子命令形式，断言文案随新回复模板同步修订。
- **悬赏拆分用例**：改写 `sect-content-filter`——全局「接取悬赏 307/308」改为"请走宗门悬赏入口"类拒绝断言；新增宗门悬赏生命周期用例（`/宗门 悬赏` 查看/接取/进度/放弃，成员与非成员对照）。
- **秘境可见性用例**：`sect-content-filter` 中非成员断言改用 `expect_not` 负向断言（平台 v0.2.0 已支持：列表不含该秘境），"探索被拒"作兜底，成员可见可进断言保留。
- **新增用例**：`/宗门` 导航与未知子命令、缺参提示；宗门商店（列表展示、GM 置贡献后购买成功、贡献不足拒绝、职阶门槛、无宗门拒绝）；历练宗门事件标记（用例级 `deterministic: true` + seed 确定性断言 🏯 宗门际遇，`--repeat` 采样计数兜底）。
- **能力缺口同步**：`functional_tests/platform-gap-report.md` 更新——`expect_not` 负向断言与 `deterministic`/`seed` 随机注入转为已支持并移除对应绕行行；仅保留真正的缺口（DB 直断、时间加速等）。
- **执行与归档**：`sync-cases` 后先用 `case check --source` 校验同步，再以 one-shot 管线 `run-all --tag sect --quiet --sync-from ./cases --reload astrbot_plugin_monixiuxian2_2 --export ./results` 执行并落盘，结果导出至 `functional_tests/results/<date>_sect-commands/`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `functional-test-suite`: 新增 Requirement——宗门指令统一与新专属内容的功能测试覆盖（存量用例迁移、新功能用例、执行与归档要求）。

## Impact

- **代码**：仅测试资产（`functional_tests/cases/`）与 `functional_tests/platform-gap-report.md`；不改动插件玩法代码。所需的 GM 测试辅助指令「清除悬赏」（清理进行中悬赏与放弃冷却）由 `unify-sect-commands` 实施，本 change 的悬赏用例依赖其就绪。验证中发现的玩法 Bug 用 `bd` 登记。
- **依赖**：用例编写可与 `unify-sect-commands` 实施并行；**执行必须在其完成并热重载后**。断言文案以最终实现为准。
- **平台约束**：用例只依赖 gap 报告中 Supported 能力（指令链路 + 文本断言 + v0.2.0 的 `expect_not`/`deterministic`/`combine`）；随机池走确定性+采样兜底，DB 直断等真正缺口采用报告记录的绕行策略，新增缺口补登报告。
