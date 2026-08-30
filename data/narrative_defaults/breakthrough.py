# data/narrative_defaults/breakthrough.py
"""Default narrative copy for the breakthrough domain (section ``breakthrough``).

Every default text is copied verbatim from the original hard-coded strings in
``core/breakthrough_manager.py`` (success / failure-revive-pill / death /
survive / lose-streak guarantee / skill-comprehension flavor / lose-streak
reward line). Numeric explanation text (``rate_info``) intentionally stays in
code and is interpolated here as the ``{rate_info}`` variable — see openspec
externalize-narrative-texts design D6. Initial pools have length 1 so existing
test assertions on the exact wording keep passing.
"""

SCENES: dict[str, object] = {
    # Breakthrough success panel (core/breakthrough_manager.py execute_breakthrough).
    # {streak_bonus_msg} carries the optional lose-streak reward line (already
    # rendered from the ``lose_streak_reward`` scene, empty when streak < 3).
    "success": (
        "✨ 突破成功！✨{streak_bonus_msg}\n"
        "━━━━━━━━━━━━━━━\n"
        "{rate_info}\n"
        "━━━━━━━━━━━━━━━\n"
        "恭喜你从【{current_level_name}】突破至【{next_level_name}】！\n"
        "\n【属性增长】\n"
        "气血 +{hp_growth}\n"
        "伤害 +{damage_growth}\n"
        "身法 +{agility_growth}\n"
        "迅捷 +{speed_growth}\n"
        "\n【当前属性】\n"
        "伤害：{damage}\n"
        "身法：{agility}\n"
        "迅捷：{speed}\n"
        "气血：{hp}\n"
        "护甲：{armor_value}"
    ),
    # Lose-streak reward line appended to the success header when the player
    # had >= 3 consecutive failures before this success.
    "lose_streak_reward": "\n💪 苦尽甘来，天道不负有心人！",
    # Skill-comprehension flavor lines (success roll / fail soft-pity roll /
    # universal-pool fallback shared by both outcomes).
    "comprehend_success": "🎁 福至心灵，领悟功法【{name}】！",
    "comprehend_fail": "🎁 破而后立，领悟功法【{name}】！",
    "comprehend_universal": "🎁 破境感悟，领悟通用功法【{name}】！",
    # Failure with revive pill (回生丹 resurrection branch).
    "revive": (
        "💀 突破失败，走火入魔！💀\n"
        "━━━━━━━━━━━━━━━\n"
        "{rate_info}\n"
        "━━━━━━━━━━━━━━━\n"
        "你在突破【{next_level_name}】时走火入魔...\n"
        "\n"
        "⚡ 回生丹效果触发！⚡\n"
        "━━━━━━━━━━━━━━━\n"
        "🌟 你涅槃重生了！\n"
        "⚠️ 但所有属性降低到之前的一半\n"
        "💊 回生丹效果已消耗\n"
        "━━━━━━━━━━━━━━━\n"
        "请继续修炼，重回巅峰！"
    ),
    # Failure with death (身死道消 branch).
    "death": (
        "💀 突破失败，走火入魔！💀\n"
        "━━━━━━━━━━━━━━━\n"
        "{rate_info}\n"
        "━━━━━━━━━━━━━━━\n"
        "你在突破【{next_level_name}】时走火入魔，身死道消...\n"
        "所有修为和装备化为虚无\n"
        "若想重新修仙，请使用'我要修仙'命令重新开始"
    ),
    # Lose-streak pity hint appended to the survive panel. {next_bonus} keeps
    # the original ``:.0%`` format spec from the f-string.
    "pity_hint": (
        "\n连败 {streak} 次，天道酬勤："
        "下次成功率 +{next_bonus:.0%}"
        "（再败 {remaining} 次必成）"
    ),
    # Failure without death (保命 branch). {pity_msg} carries the rendered
    # ``pity_hint`` line.
    "survive": (
        "❌ 突破失败 ❌\n"
        "━━━━━━━━━━━━━━━\n"
        "{rate_info}\n"
        "━━━━━━━━━━━━━━━\n"
        "突破【{next_level_name}】失败，但幸运地保住了性命\n"
        "修为受损，损失了 {exp_penalty} 点修为\n"
        "当前修为：{experience}"
        "{pity_msg}"
    ),
}

SCENE_VARS: dict[str, set[str]] = {
    "success": {
        "streak_bonus_msg",
        "rate_info",
        "current_level_name",
        "next_level_name",
        "hp_growth",
        "damage_growth",
        "agility_growth",
        "speed_growth",
        "damage",
        "agility",
        "speed",
        "hp",
        "armor_value",
    },
    "lose_streak_reward": set(),
    "comprehend_success": {"name"},
    "comprehend_fail": {"name"},
    "comprehend_universal": {"name"},
    "revive": {"rate_info", "next_level_name"},
    "death": {"rate_info", "next_level_name"},
    "pity_hint": {"streak", "next_bonus", "remaining"},
    "survive": {
        "rate_info",
        "next_level_name",
        "exp_penalty",
        "experience",
        "pity_msg",
    },
}
