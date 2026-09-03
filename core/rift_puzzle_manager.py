"""Rift encounter puzzle engine - pure logic, no IO.

Programmatically generates puzzle instances for rift encounters across
several puzzle families (wuxing element puzzles, Lo Shu magic squares and
truth-teller/liar cave puzzles). Each encounter draws one family uniformly at
random and builds a fresh instance; nothing is cached between calls, so
consecutive puzzles are independent.

This module performs no IO, reads no database and imports nothing from
astrbot, so pytest can cover it directly. Behaviour contract:
``openspec/changes/add-rift-encounters/specs/rift-puzzle/spec.md`` and design
section D3 of the same change.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum


class CheckResult(str, Enum):
    """Three-way outcome of checking a player answer against a puzzle."""

    CORRECT = "correct"
    WRONG = "wrong"
    INVALID = "invalid"


@dataclass
class RiftPuzzle:
    """One generated puzzle instance for a rift encounter.

    Attributes:
        family: Puzzle family identifier (``"wuxing"``/``"luoshu"``/``"turtle"``).
        template: Template identifier within the family.
        question_text: User-facing Chinese question text.
        answer: Correct answer in normalized (stripped) string form.
        attempts_left: Remaining attempt budget; wrong answers decrement it to
            a floor of zero, invalid inputs never touch it.
        meta: Structured generation data (magic-square grid, turtle
            statements, ...) kept for verification and debugging. Auxiliary
            only - not part of the spec field contract.
    """

    family: str
    template: str
    question_text: str
    answer: str
    attempts_left: int = 2
    meta: dict = field(default_factory=dict)

    def check(self, answer: str) -> CheckResult:
        """Validate a player answer and return the three-way result.

        The answer is stripped before comparison. ``INVALID`` (input not
        matching the family's legal answer form) never consumes an attempt;
        ``WRONG`` consumes one attempt down to a floor of zero. The encounter
        layer decides when an exhausted puzzle closes - this method only
        tracks the budget and still reports ``CORRECT`` at zero attempts.
        """
        normalized = (answer or "").strip()
        if not _FAMILY_VALIDATORS[self.family](normalized):
            return CheckResult.INVALID
        if normalized == self.answer:
            return CheckResult.CORRECT
        if self.attempts_left > 0:
            self.attempts_left -= 1
        return CheckResult.WRONG


def check(puzzle: RiftPuzzle, answer: str) -> CheckResult:
    """Module-level convenience wrapper around :meth:`RiftPuzzle.check`."""
    return puzzle.check(answer)


def is_valid_answer(family: str, answer: str) -> bool:
    """Return whether ``answer`` matches the family's legal answer form."""
    return _FAMILY_VALIDATORS[family]((answer or "").strip())


# ---------------------------------------------------------------------------
# Family: 五行破阵 (wuxing)
# ---------------------------------------------------------------------------

WUXING_ELEMENTS = ("金", "木", "水", "火", "土")

# Generating cycle: 金生水，水生木，木生火，火生土，土生金.
WUXING_SHENG = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}
# Overcoming cycle: 金克木，木克土，土克水，水克火，火克金.
WUXING_KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}

_WUXING_SHENG_INV = {v: k for k, v in WUXING_SHENG.items()}
_WUXING_KE_INV = {v: k for k, v in WUXING_KE.items()}

# The full generating/overcoming tables are embedded in every wuxing question
# as "stele inscriptions" so players need zero prior knowledge (spec D3).
_WUXING_STELE = (
    "残碑铭文曰：\n"
    "「五行相生：金生水，水生木，木生火，火生土，土生金。」\n"
    "「五行相克：金克木，木克土，土克水，水克火，火克金。」"
)

_WUXING_HINT = "（答单字：金/木/水/火/土）"


def _gen_wuxing_ke_break(rng: random.Random) -> RiftPuzzle:
    """Overcoming-break template: given the eye element, answer its conqueror."""
    eye = rng.choice(WUXING_ELEMENTS)
    answer = _WUXING_KE_INV[eye]
    text = (
        "【五行古阵 · 相克破阵】\n"
        f"{_WUXING_STELE}\n"
        f"古阵阵眼属「{eye}」，唯以相克之五行击之方可破阵。\n"
        f"当以何五行击破阵眼？{_WUXING_HINT}"
    )
    return RiftPuzzle(
        family="wuxing",
        template="ke_break",
        question_text=text,
        answer=answer,
        meta={"eye": eye},
    )


