# data/narrative_defaults/combat.py
"""Default narrative copy for the combat domain (section ``combat``).

Every default text is copied verbatim from the original hard-coded strings in
``managers/combat_manager.py`` (``_resolve_attack`` sentence patterns,
``_try_survive`` cheat-death line, skill-trigger/buff lines, the round header,
and the effect-handler log lines) — except the battle-frame and remaining-HP
scenes, whose copy was re-finalized by change ``combat-report-structure`` (see
the paragraph below).
Initial pools have length 1 (single-template str shape) so existing test
assertions on the exact wording keep passing.

Numeric/structural lines intentionally stay in code (design D6): the fighter
stat panel lines. The ``-- 第 N 回合 --`` round header and the dot-tick /
counter / heal / dot-attach / survive-grant / stack-cap-rejection log lines in
the effect handlers are covered too — they were externalized by the follow-up
change ``narrative-text-migration-leftovers`` (``round_header`` and the
``effect_*`` scenes below).

The five battle-frame scenes are **literary description lines only** since
change ``combat-report-structure`` (bd -r0a, design D1-D3): the ``☆━━━━ … ━━━━☆``
banners and the ``{name1} VS {name2}`` versus line are structural and now owned
by ``managers/combat_manager.py`` (module constants ``_BANNER_*`` /
``_VERSUS_LINE``); ``battle_vs`` is retired. The same change split ``remaining_hp``
into the two tier scenes (design D4) and retired the old key. All seven defaults
below are the copy rendered when the config pool is empty; the text is finalized
in design_docs/剧情/03-战斗说书人剧本.md「内嵌默认（池空回退）」and must keep the
same variable sets as ``SCENE_VARS`` (load-time validation, config_manager.py —
pool variants must also be a superset of those sets, or the importer skips the
whole scene and this default stays in charge).
"""

# Verbatim copy rules (design D5): emoji, full/half-width punctuation, and the
# half-width colons in the mechanical lines are part of the original text — do
# not "normalize" them.
SCENES: dict[str, object] = {
    # --- Battle frame (CombatEngine.resolve_combat) ---
    # Optional description line under the code-owned opening banner + versus
    # line. No interpolation variables (declared set is empty).
    "battle_opening": "杀气先到，人影随后。你握紧了兵刃站定——这一战，躲不过。",
    # Optional description line after the mutual-destruction banner.
    "battle_mutual_destruction": "最后一击同时落下——两道身影一齐倒地，谁也没能再站起来。",
    # Optional description line after the victory banner ({name} = winner).
    "battle_victory": "{name} 站到最后，兵器归鞘——这一战，胜了。",
    # Optional description line after the stalemate (action limit) banner.
    "battle_draw_stalemate": "斗到招式都用老了，谁也压不住谁，两边各自收手——僵持不下，算作平局。",
    # Optional description line after the fallback draw banner (defensive
    # branch, not reachable in practice).
    "battle_draw": "你来我往，谁也没占到便宜——这一场，平分秋色。",
    # Round header emitted every two actions (resolve_combat).
    "round_header": "-- 第 {rounds} 回合 --",
    # --- Attack chain (CombatEngine._resolve_attack) ---
    # Stunned attacker loses the action.
    "stun_skip": "{name} 处于眩晕状态，无法出手！",
    # Defender dodges the attack entirely.
    "dodge": "{defender_name} 身形一闪，躲过了 {attacker_name} 的攻击！",
    # Defender blocks (damage halved later in the chain).
    "block": "{defender_name} 举盾格挡，化解了部分攻势！",
    # Crit roll succeeds (announced before trigger skills).
    "crit_notice": "{attacker_name} 目光如电，寻得破绽！",
    # Ultimate cast line.
    "ultimate_cast": "{attacker_name} 施展大招【{ult_name}】，天地变色！",
    # Damage settlement, crit hit.
    "damage_crit": "{attacker_name} 暴击！造成 {final_damage} 点伤害！",
    # Damage settlement, normal hit.
    "damage_normal": "{attacker_name} 发起攻击，造成 {final_damage} 点伤害",
    # Reflect: defender refunds part of the damage to the attacker.
    "reflect": "{defender_name} 反弹 {reflect_dmg} 点伤害！",
    # Lifesteal: attacker heals a fraction of the dealt damage.
    "lifesteal": "{attacker_name} 吸取 {heal} 气血！",
    # Tiered post-attack HP description lines (change combat-report-structure
    # D4): 残局档, ratio in (low, mid].
    "remaining_hp_mid": (
        "{defender_name} 气血还剩 {remaining_hp} 点，仍然站得稳，这一战还长。"
    ),
    # 濒死档, ratio in (0, low].
    "remaining_hp_low": (
        "{defender_name} 气血只剩 {remaining_hp} 点，一口气吊着，人还站着。"
    ),
    # --- Cheat death (CombatEngine._try_survive) ---
    "survive": "{name} 触发【免死】，于绝境中存活！",
    # --- Skill-trigger / buff lines ---
    # buff/debuff/fatigue status successfully attached (_attach_stat_status).
    "buff_applied": "{actor_name} 的【{effect_name}】作用于 {target_name}",
    # Status effect expired at round start (_tick_status_effects).
    "status_expired": "{name} 的【{effect_name}】效果消散",
    # round_start trigger skill granted a damage bonus
    # (_process_round_start_skills).
    "trigger_round_start_boost": "{name} 触发【{skill_name}】，下回合攻势更盛！",
    # on_attack/on_crit trigger skill granted a damage bonus
    # (_process_trigger_skills).
    "trigger_attack_boost": "{actor_name} 触发【{skill_name}】，攻势更盛！",
    # Stun trigger skill fired.
    "trigger_stun": (
        "{actor_name} 触发【{skill_name}】，{target_name} 被眩晕，下回合无法出手！"
    ),
    # damage_reduction trigger skill fired.
    "trigger_damage_reduction": "{actor_name} 触发【{skill_name}】，受到的伤害降低！",
    # --- Effect handler / status log lines ---
    # counter trigger effect: immediate retaliation damage (_handler_counter).
    "effect_counter": (
        "{actor_name} 触发【{skill_name}】反击，"
        "对 {target_name} 造成 {counter_dmg} 点伤害！"
    ),
    # heal trigger effect: restore HP (_handler_heal).
    "effect_heal": "{actor_name} 触发【{skill_name}】，恢复 {heal} 气血！",
    # dot trigger effect: attach a per-round damage status (_handler_dot).
    "effect_dot_attach": "{actor_name} 使【{skill_name}】附着于 {target_name}",
    # buff/debuff/fatigue rejected by the stack cap (_attach_stat_status).
    "effect_stack_cap_rejected": (
        "{actor_name} 的【{effect_name}】未生效：同类效果已达叠加上限（{stack_cap}）"
    ),
    # survive trigger effect: grant lethal-protection charges (_handler_survive).
    "effect_survive_grant": "{actor_name} 获得【{skill_name}】庇护！",
    # dot ticks at round start (_tick_status_effects).
    "effect_dot_tick": "{name} 受【{effect_name}】侵蚀，损失 {dot_dmg} 气血！",
}

