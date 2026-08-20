# Tasks — adapt-pvp-effects-to-platform-v020

## 1. Gap Report & Baseline

- [ ] 1.1 更新 `functional_tests/platform-gap-report.md`：随机数种子注入（deterministic/seed）、负向断言（expect_not）、跨条匹配（combine）、one-shot 编排（case check --source / --sync-from / --reload / --export）移入 Supported/Partially supported 并删除对应绕行说明（保留"随机种子为尽力而为"注释）；确认 Unsupported 仅剩 DB 直断、时间加速等真实缺口
- [ ] 1.2 确认 `scripts/test_suite_ctl.py` 的 run/export 是否透传或等价封装平台新参数（--sync-from/--reload/--export/--quiet/--include-manual）；如不支持则补充透传或文档化直连平台 CLI 的等价命令，保持 AGENTS.md「功能测试套件」小节记载的入口可用
- [ ] 1.3 在测试实例跑基线 `case check --source`（全部 cases），登记漂移清单（已知 daily-checkin-basic 平台副本存在但源缺失），不修改源文件

## 2. PvP 用例适配

- [ ] 2.1 逐文件为 `functional_tests/cases/pvp/` 下带 `sampled` 标签的随机效果用例（pvp-effect-{buff,combo,counter,damage_bonus,damage_reduction,debuff,dot,fatigue,heal,pierce,reflect,stun,survive,vampire,unavoidable}、pvp-ultimate-{dot,heal,survive}、pvp-weapon-trigger，共 20 个）加用例级 `deterministic: true` + `seed`（默认 42）；同步更新 description/scenario 措辞为"确定性优先，必要时 --repeat 采样兜底"（不改动断言目标与步骤含义）
- [ ] 2.2 重估并下调默认 repeat 次数（建议 1-3，保留必要时手动放大与"连续两次不命中才判失败"的防 flaky 约定）；确认用例或运行说明记录默认 seed 值
- [ ] 2.3 `pvp-weapon-trigger.json` 改用 `combine: true` 跨条断言（三场战斗多回复拼接匹配）；若实战时间窗不稳定，回退方案为按武器拆分三个单武器用例（见 design.md Decision 2）
- [ ] 2.4 扫描 pvp 域用例是否有点可转 `expect_not` 负向断言（如"某效果不出现"）；有则转换并同步 gap 报告，无则跳过并在结果记录中说明
- [ ] 2.5 确认固定 `pin_players`（gm:900000001/p1:900000002/p2:900000003）与 GM 指令内 id 引用一致，不迁移 fresh 形式（design.md Decision 3）；如发现引用不一致的用例修正之

## 3. 执行与归档

- [ ] 3.1 `uv run python scripts/test_suite_ctl.py sync-cases` 同步用例，随后 `case check --source` 确认源与平台副本一致（防漏 sync 跑旧用例）
- [ ] 3.2 执行 one-shot 回归：`case run-all --tag pvp --quiet --sync-from ./cases --reload astrbot_plugin_monixiuxian2_2 --export ./results`（必要时按子 tag/单用例 `case run --repeat N --sync-from --reload` 聚合），全部通过
- [ ] 3.3 归档 one-shot 导出结果至 `functional_tests/results/<date>_pvp-effects/`（含 summary.json 通过/失败清单）；新增发现的玩法 Bug 用 `bd` 登记

## 4. 收尾

- [ ] 4.1 若 1.2 引入新命令/参数，同步 AGENTS.md「功能测试套件」小节与 `functional_tests/README.md`（one-shot 用法、case check --source、结果含 summary.json）
- [ ] 4.2 全量校验：`uv run ruff format . && uv run ruff check .`；`openspec validate --changes adapt-pvp-effects-to-platform-v020` 通过
- [ ] 4.3 提交：conventional commit（如 `test: adapt pvp effect cases to platform v0.2.0`），push 到 remote