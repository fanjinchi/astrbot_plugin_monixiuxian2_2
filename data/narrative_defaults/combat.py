# data/narrative_defaults/combat.py
"""Default narrative copy for the combat domain (section ``combat``).

Every default text is copied verbatim from the original hard-coded strings in
``managers/combat_manager.py`` (``_resolve_attack`` sentence patterns,
``_try_survive`` cheat-death line, battle frame opening/result closers, and
skill-trigger/buff lines). Initial pools have length 1 (single-template str
shape) so existing test assertions on the exact wording keep passing.

Numeric/structural lines intentionally stay in code (design D6): the fighter
stat panel lines, the ``-- 第 N 回合 --`` round header, and the dot-tick /
counter / heal / dot-attach / survive-grant / stack-cap-rejection log lines in
the effect handlers are outside this change's scope.
"""

# Verbatim copy rules (design D5): emoji, full/half-width punctuation, and the
# half-width colon in ``剩余气血:`` are part of the original text — do not
# "normalize" them.
SCENES: dict[str, object] = {
    # --- Battle frame (CombatEngine.resolve_combat) ---
    # Opening header of every battle report.
    "battle_opening": "☆━━━━ 战斗开始 ━━━━☆",
    # Versus line right below the opening header.
    "battle_vs": "{name1} VS {name2}",
    # Closer when both fighters die in the same round.
    "battle_mutual_destruction": "☆━━━━ 同归于尽！平局！━━━━☆",
    # Closer when one fighter wins.
    "battle_victory": "☆━━━━ {name} 胜利！━━━━☆",
    # Closer when the action limit is reached with both fighters alive.
    "battle_draw_stalemate": "☆━━━━ 战斗胶着，双方罢手，平局！━━━━☆",
    # Fallback draw closer (defensive branch, not reachable in practice).
    "battle_draw": "☆━━━━ 平局！━━━━☆",
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
    # Post-attack HP summary line.
    "remaining_hp": "{defender_name} 剩余气血: {remaining_hp}",
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
}

# Declared interpolation variables per scene. Load-time contract validation
# rejects config scenes referencing anything outside these sets, so each set
# must exactly match the variables its render point in combat_manager.py
# passes to render_narrative.
SCENE_VARS: dict[str, set[str]] = {
    "battle_opening": set(),
    "battle_vs": {"name1", "name2"},
    "battle_mutual_destruction": set(),
    "battle_victory": {"name"},
    "battle_draw_stalemate": set(),
    "battle_draw": set(),
    "stun_skip": {"name"},
    "dodge": {"defender_name", "attacker_name"},
    "block": {"defender_name"},
    "crit_notice": {"attacker_name"},
    "ultimate_cast": {"attacker_name", "ult_name"},
    "damage_crit": {"attacker_name", "final_damage"},
    "damage_normal": {"attacker_name", "final_damage"},
    "reflect": {"defender_name", "reflect_dmg"},
    "lifesteal": {"attacker_name", "heal"},
    "remaining_hp": {"defender_name", "remaining_hp"},
    "survive": {"name"},
    "buff_applied": {"actor_name", "effect_name", "target_name"},
    "status_expired": {"name", "effect_name"},
    "trigger_round_start_boost": {"name", "skill_name"},
    "trigger_attack_boost": {"actor_name", "skill_name"},
    "trigger_stun": {"actor_name", "skill_name", "target_name"},
    "trigger_damage_reduction": {"actor_name", "skill_name"},
}