def _gen_wuxing_cycle_fill(rng: random.Random) -> RiftPuzzle:
    """Cycle-gap template: blank one slot of four consecutive generating steps."""
    # Four consecutive slots of a 5-cycle are always distinct, so the blanked
    # element is uniquely determined by its neighbours in the fixed cycle.
    cycle = ["金", "水", "木", "火", "土"]
    start = rng.randrange(len(cycle))
    seq = [cycle[(start + i) % len(cycle)] for i in range(4)]
    blank = rng.randrange(4)
    shown = ["？" if i == blank else v for i, v in enumerate(seq)]
    text = (
        "【五行古阵 · 轮转补缺】\n"
        f"{_WUXING_STELE}\n"
        f"碑侧另刻一行残缺的相生轮转：「{' → '.join(shown)}」\n"
        f"依相生之序，缺位当为何五行？{_WUXING_HINT}"
    )
    return RiftPuzzle(
        family="wuxing",
        template="cycle_fill",
        question_text=text,
        answer=seq[blank],
        meta={"sequence": seq, "blank_index": blank},
    )


def _gen_wuxing_trace_mother(rng: random.Random) -> RiftPuzzle:
    """Trace-the-mother template: given an element, answer what generates it."""
    element = rng.choice(WUXING_ELEMENTS)
    answer = _WUXING_SHENG_INV[element]
    text = (
        "【五行古阵 · 逆生溯源】\n"
        f"{_WUXING_STELE}\n"
        f"碑末刻曰：「{element}者，有所出也。」\n"
        f"依相生之理，生「{element}」者为何五行？{_WUXING_HINT}"
    )
    return RiftPuzzle(
        family="wuxing",
        template="trace_mother",
        question_text=text,
        answer=answer,
        meta={"element": element},
    )


def _gen_wuxing(rng: random.Random) -> RiftPuzzle:
    """Build a wuxing puzzle from one of the three templates, uniformly."""
    template = rng.choice(("ke_break", "cycle_fill", "trace_mother"))
    if template == "ke_break":
        return _gen_wuxing_ke_break(rng)
    if template == "cycle_fill":
        return _gen_wuxing_cycle_fill(rng)
    return _gen_wuxing_trace_mother(rng)


def _valid_wuxing(text: str) -> bool:
    """Legal wuxing answer form: exactly one of the five element characters."""
    return text in WUXING_SHENG


# ---------------------------------------------------------------------------
# Family: 洛书数阵 (luoshu)
# ---------------------------------------------------------------------------

LUOSHU_BASE = ((4, 9, 2), (3, 5, 7), (8, 1, 6))

# Shift range for the whole-grid offset d; small values keep answers mental-math
# friendly while still varying the instance (target sum becomes 15 + 3d).
LUOSHU_SHIFT_MIN = 0
LUOSHU_SHIFT_MAX = 9


def _rot90(grid: tuple) -> tuple:
    """Rotate a square grid 90 degrees clockwise."""
    return tuple(tuple(row) for row in zip(*grid[::-1]))


def _mirror(grid: tuple) -> tuple:
    """Mirror a grid horizontally."""
    return tuple(tuple(reversed(row)) for row in grid)


def _build_luoshu_variants() -> tuple:
    """All 8 rotations/reflections of the Lo Shu square (dihedral group D4).

    The Lo Shu square has no internal symmetry, so its D4 orbit has exactly 8
    distinct members - these are all the order-3 magic squares on 1..9.
    """
    variants = []
    g = LUOSHU_BASE
    for _ in range(4):
        variants.append(g)
        g = _rot90(g)
    g = _mirror(LUOSHU_BASE)
    for _ in range(4):
        variants.append(g)
        g = _rot90(g)
    return tuple(variants)


LUOSHU_VARIANTS = _build_luoshu_variants()


