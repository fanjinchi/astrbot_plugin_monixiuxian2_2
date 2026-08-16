# 功能测试结果：2026-08-17_pvp-effects

- 导出时间：2026-08-17T07:07:03
- 运行记录数：63
- 通过：62
- 失败/错误：1
- 不稳定：0
- 跳过：0

## 通过用例

- pvp-basic-duel
- pvp-effect-buff
- pvp-effect-combo
- pvp-effect-counter
- pvp-effect-damage_bonus
- pvp-effect-damage_reduction
- pvp-effect-debuff
- pvp-effect-dot
- pvp-effect-fatigue
- pvp-effect-heal
- pvp-effect-pierce
- pvp-effect-reflect
- pvp-effect-stun
- pvp-effect-survive
- pvp-effect-unavoidable
- pvp-effect-vampire
- pvp-heart-passive
- pvp-ultimate-damage
- pvp-ultimate-dot
- pvp-ultimate-heal
- pvp-ultimate-survive
- pvp-weapon-trigger

## 失败/错误用例

- pvp-basic-spar (run 31, failed)

## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- pvp-basic-duel: pierce= 27, reflect= 2（采样 1 次）
- pvp-basic-spar: pierce= 9（采样 1 次）
- pvp-effect-buff: buff= 122, debuff= 122, unavoidable= 20, pierce= 491, reflect= 114, fatigue= 122（采样 3 次）
- pvp-effect-combo: damage_bonus= 38, combo= 38, counter= 38, unavoidable= 40, pierce= 523, reflect= 74（采样 3 次）
- pvp-effect-counter: counter= 60, unavoidable= 36, pierce= 561, reflect= 124（采样 3 次）
- pvp-effect-damage_bonus: damage_bonus= 40, combo= 40, counter= 40, unavoidable= 24, pierce= 505, reflect= 68（采样 3 次）
- pvp-effect-damage_reduction: counter= 44, damage_reduction= 44, unavoidable= 38, pierce= 605, reflect= 74（采样 3 次）
- pvp-effect-debuff: buff= 136, debuff= 136, unavoidable= 18, pierce= 523, reflect= 82, fatigue= 136（采样 3 次）
- pvp-effect-dot: heal= 130, vampire= 130, dot= 260, buff= 32, debuff= 32, unavoidable= 42, pierce= 521, reflect= 64, fatigue= 32（采样 3 次）
- pvp-effect-fatigue: buff= 122, debuff= 122, unavoidable= 26, pierce= 527, reflect= 96, fatigue= 122（采样 3 次）
- pvp-effect-heal: counter= 50, heal= 100, vampire= 50, dot= 50, unavoidable= 24, pierce= 533, reflect= 72（采样 3 次）
- pvp-effect-pierce: unavoidable= 54, pierce= 685, reflect= 96（采样 3 次）
- pvp-effect-reflect: unavoidable= 12, pierce= 433, reflect= 380（采样 3 次）
- pvp-effect-stun: stun= 12, counter= 12, unavoidable= 28, pierce= 535, reflect= 62（采样 3 次）
- pvp-effect-survive: pierce= 141, reflect= 20, counter= 4, survive= 8, ultimate_damage= 8, ultimate_heal= 8, ultimate_dot= 8, ultimate_survive= 8, unavoidable= 4（采样 3 次）
- pvp-effect-unavoidable: unavoidable= 102, pierce= 653, reflect= 82（采样 3 次）
- pvp-effect-vampire: heal= 40, vampire= 80, dot= 40, unavoidable= 36, pierce= 575, reflect= 78（采样 3 次）
- pvp-heart-passive: unavoidable= 7, pierce= 205, reflect= 49（采样 1 次）
- pvp-ultimate-damage: unavoidable= 48, pierce= 793, reflect= 144, ultimate_damage= 12, ultimate_heal= 12, ultimate_dot= 12（采样 3 次）
- pvp-ultimate-dot: heal= 24, vampire= 24, dot= 48, buff= 6, debuff= 6, unavoidable= 60, pierce= 947, reflect= 164, fatigue= 6, ultimate_damage= 12, ultimate_heal= 12, ultimate_dot= 12（采样 3 次）
- pvp-ultimate-heal: counter= 6, heal= 12, vampire= 6, dot= 6, pierce= 381, reflect= 58, ultimate_damage= 12, ultimate_heal= 12, ultimate_dot= 12, unavoidable= 4（采样 3 次）
- pvp-ultimate-survive: counter= 6, pierce= 135, reflect= 14, survive= 12, ultimate_damage= 12, ultimate_heal= 12, ultimate_dot= 12, ultimate_survive= 12, unavoidable= 2（采样 3 次）
- pvp-weapon-trigger: damage_bonus= 49, combo= 49, counter= 49, unavoidable= 57, pierce= 629, reflect= 74（采样 3 次）

## 证据路径

- 逐用例结果：`cases/`
- 消息轨迹：`messages/`

> 随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度。

## 已知问题

- [astrbot_plugin_monixiuxian2_2-tbp] `handle_spar` 未给 `result` 赋值导致切磋命令 UnboundLocalError
  - 证据：`cases/pvp-basic-spar__run31.json` / `messages/pvp-basic-spar__run31.json`
  - `pvp-basic-spar` 为预期失败，用于回归该 Bug。
- [astrbot_plugin_monixiuxian2_2-7px] GM `给予装备` 未识别 `heart_methods`，心法装配依赖 fixture 预置。
- [astrbot_plugin_monixiuxian2_2-qv9] `set_user_busy` 仅 UPDATE 不 INSERT，fixture 已预插 `user_cd` 行绕行。
- 平台偶发：连续运行同一用例时，第三轮首条消息可能被 AstrBot 事件队列延迟约 50s；`pvp-weapon-trigger` 已在用例末尾加入 60s 冲刷等待。
