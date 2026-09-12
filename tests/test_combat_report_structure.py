"""战斗战报结构行的契约测试（change combat-report-structure）。

覆盖两组行为：

- 结构行代码所有（design D1/D2）：五条横幅与对阵行是 ``combat_manager`` 的模块
  常量，恒定在场；开局拼装顺序为「横幅 → 结构对阵行 → 描述行 → 双面板」，结局
  为「结局横幅 → 描述行」；描述行场景与内嵌默认双缺失时只出横幅、不报错。
- 剩余气血行阈值分档（design D4）：按 ``hp / max(1, max_hp)`` 分
  「不出行 / remaining_hp_mid / remaining_hp_low」三态，千分位由代码渲染。

用 ``tests/helpers.py::load_module`` 绕开 ``handlers``/``managers`` 的
``__init__`` 链（与其余战斗测试同口径）。
"""

import ast
from pathlib import Path

import pytest

from tests.helpers import load_module, load_package_module

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
COMBAT_MANAGER = PLUGIN_ROOT / "managers" / "combat_manager.py"

_mod = load_module("combat_manager_report", "managers/combat_manager.py")
CombatEngine = _mod.CombatEngine
FighterState = _mod.FighterState
# Loaded under a synthetic name: the fragment is pure data (no relative imports),
# and a plain ``load_module`` would need the package tree.
_combat_defaults = load_package_module(
    "data/narrative_defaults/combat.py", "combat_defaults_slice"
)


class _FakeConfigManager:
    """Config manager stub.

    ``narrative_config`` is only set when a test drives the config-pool path;
    without the attribute ``render_narrative`` falls back to the embedded
    defaults (same shape as ``tests/test_combat_engine.py``'s fake).
    """

    def __init__(self, game_config=None, narrative_config=None):
        self.game_config = game_config or {}
        self.items_data = {}
        self.weapons_data = {}
        self.heart_methods_data = {}
        if narrative_config is not None:
            self.narrative_config = narrative_config


def make_engine(game_config=None, narrative_config=None):
    """Build a CombatEngine over the stub config manager."""
    return CombatEngine(_FakeConfigManager(game_config, narrative_config))


def make_fighter(name, hp, damage, agility, speed):
    """Build a bare FighterState (max_hp equals hp unless a test overrides it).

    Armor is 0 so damage settles at the raw value (``_apply_armor_and_reduction``
    leaves it untouched).
    """
    return FighterState(
        user_id=name,
        name=name,
        hp=hp,
        max_hp=hp,
        damage=damage,
        agility=agility,
        speed=speed,
        armor_value=0,
    )


def _resolve_one_attack(engine, defender, damage, monkeypatch):
    """Run one attack whose outcome the test fully controls; return its log lines.

    Dodge/block/crit are the three random gates in ``_resolve_attack``: the
    defender's agility is 0 (dodge rate 0), ``_calc_block_rate`` /
    ``_calc_damage`` are stubbed and the attacker's crit rate is 0, so the
    defender loses exactly ``damage`` HP and the four tier boundaries can be
    constructed exactly instead of being sampled.
    """
    monkeypatch.setattr(engine, "_calc_damage", lambda *args, **kwargs: damage)
    monkeypatch.setattr(engine, "_calc_block_rate", lambda defender_arg: 0.0)
    attacker = make_fighter("攻方", 100000, 0, 0, 10)
    attacker.crit_rate = 0.0
    log: list[str] = []
    engine._resolve_attack(attacker, defender, 0.5, 1.5, log, round_no=1)
    return log


def _tier_of(log: list[str], name: str) -> str | None:
    """Classify the remaining-HP line as "mid" / "low" / None (not emitted).

    The two embedded defaults differ in one character (``气血还剩`` vs
    ``气血只剩``), which keeps this classifier independent of pool wording.
    """
    for entry in log:
        if entry.startswith(f"{name} 气血还剩 "):
            return "mid"
        if entry.startswith(f"{name} 气血只剩 "):
            return "low"
    return None


