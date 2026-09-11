# 功能测试结果：2026-09-11_flavor-copy-webtest

- 导出时间：2026-09-11T20:53:13
- 运行记录数：28
- 通过：28
- 失败/错误：0
- 不稳定：0
- 跳过：0

## 通过用例

- breakthrough-fail-pity
- breakthrough-guarantee
- gm-time-tools
- legacy-basic
- player-lifecycle
- pvp-basic-duel
- pvp-basic-spar
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


## 不稳定用例


## 跳过用例


## 效果证据聚合（抽样）

- breakthrough-fail-pity: pity_streak_bonus= 3, pity_hint_prose= 7（采样 1 次）
- breakthrough-guarantee: pity_guarantee= 3, streak_reward_prose= 3, fortune_drop_prose= 3（采样 1 次）
- pvp-basic-duel: round_header= 96, dodge_prose= 6（采样 1 次，最长回合=16）
- pvp-basic-spar: round_header= 18（采样 1 次，最长回合=3）
- pvp-effect-buff: tr_ningshen_xurui= 48, round_header= 432, dodge_prose= 18, expire_prose= 24（采样 1 次，最长回合=72）
- pvp-effect-combo: tr_jingfeng_lianji= 24, round_header= 402, dodge_prose= 18（采样 1 次，最长回合=67）
- pvp-effect-counter: tr_yi_ya_huan_ya= 31, counter_line= 27, round_header= 432, dodge_prose= 18（采样 1 次，最长回合=72）
- pvp-effect-damage_bonus: tr_qixi_liuzhuan= 24, round_header= 420, dodge_prose= 18（采样 1 次，最长回合=70）
- pvp-effect-damage_reduction: tr_jingang_huti= 36, round_header= 456, dodge_prose= 18（采样 1 次，最长回合=76）
- pvp-effect-debuff: tr_lingshe_fu= 60, round_header= 432, dodge_prose= 18, expire_prose= 30（采样 1 次，最长回合=72）
- pvp-effect-dot: tr_shi_gu= 210, dot_tick= 246, heal_line= 123, round_header= 402, dodge_prose= 18, expire_prose= 36（采样 1 次，最长回合=67）
- pvp-effect-fatigue: tr_ran_xue= 48, round_header= 438, dodge_prose= 18, expire_prose= 24（采样 1 次，最长回合=73）
- pvp-effect-heal: tr_hui_chun_tuna= 24, dot_tick= 24, heal_line= 48, round_header= 432, dodge_prose= 18（采样 1 次，最长回合=72）
- pvp-effect-pierce: round_header= 456, dodge_prose= 18（采样 1 次，最长回合=76）
- pvp-effect-reflect: round_header= 432, reflect_prose= 135, dodge_prose= 18（采样 1 次，最长回合=72）
- pvp-effect-stun: tr_zhenshan_yiji= 3, round_header= 420, dodge_prose= 15（采样 1 次，最长回合=70）
- pvp-effect-survive: tr_niepan_zhongsheng= 6, survive_line= 3, round_header= 198, dodge_prose= 9（采样 1 次，最长回合=33）
- pvp-effect-unavoidable: round_header= 600, dodge_prose= 99（采样 1 次，最长回合=100）
- pvp-effect-vampire: lifesteal_prose= 30, round_header= 432, dodge_prose= 18（采样 1 次，最长回合=72）
- pvp-heart-passive: round_header= 402, dodge_prose= 16（采样 1 次，最长回合=24）
- pvp-ultimate-damage: ult_wanjian_guizong= 7, round_header= 312, dodge_prose= 12（采样 1 次，最长回合=52）
- pvp-ultimate-dot: ult_jiuyou_shihun= 21, dot_tick= 24, heal_line= 12, round_header= 540, dodge_prose= 27, expire_prose= 3（采样 1 次，最长回合=90）
- pvp-ultimate-heal: ult_huitian_shengshou= 10, dot_tick= 3, heal_line= 6, round_header= 402, dodge_prose= 21（采样 1 次，最长回合=67）
- pvp-ultimate-survive: tr_niepan_zhongsheng= 6, survive_line= 3, round_header= 198, dodge_prose= 9（采样 1 次，最长回合=33）
- pvp-weapon-trigger: wp_liekong_zhan= 305, wp_zhenhun_chui= 16, wp_xurui_shi= 27, round_header= 4400, dodge_prose= 186（采样 1 次，最长回合=100）

## 证据路径

- 逐用例结果：`cases/`
- 消息轨迹：`messages/`

> 随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度。
> 上面的人数/次数计数只证存在性：同一个 combine 窗口的 fullText 会出现在多个
> 步骤的 actual 与逐条消息里，计数因而被放大；判定请回看 `messages/` 原文。
> `最长回合` 是该用例单场战报的最大回合数，用于判断触发率断言的前提是否成立
> （见 README「概率效果口径」）。
