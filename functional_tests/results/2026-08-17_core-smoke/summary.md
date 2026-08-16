# 功能测试结果：2026-08-17_core-smoke

- 导出时间：2026-08-17T06:43:37
- 运行记录数：7
- 通过：6
- 失败/错误：1
- 不稳定：0
- 跳过：0

## 通过用例

- bank-sect-smoke
- equipment-heart-weapon
- gm-basics
- player-lifecycle
- pve-smoke
- pvp-basic-duel

## 失败/错误用例

- pvp-basic-spar (run 31, failed)

## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- gm-basics: pierce= 6（采样 1 次）
- player-lifecycle: pierce= 7（采样 1 次）
- pvp-basic-duel: pierce= 27, reflect= 2（采样 1 次）
- pvp-basic-spar: pierce= 9（采样 1 次）

## 证据路径

- 逐用例结果：`cases/`
- 消息轨迹：`messages/`

> 随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度。

## 已知问题

- [astrbot_plugin_monixiuxian2_2-tbp] `handle_spar` 未给 `result` 赋值导致切磋命令 UnboundLocalError
  - 证据：`cases/pvp-basic-spar__run31.json` / `messages/pvp-basic-spar__run31.json`
  - `pvp-basic-spar` 为预期失败，用于回归该 Bug。