# ------------------------------------------------------------------
# D1: structural line constants
# ------------------------------------------------------------------


def test_structural_constants_are_verbatim():
    """Banners and the versus line keep the original bytes (bd -r0a 复原）。"""
    assert _mod._BANNER_OPENING == "☆━━━━ 战斗开始 ━━━━☆"
    assert _mod._BANNER_VICTORY.format(name="甲") == "☆━━━━ 甲 胜利！━━━━☆"
    assert _mod._BANNER_DRAW == "☆━━━━ 平局！━━━━☆"
    assert _mod._BANNER_DRAW_STALEMATE == "☆━━━━ 战斗胶着，双方罢手，平局！━━━━☆"
    assert _mod._BANNER_MUTUAL_DESTRUCTION == "☆━━━━ 同归于尽！平局！━━━━☆"
    assert _mod._VERSUS_LINE == "{name1} VS {name2}"
    # half-width VS + one space on each side, verbatim
    assert (
        _mod._VERSUS_LINE.format(name1="测试玩家1", name2="测试玩家2")
        == "测试玩家1 VS 测试玩家2"
    )


# ------------------------------------------------------------------
# D2: assembly order and always-present structural lines
# ------------------------------------------------------------------


def test_opening_block_order_is_banner_versus_flavor_panels():
    """开局：横幅 → 对战行 → 描述行 → 双面板 → 空行（merge_count=1 → 每行一 chunk）。"""
    engine = make_engine({"skill_system": {"battle_report_merge_count": 1}})
    fighter1 = make_fighter("测试玩家1", 100000, 1, 0, 10)
    fighter2 = make_fighter("测试玩家2", 2, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.combat_log[0] == _mod._BANNER_OPENING
    assert result.combat_log[1] == "测试玩家1 VS 测试玩家2"
    # 内嵌默认描述行（config 池为空时的回退句）
    assert (
        result.combat_log[2]
        == "杀气先到，人影随后。你握紧了兵刃站定——这一战，躲不过。"
    )
    assert result.combat_log[3].startswith("测试玩家1：气血 100000/100000")
    assert result.combat_log[4].startswith("测试玩家2：气血 2/2")
    assert result.combat_log[5] == ""


def test_victory_banner_is_followed_by_its_description_line():
    """结局：结局横幅 → 描述行直接相邻（胜者名由代码插值）。"""
    engine = make_engine({"skill_system": {"battle_report_merge_count": 1}})
    fighter1 = make_fighter("测试玩家1", 100000, 1, 0, 10)
    fighter2 = make_fighter("测试玩家2", 2, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    banner = result.combat_log.index("☆━━━━ 测试玩家1 胜利！━━━━☆")
    assert (
        result.combat_log[banner + 1]
        == "测试玩家1 站到最后，兵器归鞘——这一战，胜了。"
    )


def test_stalemate_banner_and_description_line():
    """触顶平局：胶着横幅 + 对应场景描述行。"""
    engine = make_engine(
        {"combat": {"action_limit": 1}, "skill_system": {"battle_report_merge_count": 1}}
    )
    fighter1 = make_fighter("甲", 100000, 1, 0, 10)
    fighter2 = make_fighter("乙", 100000, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.winner == "draw"
    banner = result.combat_log.index(_mod._BANNER_DRAW_STALEMATE)
    assert (
        result.combat_log[banner + 1]
        == "斗到招式都用老了，谁也压不住谁，两边各自收手——僵持不下，算作平局。"
    )


def test_mutual_destruction_banner_and_description_line():
    """同归于尽：双方反弹伤害互杀（谁先手都成立），横幅 + 描述行相邻。"""
    engine = make_engine({"skill_system": {"battle_report_merge_count": 1}})
    fighter1 = make_fighter("甲", 10, 1000, 0, 10)
    fighter2 = make_fighter("乙", 10, 1000, 0, 10)
    for fighter in (fighter1, fighter2):
        fighter.reflect_rate = 100.0

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.winner == "draw"
    banner = result.combat_log.index(_mod._BANNER_MUTUAL_DESTRUCTION)
    assert (
        result.combat_log[banner + 1]
        == "最后一击同时落下——两道身影一齐倒地，谁也没能再站起来。"
    )


def test_fallback_draw_branch_emits_its_banner():
    """兜底平局分支（设计上不可达）：NaN 极限值让 while 与触顶比较同时为假。

    只为证明该分支的横幅同样是代码结构行，不依赖叙事配置。
    """
    engine = make_engine(
        {
            "combat": {"action_limit": float("nan")},
            "skill_system": {"battle_report_merge_count": 1},
        }
    )
    fighter1 = make_fighter("甲", 100, 1, 0, 10)
    fighter2 = make_fighter("乙", 100, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.winner == "draw"
    assert result.combat_log[0] == _mod._BANNER_OPENING
    assert result.combat_log[1] == "甲 VS 乙"
    assert result.combat_log[-2] == _mod._BANNER_DRAW
    assert result.combat_log[-1] == "你来我往，谁也没占到便宜——这一场，平分秋色。"


def test_empty_config_pool_falls_back_to_embedded_description_line():
    """极端：config 池被清空 → 描述行回退内嵌默认，结构行不受影响。"""
    engine = make_engine(
        {"skill_system": {"battle_report_merge_count": 1}},
        narrative_config={"combat": {"battle_opening": [], "battle_victory": []}},
    )
    fighter1 = make_fighter("测试玩家1", 100000, 1, 0, 10)
    fighter2 = make_fighter("测试玩家2", 2, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.combat_log[0] == _mod._BANNER_OPENING
    assert result.combat_log[1] == "测试玩家1 VS 测试玩家2"
    assert (
        result.combat_log[2]
        == "杀气先到，人影随后。你握紧了兵刃站定——这一战，躲不过。"
    )
    banner = result.combat_log.index("☆━━━━ 测试玩家1 胜利！━━━━☆")
    assert (
        result.combat_log[banner + 1]
        == "测试玩家1 站到最后，兵器归鞘——这一战，胜了。"
    )


def test_retired_battle_vs_key_is_ignored_by_the_report():
    """config 残留 battle_vs 池被静默忽略，对阵行始终为代码结构行。"""
    engine = make_engine(
        {"skill_system": {"battle_report_merge_count": 1}},
        narrative_config={
            "combat": {
                "battle_vs": {"通用": ["{name1} 与 {name2} 相对而立，互道一声名号……"]},
                "battle_opening": {"通用": ["风停了，一战在即。"]},
            }
        },
    )
    fighter1 = make_fighter("测试玩家1", 100000, 1, 0, 10)
    fighter2 = make_fighter("测试玩家2", 2, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)
    report = "\n".join(result.combat_log)

    assert result.combat_log[1] == "测试玩家1 VS 测试玩家2"
    assert "相对而立" not in report
    # 开局描述行仍走 battle_opening 池
    assert result.combat_log[2] == "风停了，一战在即。"


def test_double_missing_scene_leaves_banner_only(monkeypatch):
    """config 与内嵌默认都没有该场景时：render_narrative 返回 ""，只出结构行。"""
    defaults = _mod.render_narrative.__globals__["DEFAULT_NARRATIVE_CONFIG"]
    monkeypatch.delitem(defaults["combat"], "battle_opening")
    narrative_config = {"combat": {}}
    assert (
        _mod.render_narrative(
            _FakeConfigManager(narrative_config=narrative_config),
            "combat",
            "battle_opening",
        )
        == ""
    )

    engine = make_engine(
        {"skill_system": {"battle_report_merge_count": 1}},
        narrative_config=narrative_config,
    )
    fighter1 = make_fighter("测试玩家1", 100000, 1, 0, 10)
    fighter2 = make_fighter("测试玩家2", 2, 1, 0, 10)

    result = engine.resolve_combat(fighter1, fighter2)

    assert result.combat_log[0] == _mod._BANNER_OPENING
    assert result.combat_log[1] == "测试玩家1 VS 测试玩家2"
    assert result.combat_log[2].startswith("测试玩家1：气血 ")


def _narrative_scene_args(source: str) -> set[str]:
    """Collect literal scene keys passed to ``_narrative(...)`` in ``source``.

    The scene key is the first positional argument (later args carry template
    variables such as ``remaining_hp``) or the ``scene=`` keyword; only literals
    are collected — the tier code passes a computed ``scene`` variable instead,
    which is out of this check's scope.
    """
    scenes = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or (not node.args and not node.keywords):
            continue
        callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if callee != "_narrative":
            continue
        candidates = list(node.args[:1])
        # ``scene=`` keyword form (``**kwargs`` yields arg=None and is skipped).
        candidates += [kw.value for kw in node.keywords if kw.arg == "scene"]
        for candidate in candidates:
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                scenes.add(candidate.value)
    return scenes


def test_scene_arg_collector_covers_positional_and_keyword_literals():
    """钉收集器自身：位置实参与 ``scene=`` 关键字字面量都收，计算值/``**kwargs`` 不收。"""
    source = "\n".join(
        [
            "engine._narrative('battle_vs')",
            "engine._narrative(scene='remaining_hp')",
            "engine._narrative('battle_opening', {'x': 1})",
            "engine._narrative(scene=computed)",
            "engine._narrative(**kwargs)",
        ]
    )

    assert _narrative_scene_args(source) == {
        "battle_vs",
        "remaining_hp",
        "battle_opening",
    }


# ------------------------------------------------------------------
# D4: remaining-HP tiers
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hp", "expected_tier"),
    [
        (6005, "mid"),  # 恰等 mid（0.6）：(low, mid] 闭区间 → 残局档
        (6006, None),  # 刚过 mid → 高血量降噪，不出行
        (3005, "low"),  # 恰等 low（0.3）：(0, low] 闭区间 → 濒死档
        (3006, "mid"),  # 刚过 low → 残局档
        (5, None),  # 受击致死（hp 归零）→ 死亡由结局横幅表达
        (9500, None),  # 高血量不出行
    ],
)
def test_remaining_hp_tier_boundaries(monkeypatch, hp, expected_tier):
    """四格边界（max_hp=10000、单击 5 点伤害，故受击后 HP = hp - 5）。"""
    engine = make_engine()
    defender = make_fighter("守方", hp, 0, 0, 10)
    defender.max_hp = 10000

    log = _resolve_one_attack(engine, defender, 5, monkeypatch)

    assert _tier_of(log, "守方") == expected_tier


def test_remaining_hp_is_thousands_separated(monkeypatch):
    """千分位由代码渲染：文案只见到 1,241，裸数字不得出现。"""
    engine = make_engine()
    defender = make_fighter("守方", 1246, 0, 0, 10)
    defender.max_hp = 10000

    log = _resolve_one_attack(engine, defender, 5, monkeypatch)

    assert (
        "守方 气血只剩 1,241 点，一口气吊着，人还站着。" in log
    ), f"千分位失配: {log}"
    assert "1241" not in "\n".join(log)


def test_thresholds_are_read_from_combat_config(monkeypatch):
    """阈值可由 combat 段配置覆盖：同一 HP 比例在默认阈值下被降噪。"""
    engine = make_engine(
        {
            "combat": {
                "remaining_hp_mid_threshold": 0.9,
                "remaining_hp_low_threshold": 0.85,
            }
        }
    )
    defender = make_fighter("守方", 8605, 0, 0, 10)
    defender.max_hp = 10000
    default_defender = make_fighter("守方", 8605, 0, 0, 10)
    default_defender.max_hp = 10000

    # 受击后比例 0.86 ∈ (0.85, 0.9] → 残局档；默认阈值（mid=0.6）下不出行
    assert _tier_of(_resolve_one_attack(engine, defender, 5, monkeypatch), "守方") == "mid"
    assert (
        _tier_of(_resolve_one_attack(make_engine(), default_defender, 5, monkeypatch), "守方")
        is None
    )


@pytest.mark.parametrize(
    "combat_cfg",
    [
        {"remaining_hp_mid_threshold": 0.2, "remaining_hp_low_threshold": 0.5},
        {"remaining_hp_mid_threshold": 1.5, "remaining_hp_low_threshold": 0.3},
        {"remaining_hp_mid_threshold": 0.6, "remaining_hp_low_threshold": 0},
        {"remaining_hp_mid_threshold": "0.6", "remaining_hp_low_threshold": 0.3},
        # None / bool / negative are the three non-``str`` shapes config JSON or a
        # hand-edited file can produce: ``isinstance(v, (int, float))`` rejects None,
        # and ``bool`` is an ``int`` subclass but ``0 < True < 1`` is False (likewise
        # ``0 < False``), so both fall back on the same branch as a negative value.
        {"remaining_hp_mid_threshold": None, "remaining_hp_low_threshold": 0.3},
        {"remaining_hp_mid_threshold": 0.6, "remaining_hp_low_threshold": None},
        {"remaining_hp_mid_threshold": True, "remaining_hp_low_threshold": 0.3},
        {"remaining_hp_mid_threshold": 0.6, "remaining_hp_low_threshold": False},
        {"remaining_hp_mid_threshold": 0.6, "remaining_hp_low_threshold": -0.1},
    ],
)
def test_illegal_thresholds_fall_back_to_defaults(combat_cfg):
    """非法阈值（倒置 / 越界 / 非数值 / None / 布尔 / 负数）回退代码默认 0.6 / 0.3。

    校验是**成对**的：任一格非法则两格一起回退（``combat_manager`` 构造时的
    ``all(...) or low >= mid`` 判定），故逐格断言两值都等于默认。
    """
    engine = make_engine({"combat": combat_cfg})

    assert engine._hp_mid_threshold == 0.6
    assert engine._hp_low_threshold == 0.3


def test_retired_scene_keys_are_unreferenced_in_code():
    """两个退役场景键不再作为场景键出现（grep 钉；config 键退役见任务组 4.2）。

    只钉「场景键位置」：``_narrative(...)`` 的首个位置实参，以及内嵌默认的
    ``SCENES``/``SCENE_VARS`` 字典键。变量名 ``remaining_hp``（文案插值用）仍在
    用且必须保留，不能一刀切搜字符串字面量。
    """
    retired = {"remaining_hp", "battle_vs"}
    declared = set(_combat_defaults.SCENE_VARS)
    assert retired.isdisjoint(_combat_defaults.SCENES)
    assert retired.isdisjoint(declared)

    offenders = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if any(
            part in {"tests", "__pycache__"} or part.startswith(".")
            for part in path.parts
        ):
            continue
        scene_args = _narrative_scene_args(path.read_text(encoding="utf-8"))
        for scene in sorted(scene_args & retired):
            offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: _narrative({scene!r})")
        # combat_manager owns the combat-domain ``_narrative`` wrapper; other
        # modules render their own domains, so only its keys must be declared here.
        if path == COMBAT_MANAGER:
            for scene in sorted(scene_args - retired - declared):
                offenders.append(
                    f"{path.relative_to(PLUGIN_ROOT)}: _narrative({scene!r}) 未在 SCENE_VARS 登记"
                )

    assert not offenders, f"叙事场景键引用异常: {offenders}"
