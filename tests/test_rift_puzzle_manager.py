"""Tests for the rift encounter puzzle engine (core/rift_puzzle_manager.py).

Covers:
- Answer correctness for every wuxing template (against the element tables)
- Lo Shu magic-square constraint satisfaction after filling in the answer
- Turtle puzzle unique-solution guarantee for every template
- Independent randomness between consecutive generate() calls (no caching)
- check() three-way results, attempt consumption rules, exhaustion boundary

All randomized assertions iterate over fixed seeds, so runs are deterministic.
"""

import random

import pytest

from tests.helpers import load_module

_mod = load_module("rift_puzzle_manager", "core/rift_puzzle_manager.py")

RiftPuzzle = _mod.RiftPuzzle
CheckResult = _mod.CheckResult
generate = _mod.generate
check = _mod.check
is_valid_answer = _mod.is_valid_answer
registered_families = _mod.registered_families
turtle_solutions = _mod.turtle_solutions
WUXING_SHENG = _mod.WUXING_SHENG
WUXING_KE = _mod.WUXING_KE
TURTLE_CAVES = _mod.TURTLE_CAVES

SHENG_INV = {v: k for k, v in WUXING_SHENG.items()}
KE_INV = {v: k for k, v in WUXING_KE.items()}

# Fixed seed range keeps randomized assertions deterministic (no flakiness).
SEEDS = range(400)


def _gen_family(family: str, seeds=SEEDS) -> list:
    """Generate one puzzle per seed, restricted to a single family."""
    return [generate(random.Random(s), families=[family]) for s in seeds]


# ---------------------------------------------------------------------------
# Wuxing (五行破阵)
# ---------------------------------------------------------------------------


def test_wuxing_all_templates_seen():
    """Fixed seeds must hit all three wuxing templates."""
    templates = {p.template for p in _gen_family("wuxing")}
    assert templates == {"ke_break", "cycle_fill", "trace_mother"}


def test_wuxing_stele_embedded():
    """Every wuxing question embeds the full generating/overcoming tables."""
    for p in _gen_family("wuxing", range(30)):
        assert "金生水" in p.question_text
        assert "火生土" in p.question_text
        assert "金克木" in p.question_text
        assert "水克火" in p.question_text


def test_wuxing_ke_break_answer():
    """ke_break: the answer conquers the eye element (KE[answer] == eye)."""
    puzzles = [p for p in _gen_family("wuxing") if p.template == "ke_break"]
    assert puzzles
    for p in puzzles:
        eye = p.meta["eye"]
        assert eye in p.question_text
        assert p.answer == KE_INV[eye]
        assert WUXING_KE[p.answer] == eye


def test_wuxing_cycle_fill_answer():
    """cycle_fill: the answer is the blanked slot of a valid generating run."""
    puzzles = [p for p in _gen_family("wuxing") if p.template == "cycle_fill"]
    assert puzzles
    for p in puzzles:
        seq = p.meta["sequence"]
        # The shown sequence must follow the generating cycle step by step.
        for a, b in zip(seq, seq[1:]):
            assert WUXING_SHENG[a] == b
        assert p.answer == seq[p.meta["blank_index"]]
        # Exactly one slot is blanked in the displayed sequence (the trailing
        # prompt sentence also contains a full-width "？", so scope the count
        # to the sequence line).
        seq_line = next(
            line for line in p.question_text.splitlines() if "轮转：" in line
        )
        assert seq_line.count("？") == 1


def test_wuxing_trace_mother_answer():
    """trace_mother: the answer generates the given element."""
    puzzles = [p for p in _gen_family("wuxing") if p.template == "trace_mother"]
    assert puzzles
    for p in puzzles:
        assert WUXING_SHENG[p.answer] == p.meta["element"]
        assert p.meta["element"] in p.question_text


# ---------------------------------------------------------------------------
# Luoshu (洛书数阵)
# ---------------------------------------------------------------------------


def _magic_square_ok(grid: list, target: int) -> bool:
    """Check all rows, columns and both diagonals sum to ``target``."""
    if not all(sum(row) == target for row in grid):
        return False
    if not all(sum(grid[r][c] for r in range(3)) == target for c in range(3)):
        return False
    if sum(grid[i][i] for i in range(3)) != target:
        return False
    return sum(grid[i][2 - i] for i in range(3)) == target


