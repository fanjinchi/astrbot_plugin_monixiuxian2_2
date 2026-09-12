# 功能测试结果：2026-09-12_pvp-duel-anchor-tighten

- 导出时间：2026-09-12T19:45:26
- 运行记录数：1
- 通过：1
- 失败/错误：0
- 不稳定：0
- 跳过：0

## 通过用例

- pvp-basic-duel

## 失败/错误用例


## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- pvp-basic-duel: round_header= 160, dodge_prose= 5（采样 1 次，最长回合=16）

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
