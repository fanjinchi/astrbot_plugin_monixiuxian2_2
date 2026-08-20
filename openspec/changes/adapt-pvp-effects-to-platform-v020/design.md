# Design — adapt-pvp-effects-to-platform-v020

## Context

See proposal.md — Why. The platform test skill (testplatform repo, commit `0e3ad69`, v0.2.0) ships `deterministic`/`seed`, `expect_not`, `combine`, fresh-form `pin_players`, and one-shot orchestration CLI. Current state of the PvP effect suite:

- 20 case files under `functional_tests/cases/pvp/` carry the `sampled` tag; their `scenario` text states 概率触发需 `--repeat`（e.g. `pvp-effect-pierce.json`: "引擎无穿透专用文本…需 --repeat 聚合"；`pvp-weapon-trigger.json`: "概率触发，需配合 --repeat 聚合"）。
- All cases use fixed `pin_players` ids (`gm:900000001, p1:900000002, p2:900000003`), sequential `send`/`expect` steps with `re:` regex matching, and rely on the platform `run --repeat`/fixture aggregation for stochastic effects.
- Existing run/export flow is two-step: `test_suite_ctl.py sync-cases` then `run --tag …` + `export --target …`（结果归档 `functional_tests/results/<date>_<target>/`）。

## Goals / Non-Goals

**Goals**: Make stochastic PvP effect verification reproducible first (RNG seeding), keep the suite runnable in one command, keep result artifact structure unchanged, and keep gap-report honest（能力分类随平台版本演进）。

**Non-Goals**: 不改被测插件游戏代码/数值；不为平台开发新能力（时间加速、DB 直断等仍为缺口）；不把非 sect 域用例纳入 sect change 的范围；不在本 change 中完成 sect 相关用例适配（由 `update-sect-functional-tests` 负责）。

## Decisions

**Decision 1 — `deterministic: true` + `seed`（默认 42）为随机效果用例的主路径，`--repeat` 降为统计兜底。**
理由：平台 v0.2.0 在每次 send 注入前重置全局随机种子，使同 seed 运行可复现；PvP 用例的 send 序列是纯顺序队列（无并发异步 request），RNG 消费窗口紧凑，种子重置的"尽力而为"语义在此场景下实际可靠。备选：维持大 `--repeat` 采样——保留为兜底，但作为默认会使运行时长随用例数放大且 flaky 判定难收敛。
落地：仅在**确含随机抽取**的用例（17-20 个 `sampled` 标签文件）加 `deterministic: true` + `seed`；场景/描述文本同步注明"确定性优先，--repeat 兜底"；默认 repeat 降为 1-3，保留必要时手动放大与"连续两次不命中才判失败"的既有防 flaky 约定。

**Decision 2 — `pvp-weapon-trigger` 的跨回复断言用 `combine: true`（跨条拼接），不拆分成三个单武器子用例。**
理由：三角色各打一场、每场多条战斗回复，`combine` 可直接把窗口内多回复拼接成一条断言目标，减少步骤与超时敏感度；拆分方案会三倍 GM/装备/冷却准备与 fixture 依赖。备选（保留）：若实战中 combine 对多 round 时间窗不稳定，按武器拆三个 case 并各自减小范围。

**Decision 3 — 保持固定 `pin_players` id，不迁移 fresh 形式。**
理由：PvP 用例依赖 GM 指令按已知 id 精确设置属性/发放装备（`#修仙GM 设置攻击 900000002 200` 等），fixture（`test_suite_ctl.py fixture --profile pvp`）也以这三个 id 为目标；fresh 形式引入逐运行派生 id 会破坏这些引用。fresh 仅适合无跨指令 id 引用的用例（如每日签到），此类用例若存在再单独处理。daily-checkin-basic 的平台副本漂移（源缺失）不属于本 change 范围，只需在 3.1 基线扫描中登记。

**Decision 4 — 执行/归档改为 one-shot 管线，封装进 `scripts/test_suite_ctl.py` 保持 AGENTS.md 记载命令可用。**
理由：平台 CLI 已提供 `case check --source`、`run-all --sync-from --reload --export --quiet --include-manual`；项目既有入口脚本是 `test_suite_ctl.py`，在其 run/export 子命令上透明透传新参数（或文档化直连平台 CLI），避免 AGENTS.md/functional_tests/README.md 双入口漂移。结果仍落 `functional_tests/results/<date>_<target>/`（含 summary.json）。

**Decision 5 — gap 报告按平台版本重分类：RNG 注入（deterministic/seed）、负向断言（expect_not）、跨条匹配（combine）、one-shot 编排转已支持并删除对应绕行说明；DB 直断/时间加速保持 Unsupported。**

## Risks / Trade-offs

- [seed 重置为尽力而为，宿主异步活动可能消耗 RNG] → PvP send 序列为纯顺序队列，实际风险低；若仍失败回退 `--repeat` 统计路径（连续两次不中才判失败）。
- [combine 对多轮时间窗不稳定] → 保留拆分三武器子用例的备选方案（Decision 2）。
- [一次性改 20 个文件造成描述/场景文本失真] → 逐文件核对 scenario 文本与断言含义，仅加种子字段与措辞修改，不擅自改断言目标。
- [gap 报告重分类后旧绕行文本残留] → 重分类同时删除对应行/段落，保留变更记录注明平台版本。
- [漂移用例（daily-checkin-basic 仅平台侧有）污染回归] → 3.1 用 `case check --source` 基线扫描登记，不在本 change 内改动源文件。

## Migration Plan

1. 先在测试实例环境确认平台 v0.2.0 已部署（`/api/status` adapter_ready）。
2. 按任务更新 gap 报告 → 更新用例 → `sync-cases` → `case check --source` 校验 → one-shot `run-all --tag pvp … --export`。
3. 导出结果归档 `functional_tests/results/<date>_pvp-effects/`（含 summary.json）；回滚只需 git revert 用例/gap 报告改动，平台侧无状态变更。

## Open Questions

无阻塞项。`pvp-basic-spar` 的已知预期失败（handle_spar UnboundLocalError 怀疑）不受本 change 影响，按既有 bd 流程跟踪。