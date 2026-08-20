## Why

测试平台 skill 已升级到 v0.2.0（testplatform 仓库 commit `0e3ad69`）：新增用例级随机种子注入（`deterministic: true` + `seed`）、负向断言 `expect_not`、跨消息拼接 `combine: true`、`pin_players` fresh 新形式，以及 one-shot 编排 CLI（`case check --source` / `run-all --sync-from --reload --export`）。现有 17 个 PvP 效果域 `sampled` 用例（`pvp-effect-*`、`pvp-ultimate-*`、`pvp-weapon-trigger`）仍使用旧式固定身份 `pin_players`，随机效果断言只能靠 `--repeat` 大次数采样聚合，运行慢、易 flaky、结果不可复现。

## What Changes

- **确定性优先**：17 个 `sampled` 用例声明用例级 `deterministic: true` + `seed`（默认 42），随机效果断言改为确定性可复现路径；`--repeat` 采样降为统计兜底，可显著缩小 repeat 次数。
- **跨消息断言**：`pvp-weapon-trigger`（多回复轮次流）改用 `combine: true` 跨条拼接匹配，替代逐条 `expect`。
- **负向断言**：如用例描述中存在可转负向断言的验证点（如"不出现某效果"）改用 `expect_not`（当前扫描显示非 sect 域暂无此需要，保留为可选约定）。
- **同步防漂移**：执行链路加入 `case check --source` 前置校验，防止源与平台副本漂移导致跑旧用例。
- **执行与归档 one-shot**：PvP 域回归改用 `run-all --tag pvp`（必要时分 tag）+ `--sync-from --reload --export` 一条命令完成，结果落盘含 summary.json；`functional_tests/results/<date>_<target>/` 命名不变。
- **gap 报告同步**：`functional_tests/platform-gap-report.md` 中"随机数种子注入"（原 Unsupported）与相关绕行说明转为已支持并从绕行策略移除；保留真正的缺口（DB 直断、时间加速等）。

## Capabilities

### New Capabilities
<!-- 无新能力 -->

### Modified Capabilities
- `functional-test-suite`: "Player-vs-player content-design effect verification" 从"可采样或确定性"改为"确定性优先（`deterministic: true` + `seed`，`--repeat` 兜底）"；"Case sync and result export process" 增加 `case check --source` 源同步校验与 one-shot 导入导出编排；"Platform capability gap report" 的 RNG 注入行转入已支持。

## Impact

- 用例文件：`functional_tests/cases/pvp/*.json`（17 个 `sampled` 用例 + `pvp-weapon-trigger` 等）
- `functional_tests/platform-gap-report.md`：随机种子注入与编排能力行更新
- 执行脚本：`scripts/test_suite_ctl.py`（run/export 适配 one-shot 参数，如需要）
- 测试平台：要求 v0.2.0 skill（仓库已更新，无需改动平台代码）
- 不修改被测插件游戏代码；结果归档目录 `functional_tests/results/<date>_pvp-effects/` 结构不变