def test_luoshu_variants_are_eight_distinct():
    """The D4 orbit of the Lo Shu base has exactly 8 distinct members."""
    assert len(_mod.LUOSHU_VARIANTS) == 8
    assert len(set(_mod.LUOSHU_VARIANTS)) == 8


def test_luoshu_answer_satisfies_magic_constraint():
    """Filling the blanked cell with the answer restores the magic square."""
    for p in _gen_family("luoshu"):
        grid = p.meta["grid"]
        r, c = p.meta["missing"]
        target = p.meta["target_sum"]
        assert int(p.answer) == grid[r][c]
        # The answer filled back into the complete grid meets the constraint.
        assert _magic_square_ok(grid, target)
        # Shift relation: target = 15 + 3d (spec D3).
        assert target == 15 + 3 * p.meta["shift"]
        # The grid body shows exactly one blank; the prompt sentence also
        # contains a full-width "？", so scope the count to the grid lines.
        body = p.question_text.splitlines()[2:5]
        assert sum(line.count("？") for line in body) == 1
        assert str(target) in p.question_text


def test_luoshu_shown_cells_match_grid():
    """Every visible number in the question matches the underlying grid."""
    for p in _gen_family("luoshu", range(60)):
        grid = p.meta["grid"]
        r, c = p.meta["missing"]
        body = p.question_text.splitlines()[2:5]
        for i, line in enumerate(body):
            cells = line.split()
            for j, cell in enumerate(cells):
                if (i, j) == (r, c):
                    assert cell == "？"
                else:
                    assert cell == str(grid[i][j])


# ---------------------------------------------------------------------------
# Turtle (灵龟辨窟)
# ---------------------------------------------------------------------------


def test_turtle_all_templates_seen():
    """Fixed seeds must hit all three turtle templates."""
    templates = {p.template for p in _gen_family("turtle")}
    assert templates == {"one_truth", "one_lie", "half_truth"}


def test_turtle_unique_solution():
    """Every turtle instance has exactly one cave satisfying the constraint."""
    for p in _gen_family("turtle"):
        statements = p.meta["statements"]
        constraint = p.meta["constraint"]
        assert turtle_solutions(statements, constraint) == [p.meta["treasure"]]
        assert p.answer == p.meta["treasure"]
        # All three caves are named in the question (anti-memorization layout).
        for cave in TURTLE_CAVES:
            assert cave in p.question_text


def test_turtle_templates_have_expected_statement_counts():
    """one_truth/one_lie use three inscriptions, half_truth uses two."""
    puzzles = _gen_family("turtle")
    by_template = {}
    for p in puzzles:
        by_template.setdefault(p.template, p)
    assert len(by_template["one_truth"].meta["statements"]) == 3
    assert len(by_template["one_lie"].meta["statements"]) == 3
    assert len(by_template["half_truth"].meta["statements"]) == 2
    assert "一真一假" in by_template["half_truth"].question_text


def test_turtle_solutions_classic_case():
    """Hand-built classic: only 丙 satisfies 'exactly one true statement'."""
    statements = [
        {"kind": "not_in", "cave": "甲"},
        {"kind": "in", "cave": "甲"},
        {"kind": "not_in", "cave": "丙"},
    ]
    assert turtle_solutions(statements, "exactly_one_true") == ["丙"]


def test_turtle_solutions_rejects_unknown_constraint():
    """Unknown constraint names raise instead of silently returning []."""
    with pytest.raises(ValueError):
        turtle_solutions([], "bogus")


# ---------------------------------------------------------------------------
# generate(): family sampling and instance independence
# ---------------------------------------------------------------------------


def test_generate_samples_all_families():
    """With a fixed seed, sampling hits every registered family."""
    rng = random.Random(0)
    families = {generate(rng).family for _ in range(300)}
    assert families == set(registered_families()) == {"wuxing", "luoshu", "turtle"}


def test_generate_same_seed_same_instance():
    """Same seeded rng reproduces the instance: it is fully rng-driven."""
    p1 = generate(random.Random(7))
    p2 = generate(random.Random(7))
    assert (p1.family, p1.template, p1.answer, p1.question_text) == (
        p2.family,
        p2.template,
        p2.answer,
        p2.question_text,
    )


def test_generate_calls_generator_every_time(monkeypatch):
    """Two consecutive calls both invoke the family generator (no caching)."""
    calls = []
    real = _mod._FAMILY_GENERATORS["wuxing"]

    def spy(rng):
        calls.append(1)
        return real(rng)

    monkeypatch.setitem(_mod._FAMILY_GENERATORS, "wuxing", spy)
    p1 = generate(random.Random(1), families=["wuxing"])
    p2 = generate(random.Random(2), families=["wuxing"])
    assert len(calls) == 2
    assert p1 is not p2


