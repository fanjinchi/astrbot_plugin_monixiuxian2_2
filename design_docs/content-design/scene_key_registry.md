# Scene Key 登记表（tasks 1.4：scene key ↔ 载体位置 ↔ 插值变量白名单）

> 用途：copy_variants.csv 写作/灌入前先对照本表；lint_narrative.py 按本表（运行时事实源）
> 校验 text 列 `{var}` 白名单。四宗（金刚寺/天机阁/万毒门/血魔宗）事件复用同源 key，
> config 立组随 bd `n6o`（当前未登记）。

## narrative_config.json 场景（externalize-narrative-texts 已落地）

- `breakthrough.success` — 变量白名单: ['agility', 'agility_growth', 'armor_value', 'current_level_name', 'damage', 'damage_growth', 'hp', 'hp_growth', 'next_level_name', 'rate_info', 'speed', 'speed_growth', 'streak_bonus_msg']
- `breakthrough.lose_streak_reward` — 变量白名单: （无）
- `breakthrough.comprehend_success` — 变量白名单: ['name']
- `breakthrough.comprehend_fail` — 变量白名单: ['name']
- `breakthrough.comprehend_universal` — 变量白名单: ['name']
- `breakthrough.revive` — 变量白名单: ['next_level_name', 'rate_info']
- `breakthrough.death` — 变量白名单: ['next_level_name', 'rate_info']
- `breakthrough.pity_hint` — 变量白名单: ['remaining', 'streak']
- `breakthrough.survive` — 变量白名单: ['exp_penalty', 'experience', 'next_level_name', 'pity_msg', 'rate_info']
- `combat.battle_opening` — 变量白名单: （无）
- `combat.battle_vs` — 变量白名单: ['name1', 'name2']
- `combat.battle_mutual_destruction` — 变量白名单: （无）
- `combat.battle_victory` — 变量白名单: ['name']
- `combat.battle_draw_stalemate` — 变量白名单: （无）
- `combat.battle_draw` — 变量白名单: （无）
- `combat.stun_skip` — 变量白名单: ['name']
- `combat.dodge` — 变量白名单: ['attacker_name', 'defender_name']
- `combat.block` — 变量白名单: ['defender_name']
- `combat.crit_notice` — 变量白名单: ['attacker_name']
- `combat.ultimate_cast` — 变量白名单: ['attacker_name', 'ult_name']
- `combat.damage_crit` — 变量白名单: ['attacker_name', 'final_damage']
- `combat.damage_normal` — 变量白名单: ['attacker_name', 'final_damage']
- `combat.reflect` — 变量白名单: ['defender_name', 'reflect_dmg']
- `combat.lifesteal` — 变量白名单: ['attacker_name', 'heal']
- `combat.remaining_hp` — 变量白名单: ['defender_name', 'remaining_hp']
- `combat.survive` — 变量白名单: ['name']
- `combat.buff_applied` — 变量白名单: ['actor_name', 'effect_name', 'target_name']
- `combat.status_expired` — 变量白名单: ['effect_name', 'name']
- `combat.trigger_round_start_boost` — 变量白名单: ['name', 'skill_name']
- `combat.trigger_attack_boost` — 变量白名单: ['actor_name', 'skill_name']
- `combat.trigger_stun` — 变量白名单: ['actor_name', 'skill_name', 'target_name']
- `combat.trigger_damage_reduction` — 变量白名单: ['actor_name', 'skill_name']
- `cultivation.retreat_start` — 变量白名单: ['end_cmd']
- `cultivation.retreat_settlement` — 变量白名单: ['exceed_msg', 'fairyland_line', 'time_str']
- `cultivation.retreat_epiphany` — 变量白名单: ['skill_name']
- `cultivation.impart_value_inactive_hint` — 变量白名单: （无）
- `cultivation.creation_help_welcome` — 变量白名单: （无）
- `cultivation.creation_welcome` — 变量白名单: ['name']
- `cultivation.creation_warning` — 变量白名单: （无）
- `cultivation.rebirth_farewell` — 变量白名单: （无）
- `fortune.weapon_drop` — 变量白名单: ['name', 'rank']
- `fortune.heart_method_drop` — 变量白名单: ['name', 'rank']
- `fortune.pill_drop` — 变量白名单: ['items']

## narrative_config.json 遗留簇（legacy_encounter，传承之地；externalize 落地时新增）

- `legacy_encounter.encounter_win` — 变量白名单: ['battle_msg', 'instance_id', 'name']
- `legacy_encounter.encounter_lose` — 变量白名单: ['battle_msg']
- `legacy_encounter.claim_win` — 变量白名单: ['battle_msg', 'instance_id', 'name']
- `legacy_encounter.claim_lose` — 变量白名单: ['battle_msg', 'name']

## adventure_config.json 事件（event_groups）

- 2026-08-30 externalize 落地：事件条目支持可选 `tags`/`desc_variants` 桶（schema 扩展，运行时空桶回落 `desc`）；**内容桶填充属本 change（season-1-tier1-copywriting）导入阶段产物，由用户侧发起导入任务**

- `adventure_event.herb_bloom`（组 safe）— 变量白名单: （无，静态文本）
- `adventure_event.travel_insight`（组 safe）— 变量白名单: （无，静态文本）
- `adventure_event.ally_help`（组 safe）— 变量白名单: （无，静态文本）
- `adventure_event.steady_path`（组 standard）— 变量白名单: （无，静态文本）
- `adventure_event.beast_skirmish`（组 standard）— 变量白名单: （无，静态文本）
- `adventure_event.secret_cache`（组 standard）— 变量白名单: （无，静态文本）
- `adventure_event.blood_battle`（组 risky）— 变量白名单: （无，静态文本）
- `adventure_event.ancient_trial`（组 risky）— 变量白名单: （无，静态文本）
- `adventure_event.trade_windfall`（组 risky）— 变量白名单: （无，静态文本）
- `adventure_event.ambush_fail`（组 disaster）— 变量白名单: （无，静态文本）
- `adventure_event.lost_in_fog`（组 disaster）— 变量白名单: （无，静态文本）
- `adventure_event.elder_guidance`（组 sect_qingyun）— 变量白名单: （无，静态文本）
- `adventure_event.sect_errand`（组 sect_qingyun）— 变量白名单: （无，静态文本）
- `adventure_event.sect_duel`（组 sect_qingyun）— 变量白名单: （无，静态文本）；2026-08-29 扩类，adventure_config.json 尚未落地（config 立组随 bd n6o），lint 当前按未知 scene WARN 提示
- `adventure_event.sect_trial`（组 sect_qingyun）— 变量白名单: （无，静态文本）；同上，config 未落地前恒 WARN

事件 key 全集：15 基础 key（11 散修 + 青云门 4: elder_guidance/sect_errand/sect_duel/sect_trial）；四宗 4 组复用同源 key（组属 sect_jingang/sect_tianji/sect_wandu/sect_xuemo，待 bd n6o 立组）。