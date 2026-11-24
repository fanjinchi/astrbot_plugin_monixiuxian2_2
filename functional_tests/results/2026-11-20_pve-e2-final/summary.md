# 功能测试结果：2026-11-20_pve-e2-final

- 导出时间：2026-11-20T17:30:02
- 运行记录数：10
- 通过：10
- 失败/错误：0
- 不稳定：0
- 跳过：0

## 通过用例

- pve-roster-jd
- pve-roster-lq
- pve-roster-yy
- pve-roster-zj
- world-boss-daily-limit
- world-boss-dissipate
- world-boss-jd-kill
- world-boss-lq-kill
- world-boss-yy-kill
- world-boss-zj-kill

## 失败/错误用例


## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- pve-roster-jd: round_header= 4（采样 1 次，最长回合=1）
- pve-roster-lq: round_header= 4（采样 1 次，最长回合=1）
- pve-roster-yy: round_header= 4（采样 1 次，最长回合=1）
- pve-roster-zj: round_header= 4（采样 1 次，最长回合=1）
- world-boss-daily-limit: round_header= 2（采样 1 次）
- world-boss-dissipate: round_header= 7（采样 1 次）
- world-boss-jd-kill: round_header= 13（采样 1 次）
- world-boss-lq-kill: round_header= 13（采样 1 次）
- world-boss-yy-kill: round_header= 13（采样 1 次）
- world-boss-zj-kill: round_header= 13（采样 1 次）

## 证据路径

- 逐用例结果：`cases/`
- 消息轨迹：`messages/`

> 随机/概率效果不靠 `--repeat` 换抽样：标了 `deterministic` 的用例每轮被平台用同一个
> seed 重置（`astrbot_plugin_testplatform/cases/runner.py`），重跑 N 遍得到的是同一随机序列；没标的用例每轮继续
> 消费全局流，换得了抽样但不可复现。要拿真实样本请换种子/换用例，或在 `tests/` 补
> 单测（见 README「概率效果口径」）。
> 上面的人数/次数计数只证存在性：同一个 combine 窗口的 fullText 会出现在多个
> 步骤的 actual 与逐条消息里，计数因而被放大；判定请回看 `messages/` 原文。
> `最长回合` 是该用例单场战报的最大回合数，用于判断触发率断言的前提是否成立
> （见 README「概率效果口径」）。
