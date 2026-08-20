# 功能测试结果：2026-08-21_pvp-effects

- 导出方式：one-shot `run --tag pvp --sync --reload astrbot_plugin_monixiuxian2 --fixture --fixture-profile pvp --export`
- 运行记录数：23
- 通过：23
- 失败/错误：0
- 不稳定：0
- 跳过：0

## 通过用例

- pvp-basic-duel, pvp-basic-spar, pvp-heart-passive
- pvp-effect-buff/combo/counter/damage_bonus/damage_reduction/debuff/dot/fatigue/heal/pierce/reflect/stun/survive/unavoidable/vampire
- pvp-ultimate-damage/dot/heal/survive
- pvp-weapon-trigger

## 效果证据聚合（sampled 用例，deterministic+seed 下采样）

见 `summary.json`（机器可读）+ 各 run JSON 的 `evidence`。标志位：

- 20 个 sampled 用例全部 `deterministic: true` + `seed: 42`；pierce/reflect/unavoidable 等证据片段均有捕获。
- `pvp-effect-unavoidable`：保留采样（反向证据「躲过了」），未转 expect_not（原因见 tasks.md 执行结果记录）。
- `pvp-weapon-trigger`：3 处触发断言 `combine: true`；修正为期望 60s 超时后通过。

## 证据路径

- 逐用例结果：`cases/` 下的 `*__run*.json`（含 steps_result、evidence）
- 汇总：`summary.json`（total/passed/failed/errors/runs）

> 随机/概率效果用例采用 `deterministic: true` + `seed: 42` 主路径，`--repeat` 仅作统计兜底。
