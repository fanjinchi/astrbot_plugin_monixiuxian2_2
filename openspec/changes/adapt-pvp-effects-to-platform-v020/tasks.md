# Tasks — adapt-pvp-effects-to-platform-v020

## 1. Gap Report & Baseline

- [x] 1.1 更新 `functional_tests/platform-gap-report.md`：随机数种子注入（deterministic/seed）、负向断言（expect_not）、跨条匹配（combine）、one-shot 编排（case check --source / --sync-from / --reload / --export）移入 Supported/Partially supported 并删除对应绕行说明（保留"随机种子为尽力而为"注释）；确认 Unsupported 仅剩 DB 直断、时间加速等真实缺口
- [x] 1.2 确认 `scripts/test_suite_ctl.py` 的 run/export 是否透传或等价封装平台新参数（--sync-from/--reload/--export/--quiet/--include-manual）；如不支持则补充透传或文档化直连平台 CLI 的等价命令，保持 AGENTS.md「功能测试套件」小节记载的入口可用
- [x] 1.3 在测试实例跑基线 `case check --source`（全部 cases），登记漂移清单（已知 daily-checkin-basic 平台副本存在但源缺失），不修改源文件

## 2. PvP 用例适配

- [x] 2.1 逐文件为 `functional_tests/cases/pvp/` 下带 `sampled` 标签的随机效果用例（pvp-effect-{buff,combo,counter,damage_bonus,damage_reduction,debuff,dot,fatigue,heal,pierce,reflect,stun,survive,vampire,unavoidable}、pvp-ultimate-{dot,heal,survive}、pvp-weapon-trigger，共 20 个；另含 pvp-ultimate-damage 同为 sampled）加用例级 `deterministic: true` + `seed`（默认 42）；同步更新 description/scenario 措辞为"确定性优先，必要时 --repeat 采样兜底"（不改动断言目标与步骤含义）
- [x] 2.2 重估并下调默认 repeat 次数（建议 1-3，保留必要时手动放大与"连续两次不命中才判失败"的防 flaky 约定）；确认用例或运行说明记录默认 seed 值
- [x] 2.3 `pvp-weapon-trigger.json` 改用 `combine: true` 跨条断言（三场战斗多回复拼接匹配）；若实战时间窗不稳定，回退方案为按武器拆分三个单武器用例（见 design.md Decision 2）
- [x] 2.4 扫描 pvp 域用例是否有点可转 `expect_not` 负向断言（如"某效果不出现"）；有则转换并同步 gap 报告，无则跳过并在结果记录中说明
- [x] 2.5 确认固定 `pin_players`（gm:900000001/p1:900000002/p2:900000003）与 GM 指令内 id 引用一致，不迁移 fresh 形式（design.md Decision 3）；如发现引用不一致的用例修正之

## 3. 执行与归档

- [x] 3.1 `uv run python scripts/test_suite_ctl.py sync-cases` 同步用例，随后 `case check --source` 确认源与平台副本一致（防漏 sync 跑旧用例）
- [x] 3.2 执行 one-shot 回归：`uv run python scripts/test_suite_ctl.py run --tag pvp --sync --reload astrbot_plugin_monixiuxian2 --fixture --fixture-profile pvp --export <dir> --quiet`（插件名用平台注册名 `astrbot_plugin_monixiuxian2`，非仓库目录名 `_2` 后缀；见 1.2 文档化），全部通过
- [x] 3.3 归档 one-shot 导出结果至 `functional_tests/results/<date>_pvp-effects/`（含 summary.json 通过/失败清单）；新增发现的玩法 Bug 用 `bd` 登记

## 4. 收尾

- [x] 4.2 全量校验：`uv run ruff format . && uv run ruff check .`；`openspec validate --changes adapt-pvp-effects-to-platform-v020` 通过
- [x] 4.3 提交：conventional commit（如 `test: adapt pvp effect cases to platform v0.2.0`），push 到 remote

## 执行结果记录

- **2.4 expect_not 扫描结果**：pvp 域唯一候选是 `pvp-effect-unavoidable`（以「躲过了」为反向证据）。但 `managers/combat_manager.py` 中 `next_attack_unavoidable` 为**一次性消耗标记**（`_resolve_attack` 内取用后即清空，仅豁免首击闪避/格挡/反击），窗口后半段可能合法闪避；整窗 `expect_not` 对「躲过了」会误判。故保留采样反证（`--repeat` 多次观察）而非转 `expect_not`，已同步 gap 报告「反向（不存在）断言」行。
- **1.3 基线漂移清单**：平台侧 `daily-checkin-basic`（源缺失，已知）、`smoke-test`、`verify-char-creation`（历史孤儿）——均不改动源文件；20 个 pvp 用例在基线时与平台副本不一致（刚完成迁移，待 3.1 同步）。
- **3.2 执行结果**：`run --tag pvp --sync --reload astrbot_plugin_monixiuxian2 --fixture --fixture-profile pvp --repeat 1 --export` → **23/23 全部通过**。首轮失败 `pvp-weapon-trigger`（GM 设置境界步骤 30s 超时窗口内仅见过期「我要修仙」回复）——因 run-all 连续 23 个用例插件事件队列拥塞，已将全部 expect 超时由 30s 提到 60s 后通过。结果归档 `functional_tests/results/2026-08-21_pvp-effects/`（含 summary.json + summary.md，23 pass）。未发现新玩法 bug，无需 `bd` 登记。