def test_generate_attempts_override():
    """The attempts budget passed to generate() lands on the instance."""
    p = generate(random.Random(3), families=["wuxing"], attempts=5)
    assert p.attempts_left == 5


def test_generate_rejects_empty_family_list():
    """An empty enabled set is an error, not a silent hang."""
    with pytest.raises(ValueError):
        generate(random.Random(0), families=[])


def test_generate_rejects_unknown_family():
    """Unknown family names raise KeyError from the registry."""
    with pytest.raises(KeyError):
        generate(random.Random(0), families=["bogus"])


# ---------------------------------------------------------------------------
# check(): three-way results and attempt budget
# ---------------------------------------------------------------------------


def _puzzle(family: str, answer: str, attempts: int = 2) -> RiftPuzzle:
    """Build a bare puzzle for check() tests."""
    return RiftPuzzle(
        family=family,
        template="t",
        question_text="q",
        answer=answer,
        attempts_left=attempts,
    )


def test_check_correct_keeps_attempts():
    """A correct answer returns CORRECT and consumes no attempt."""
    p = _puzzle("wuxing", "金")
    assert p.check("金") == CheckResult.CORRECT
    assert p.attempts_left == 2


def test_check_strips_whitespace():
    """Answers are stripped before validation and comparison."""
    p = _puzzle("wuxing", "金")
    assert p.check("  金 \n") == CheckResult.CORRECT
    assert p.attempts_left == 2


def test_check_result_matches_plain_strings():
    """CheckResult is a str enum comparable to the spec's literal names."""
    p = _puzzle("wuxing", "金")
    assert p.check("金") == "correct"
    assert p.check("木") == "wrong"
    assert p.check("金木") == "invalid"


def test_check_wrong_consumes_attempts_to_zero():
    """Wrong answers consume one attempt each, down to a floor of zero."""
    p = _puzzle("wuxing", "金")
    assert p.check("木") == CheckResult.WRONG
    assert p.attempts_left == 1
    assert p.check("水") == CheckResult.WRONG
    assert p.attempts_left == 0
    # Exhaustion boundary: further wrong answers never drive it negative.
    assert p.check("火") == CheckResult.WRONG
    assert p.attempts_left == 0


def test_check_correct_still_reported_at_zero_attempts():
    """check() only tracks the budget; closure is the encounter layer's job."""
    p = _puzzle("wuxing", "金", attempts=0)
    assert p.check("金") == CheckResult.CORRECT


@pytest.mark.parametrize("bad", ["", "金木", "1", "王", "金金"])
def test_wuxing_invalid_forms_keep_attempts(bad):
    """Wuxing rejects anything but a single element char, without consuming."""
    p = _puzzle("wuxing", "金")
    assert p.check(bad) == CheckResult.INVALID
    assert p.attempts_left == 2


@pytest.mark.parametrize("bad", ["", "甲", "1a", "1.5", "十二", "1 2"])
def test_luoshu_invalid_forms_keep_attempts(bad):
    """Luoshu rejects anything but a plain integer, without consuming."""
    p = _puzzle("luoshu", "7")
    assert p.check(bad) == CheckResult.INVALID
    assert p.attempts_left == 2


@pytest.mark.parametrize("bad", ["", "丁", "甲乙", "1", "甲甲"])
def test_turtle_invalid_forms_keep_attempts(bad):
    """Turtle rejects anything but a single cave char, without consuming."""
    p = _puzzle("turtle", "甲")
    assert p.check(bad) == CheckResult.INVALID
    assert p.attempts_left == 2


def test_module_level_check_delegates():
    """The module-level check() wrapper matches the method."""
    p = _puzzle("turtle", "乙")
    assert check(p, "乙") == CheckResult.CORRECT
    assert check(p, "甲") == CheckResult.WRONG
    assert check(p, "丙丙") == CheckResult.INVALID


def test_is_valid_answer_helper():
    """is_valid_answer applies the family validator to the stripped input."""
    assert is_valid_answer("wuxing", " 水 ")
    assert not is_valid_answer("wuxing", "水火")
    assert is_valid_answer("luoshu", "15")
    assert not is_valid_answer("luoshu", "甲")
    assert is_valid_answer("turtle", "丙")
    assert not is_valid_answer("turtle", "丁")
