# data/narrative_defaults/fortune.py
"""Default narrative copy for the breakthrough-fortune domain (section ``fortune``).

Every default text is copied verbatim from the original hard-coded strings in
``core/breakthrough_fortune.py`` (the three fortune lines). ``{items}`` in the
pill drop carries the pre-joined "【名称】x数量" list (顿号分隔), matching the
original string concatenation. Initial pools have length 1 so existing test
assertions on the exact wording keep passing.
"""

SCENES: dict[str, object] = {
    # Weapon drop (core/breakthrough_fortune.py roll_breakthrough_fortune).
    "weapon_drop": "🎁 机缘天降，获得武器【{name}】（{rank}）！",
    # Heart-method drop.
    "heart_method_drop": "🎁 福至心灵，获得心法【{name}】（{rank}）！",
    # Pill drop; {items} is the 顿号-joined "【name】xcount" list.
    "pill_drop": "🎁 仙缘际会，获得丹药{items}！",
}

SCENE_VARS: dict[str, set[str]] = {
    "weapon_drop": {"name", "rank"},
    "heart_method_drop": {"name", "rank"},
    "pill_drop": {"items"},
}
