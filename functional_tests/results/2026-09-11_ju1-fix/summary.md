# 功能测试结果：2026-09-11_ju1-fix

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