# Declared interpolation variables per scene. Load-time contract validation
# rejects config scenes referencing anything outside these sets, so each set
# must exactly match the variables its render point in combat_manager.py
# passes to render_narrative.
SCENE_VARS: dict[str, set[str]] = {
    "battle_opening": set(),
    "battle_mutual_destruction": set(),
    "battle_victory": {"name"},
    "battle_draw_stalemate": set(),
    "battle_draw": set(),
    "round_header": {"rounds"},
    "stun_skip": {"name"},
    "dodge": {"defender_name", "attacker_name"},
    "block": {"defender_name"},
    "crit_notice": {"attacker_name"},
    "ultimate_cast": {"attacker_name", "ult_name"},
    "damage_crit": {"attacker_name", "final_damage"},
    "damage_normal": {"attacker_name", "final_damage"},
    "reflect": {"defender_name", "reflect_dmg"},
    "lifesteal": {"attacker_name", "heal"},
    "remaining_hp_mid": {"defender_name", "remaining_hp"},
    "remaining_hp_low": {"defender_name", "remaining_hp"},
    "survive": {"name"},
    "buff_applied": {"actor_name", "effect_name", "target_name"},
    "status_expired": {"name", "effect_name"},
    "trigger_round_start_boost": {"name", "skill_name"},
    "trigger_attack_boost": {"actor_name", "skill_name"},
    "trigger_stun": {"actor_name", "skill_name", "target_name"},
    "trigger_damage_reduction": {"actor_name", "skill_name"},
    "effect_counter": {"actor_name", "skill_name", "target_name", "counter_dmg"},
    "effect_heal": {"actor_name", "skill_name", "heal"},
    "effect_dot_attach": {"actor_name", "skill_name", "target_name"},
    "effect_stack_cap_rejected": {"actor_name", "effect_name", "stack_cap"},
    "effect_survive_grant": {"actor_name", "skill_name"},
    "effect_dot_tick": {"name", "effect_name", "dot_dmg"},
}
