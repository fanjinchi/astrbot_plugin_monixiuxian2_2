# 功能测试结果：2026-09-12_ju1-fix

- 导出时间：2026-09-12T01:32:03
- 运行记录数：6
- 通过：6
- 失败/错误：0
- 不稳定：0
- 跳过：0

## 通过用例

- breakthrough-fail-pity
- breakthrough-guarantee
- breakthrough-title-layout
- daily-checkin-basic
- player-lifecycle
- verify-char-creation

## 失败/错误用例


## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- breakthrough-fail-pity: pity_streak_bonus= 3, pity_hint_prose= 7（采样 1 次）
- breakthrough-guarantee: pity_guarantee= 3, streak_reward_prose= 3（采样 1 次）
- breakthrough-title-layout: pity_guarantee= 2, streak_reward_prose= 2（采样 1 次）

## 证据路径

- 逐用例结果：`cases/`
- 消息轨迹：`messages/`

> 随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度。
> 上面的人数/次数计数只证存在性：同一个 combine 窗口的 fullText 会出现在多个
> 步骤的 actual 与逐条消息里，计数因而被放大；判定请回看 `messages/` 原文。
> `最长回合` 是该用例单场战报的最大回合数，用于判断触发率断言的前提是否成立
> （见 README「概率效果口径」）。

## 归档注记（2026-09-12 事后补记，第三轮评审 P3-1/P3-2）

- 目录名：本批导出时被误命名为 `2026-09-11_ju1-fix`，而 6 条 run 的 `started_at` 全在
  2026-09-12 01:28:28–01:31:36（导出 01:32:03），不符合 `functional_tests/README.md`
  「目录名固定 `<YYYY-MM-DD>_<target>` 取运行日期」的约定，已改名。根因在
  `scripts/test_suite_ctl.py cmd_export()`：走 `.last-run.json` manifest 分支时 `--date`
  只用于目录命名、不做时间过滤（已在生成器里补上日期校验/自纠）。
- 并发污染：第三轮评审从平台侧看到 run 740/741/742/744 与本归档的 739（01:28:28.6→
  01:29:30.5）、743（01:29:30.8→01:30:31.5）墙钟重叠（重叠时段由评审核对平台库得出，本
  仓内只能自证 739/743 自己的窗口），违反 README「同库禁止并发跑批」（共享固定测试 ID 与
  `.fixture-backup.json`），故 739/743 的基线洁净度无法自证。验收锚 run 745
  （breakthrough-title-layout，01:30:31.49→01:30:31.90，唯一直接证明 -ju1 排版修复真机生效
  的一条）紧随 743 结束（01:30:31.45）之后、在评审报告的重叠窗口之外，且归档内
  `steps_result[0]` 记有 `pre_run_hook`「hook 退出码 0」（fixture --profile breakthrough
  --breakthrough-streak 19），因此本批验收结论不受该污染推翻。
- 上条 footer（“随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度”）是当时
  生成器写下的旧口径，已被本批 README 改正；此处保留历史原貌，现行口径见
  `functional_tests/README.md`「概率效果口径」。
- 其中 `daily-checkin-basic`（run 746）、`verify-char-creation`（run 748）两例当时仓库内无源
  文件（仅存在于平台 `cases/` 目录），已由同轮评审 P3-3 回填到 `functional_tests/cases/player/`。