def _gen_luoshu(rng: random.Random) -> RiftPuzzle:
    """Build a Lo Shu puzzle: shifted variant with one cell blanked out."""
    base = rng.choice(LUOSHU_VARIANTS)
    d = rng.randint(LUOSHU_SHIFT_MIN, LUOSHU_SHIFT_MAX)
    grid = [[v + d for v in row] for row in base]
    target = 15 + 3 * d
    r, c = rng.randrange(3), rng.randrange(3)
    shown = [
        " ".join("？" if (i, j) == (r, c) else str(v) for j, v in enumerate(row))
        for i, row in enumerate(grid)
    ]
    text = (
        "【洛书数阵】\n"
        "残碑上刻着一座三阶数阵，其中一格已然剥落：\n"
        + "\n".join(shown)
        + f"\n碑注：补全缺格后，每行、每列与两条对角线之和皆等于 {target}。\n"
        "剥落之格当填何数？（答一个数字）"
    )
    return RiftPuzzle(
        family="luoshu",
        template="missing_cell",
        question_text=text,
        answer=str(grid[r][c]),
        meta={"grid": grid, "missing": (r, c), "target_sum": target, "shift": d},
    )


def _valid_luoshu(text: str) -> bool:
    """Legal luoshu answer form: a plain integer (no spaces or units)."""
    return text.isdigit() or (text.startswith("-") and text[1:].isdigit())


# ---------------------------------------------------------------------------
# Family: 灵龟辨窟 (turtle)
# ---------------------------------------------------------------------------

TURTLE_CAVES = ("甲", "乙", "丙")

_TURTLE_LABELS = ("其一", "其二", "其三")


def turtle_solutions(statements: list[dict], constraint: str) -> list[str]:
    """List the caves that satisfy a truth constraint over the statements.

    A statement dict has ``kind`` (``"in"`` = "treasure is in cave X" or
    ``"not_in"`` = "treasure is not in cave X") and ``cave``. The constraint is
    ``"exactly_one_true"`` (exactly one statement true) or
    ``"exactly_one_false"`` (exactly one statement false). Used by the
    generator to prove each instance has a unique solution, and by tests.
    """
    if constraint not in ("exactly_one_true", "exactly_one_false"):
        raise ValueError(f"unknown turtle constraint: {constraint}")
    solutions = []
    for cand in TURTLE_CAVES:
        n_true = sum(
            1 for s in statements if (cand == s["cave"]) == (s["kind"] == "in")
        )
        if constraint == "exactly_one_true" and n_true == 1:
            solutions.append(cand)
        elif constraint == "exactly_one_false" and n_true == len(statements) - 1:
            solutions.append(cand)
    return solutions


def _turtle_stmt_text(kind: str, cave: str) -> str:
    """Render a turtle statement as user-facing Chinese text."""
    return f"宝物在{cave}窟" if kind == "in" else f"宝物不在{cave}窟"


def _turtle_build_one_truth(treasure: str, x: str) -> tuple:
    """Three inscriptions, exactly one true.

    Truth counts by candidate: treasure -> 1 (only "not_in x" holds), x -> 2,
    the third cave -> 2; hence the treasure cave is the unique solution.
    """
    statements = [
        {"kind": "not_in", "cave": x},
        {"kind": "in", "cave": x},
        {"kind": "not_in", "cave": treasure},
    ]
    return statements, "exactly_one_true", "碑铭三则，只有一句真话："


def _turtle_build_one_lie(treasure: str, x: str) -> tuple:
    """Three inscriptions, exactly one false.

    Truth counts by candidate: treasure -> 2 ("in x" is the single lie),
    x -> 1, the third cave -> 1; hence the treasure cave is the unique
    solution.
    """
    statements = [
        {"kind": "in", "cave": x},
        {"kind": "not_in", "cave": x},
        {"kind": "in", "cave": treasure},
    ]
    return statements, "exactly_one_false", "碑铭三则，只有一句假话："


def _turtle_build_half_truth(treasure: str, x: str, y: str) -> tuple:
    """Two inscriptions, one true and one false.

    Truth counts by candidate: treasure -> 1 (only "not_in y" holds), x -> 2,
    y -> 0; hence the treasure cave is the unique solution.
    """
    statements = [
        {"kind": "in", "cave": x},
        {"kind": "not_in", "cave": y},
    ]
    return statements, "exactly_one_true", "碑铭两则，一真一假："


