# data/narrative_defaults/cultivation.py
"""Default narrative copy for the cultivation domain (section ``cultivation``).

Every default text is copied verbatim from the original hard-coded strings in
``handlers/player_handler.py`` (retreat start, retreat settlement skeleton,
retreat epiphany, impart-value settlement flavor, character creation
narrative, and re-cultivation farewell). Route-mechanic explanation lines
(numeric rules for 轮回/重修, attribute stat panels, and rule lists)
intentionally stay in code — see openspec externalize-narrative-texts
design D6.
"""

SCENES: dict[str, object] = {
    # 闭关开始: {end_cmd} is the command name constant (CMD_END_CULTIVATION),
    # passed in so the template never hard-codes the command string.
    "retreat_start": (
        "🧘 道友已进入闭关状态\n"
        "━━━━━━━━━━━━━━━\n"
        "闭关期间，你将与世隔绝，潜心修炼。\n"
        "💡 发送「{end_cmd}」结束闭关\n"
        "⏱️ 每分钟将获得修为，受灵根资质影响。"
    ),
    # 出关结算骨架: {gained_exp}/{current_exp} keep the original comma format
    # spec; {fairyland_line}/{exceed_msg} are pre-built optional lines that
    # default to "" (they contain numeric/mechanic text that stays in code).
    "retreat_settlement": (
        "🌟 道友出关成功！\n"
        "━━━━━━━━━━━━━━━\n"
        "⏱️ 闭关时长：{time_str}\n"
        "{fairyland_line}"
        "📈 获得修为：{gained_exp:,}{exceed_msg}\n"
        "💫 当前修为：{current_exp:,}\n"
        "━━━━━━━━━━━━━━━\n"
        "道友已回归红尘，可继续修行。"
    ),
    # 闭关悟道: the "未知" fallback for a missing skill name is resolved in
    # code before rendering.
    "retreat_epiphany": "🎁 闭关悟道，领悟功法【{skill_name}】！",
    # 传承值结算 flavor: hint shown when the player owns a legacy but none is
    # active. Leading "\n\n" preserved verbatim (it is appended to the
    # settlement message).
    "impart_value_inactive_hint": (
        "\n\n💡 你持有传承但未激活，本次闭关未累积传承值。\n"
        "使用「激活传承 <编号>」激活后再闭关。"
    ),
    # 角色创建-选择提示头部: the stat/rule blocks that follow are numeric
    # explanation text and stay in code (design D6).
    "creation_help_welcome": (
        "🌟 欢迎踏入修仙之路！\n━━━━━━━━━━━━━━━\n请选择你的修炼方式：\n\n"
    ),
    # 角色创建-欢迎词: {name} is the sender display name.
    "creation_welcome": "🎉 恭喜道友 {name} 踏上仙途！\n",
    # 角色创建-风险 flavor 句（结束于换行，后接代码内的分隔线）。
    "creation_warning": (
        "⚠️ 修仙有风险，突破需谨慎！\n"
        "突破失败或生命值归零会导致\n"
        "身死道消，所有数据清除！\n"
    ),
    # 弃道重修-告别词: the trailing numeric rule line "（7天内不可再次重修）"
    # and the sect-treasure reclaim line stay in code (design D6).
    "rebirth_farewell": (
        "💀 你选择了弃道重修，旧生一切化为尘埃。\n"
        "━━━━━━━━━━━━━━━\n"
        "可立即使用「我要修仙」重新踏上仙途。\n"
    ),
}

SCENE_VARS: dict[str, set[str]] = {
    "retreat_start": {"end_cmd"},
    "retreat_settlement": {
        "time_str",
        "fairyland_line",
        "gained_exp",
        "exceed_msg",
        "current_exp",
    },
    "retreat_epiphany": {"skill_name"},
    "impart_value_inactive_hint": set(),
    "creation_help_welcome": set(),
    "creation_welcome": {"name"},
    "creation_warning": set(),
    "rebirth_farewell": set(),
}
