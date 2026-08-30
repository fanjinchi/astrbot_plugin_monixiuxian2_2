# data/narrative_defaults/legacy_encounter.py
"""Default narrative copy for the legacy-encounter domain (``legacy_encounter``).

Single template cluster for the 传承之地 set piece: encounter scenes
(adventure/rift 偶遇制) and claim scenes (sect 领取制, including the
sect-specific mechanic line). Defaults are copied verbatim from the original
strings in ``managers/adventure_manager.py``, ``managers/rift_manager.py`` and
``managers/sect_manager.py``.

Each scenario splits into win/lose scenes because pool semantics are random
rotation, not outcome selection (same per-branch pattern as the breakthrough
domain). The two 偶遇制 sources differed by exactly one phrase — adventure said
「你偶遇一处传承之地」 where rift said 「你偶遇上古传承之地」; the cluster
converges on the rift wording (「上古传承之地」 matches the set-piece naming in
the sect claim copy). ``{instance_id}`` renders the legacy instance id (the
original f-strings used ``{instance.id}``; format_map variables carry plain
values, so the render points pass the id directly).
"""

SCENES: dict[str, object] = {
    # 偶遇制胜利（managers/adventure_manager.py / managers/rift_manager.py）。
    # 前缀 \n\n 属于原文案（结算消息内联追加），逐字保留。
    "encounter_win": (
        "\n\n🗿 你偶遇上古传承之地，战胜了守护者！\n{battle_msg}\n"
        "🌟 获得【{name}】#{instance_id}，发送「激活传承」可开始修炼解锁。"
    ),
    # 偶遇制失败。
    "encounter_lose": "\n\n🗿 你偶遇上古传承之地，但未能战胜守护者。\n{battle_msg}",
    # 领取制胜利（managers/sect_manager.py），含宗门专属机制行（不可夺取/离宗归还）。
    "claim_win": (
        "🗿 你战胜了守护者！\n{battle_msg}\n"
        "🌟 获得宗门传承【{name}】#{instance_id}！\n"
        "⚠️ 宗门传承不可被夺取，但离宗时将自动归还宗门。\n"
        "💡 发送「激活传承 {instance_id}」开始修炼解锁等阶奖励。"
    ),
    # 领取制失败（含名额规则说明；该行与上文构成完整叙事单元，非 D6 数值分解，
    # 随模板一并外移而非拆分留码）。
    "claim_lose": (
        "🗿 领取【{name}】需先战胜传承之地守护者。\n"
        "{battle_msg}\n"
        "此次未领取成功，不占用领取名额，可择日再试。"
    ),
}

SCENE_VARS: dict[str, set[str]] = {
    "encounter_win": {"battle_msg", "name", "instance_id"},
    "encounter_lose": {"battle_msg"},
    "claim_win": {"battle_msg", "name", "instance_id"},
    "claim_lose": {"name", "battle_msg"},
}