def _gen_turtle(rng: random.Random) -> RiftPuzzle:
    """Build a turtle cave puzzle with a provably unique solution."""
    template = rng.choice(("one_truth", "one_lie", "half_truth"))
    treasure = rng.choice(TURTLE_CAVES)
    others = [c for c in TURTLE_CAVES if c != treasure]
    x = rng.choice(others)
    y = next(c for c in others if c != x)
    if template == "one_truth":
        statements, constraint, constraint_text = _turtle_build_one_truth(treasure, x)
    elif template == "one_lie":
        statements, constraint, constraint_text = _turtle_build_one_lie(treasure, x)
    else:
        statements, constraint, constraint_text = _turtle_build_half_truth(
            treasure, x, y
        )
    # Attach display text before shuffling so text follows its statement; the
    # shuffle defeats memorizing fixed inscription positions.
    for s in statements:
        s["text"] = _turtle_stmt_text(s["kind"], s["cave"])
    rng.shuffle(statements)
    # The templates guarantee uniqueness by construction (see their
    # docstrings); verify per instance anyway so a future template edit fails
    # loudly here instead of shipping an unsolvable or ambiguous puzzle.
    solutions = turtle_solutions(statements, constraint)
    if solutions != [treasure]:
        raise RuntimeError(
            f"turtle template {template} lost its unique solution: {solutions}"
        )
    lines = [f"{label}：{s['text']}" for label, s in zip(_TURTLE_LABELS, statements)]
    text = (
        "【灵龟辨窟】\n"
        "灵龟驮碑而至，碑文曰：「宝物藏于甲、乙、丙三窟之一。」\n"
        f"{constraint_text}\n"
        + "\n".join(lines)
        + "\n宝物藏于哪座洞窟？（答单字：甲/乙/丙）"
    )
    return RiftPuzzle(
        family="turtle",
        template=template,
        question_text=text,
        answer=treasure,
        meta={"statements": statements, "constraint": constraint, "treasure": treasure},
    )


def _valid_turtle(text: str) -> bool:
    """Legal turtle answer form: exactly one of the three cave characters."""
    return text in TURTLE_CAVES


# ---------------------------------------------------------------------------
# Family registry and entry point
# ---------------------------------------------------------------------------

GeneratorFn = Callable[[random.Random], RiftPuzzle]
ValidatorFn = Callable[[str], bool]

_FAMILY_GENERATORS: dict[str, GeneratorFn] = {}
_FAMILY_VALIDATORS: dict[str, ValidatorFn] = {}


def register_family(name: str, generator: GeneratorFn, validator: ValidatorFn) -> None:
    """Register a puzzle family so :func:`generate` can draw it.

    Args:
        name: Family identifier used in ``RiftPuzzle.family`` and for answer
            form validation.
        generator: Pure function building a fresh instance from an rng.
        validator: Legal-answer-form check applied to the stripped answer.
    """
    _FAMILY_GENERATORS[name] = generator
    _FAMILY_VALIDATORS[name] = validator


def registered_families() -> tuple[str, ...]:
    """Names of all registered puzzle families (the default enabled set)."""
    return tuple(_FAMILY_GENERATORS)


def generate(
    rng: random.Random | None = None,
    families: Iterable[str] | None = None,
    attempts: int = 2,
) -> RiftPuzzle:
    """Pick one enabled family uniformly at random and build a fresh instance.

    Every call re-rolls both the family and the instance from ``rng``; no
    state is cached between calls, so consecutive puzzles are independent.

    Args:
        rng: Random source; defaults to the module-level ``random`` functions.
            Pass a seeded ``random.Random`` in tests.
        families: Enabled family names to draw from (equal weight); defaults
            to all registered families. Unknown names raise ``KeyError``.
        attempts: Attempt budget stored on the instance; the encounter layer
            feeds config key ``puzzle_attempts`` here (default 2).

    Returns:
        A freshly generated :class:`RiftPuzzle`.
    """
    rand = rng if rng is not None else random
    names = list(families) if families is not None else list(_FAMILY_GENERATORS)
    if not names:
        raise ValueError("no puzzle families enabled")
    family = rand.choice(names)
    puzzle = _FAMILY_GENERATORS[family](rand)
    puzzle.attempts_left = attempts
    return puzzle


register_family("wuxing", _gen_wuxing, _valid_wuxing)
register_family("luoshu", _gen_luoshu, _valid_luoshu)
register_family("turtle", _gen_turtle, _valid_turtle)
