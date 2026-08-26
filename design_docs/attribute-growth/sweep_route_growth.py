"""One-off parameter sweep for the dual-route growth tables.

Monkeypatches ``sim_route_matchup._GROWTH_BY_ROUTE`` with candidate tables and
reports 体修 win rates per milestone/gear cell. Not part of the calibration
artifacts — a tuning aid used to derive the values that get committed to
``config/game_config.json`` and ``design.md``.

Usage:
    uv run python design_docs/attribute-growth/sweep_route_growth.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sim_route_matchup as sim  # noqa: E402

BATTLES = 1500

# 每候选：体修/灵修各给 4 段的 (hp_step, dmg, agi, spd) 权重
CANDIDATES: dict[str, dict] = {
    # v1: 锚点（已知惨败）
    "v1-anchor": {
        "体修": {
            "hp_step": [17, 16, 15, 14],
            "growth_weights": [
                {"damage": 0.55, "agility": 0.30, "speed": 0.15},
                {"damage": 0.50, "agility": 0.30, "speed": 0.20},
                {"damage": 0.45, "agility": 0.30, "speed": 0.25},
                {"damage": 0.45, "agility": 0.30, "speed": 0.25},
            ],
        },
        "灵修": {
            "hp_step": [13, 14, 16, 17],
            "growth_weights": [
                {"damage": 0.45, "agility": 0.20, "speed": 0.35},
                {"damage": 0.50, "agility": 0.20, "speed": 0.30},
                {"damage": 0.55, "agility": 0.20, "speed": 0.25},
                {"damage": 0.60, "agility": 0.20, "speed": 0.20},
            ],
        },
    },
    # v2: 收窄迅捷差（灵修 .25 平台，体修 .20 平台），体修伤害显著拉高
    "v2-narrow-speed": {
        "体修": {
            "hp_step": [18, 17, 16, 15],
            "growth_weights": [
                {"damage": 0.62, "agility": 0.20, "speed": 0.18},
                {"damage": 0.58, "agility": 0.22, "speed": 0.20},
                {"damage": 0.54, "agility": 0.24, "speed": 0.22},
                {"damage": 0.52, "agility": 0.26, "speed": 0.22},
            ],
        },
        "灵修": {
            "hp_step": [14, 14, 15, 16],
            "growth_weights": [
                {"damage": 0.48, "agility": 0.22, "speed": 0.30},
                {"damage": 0.52, "agility": 0.20, "speed": 0.28},
                {"damage": 0.56, "agility": 0.18, "speed": 0.26},
                {"damage": 0.60, "agility": 0.16, "speed": 0.24},
            ],
        },
    },
    # v4: 迅捷差收窄到"快一点"（满级 +7），灵修伤害后期反超，体修气血/身法占优
    "v4-user-intent": {
        "体修": {
            "hp_step": [18, 17, 16, 15],
            "growth_weights": [
                {"damage": 0.58, "agility": 0.22, "speed": 0.20},
                {"damage": 0.54, "agility": 0.24, "speed": 0.22},
                {"damage": 0.50, "agility": 0.26, "speed": 0.24},
                {"damage": 0.47, "agility": 0.28, "speed": 0.25},
            ],
        },
        "灵修": {
            "hp_step": [14, 15, 16, 17],
            "growth_weights": [
                {"damage": 0.50, "agility": 0.22, "speed": 0.28},
                {"damage": 0.53, "agility": 0.20, "speed": 0.27},
                {"damage": 0.56, "agility": 0.18, "speed": 0.26},
                {"damage": 0.59, "agility": 0.17, "speed": 0.24},
            ],
        },
    },
    # v5: 在 v4 基础上微调（体修气血略降、灵修前期伤害略升）
    "v5-fine-tune": {
        "体修": {
            "hp_step": [17, 16, 15, 15],
            "growth_weights": [
                {"damage": 0.58, "agility": 0.22, "speed": 0.20},
                {"damage": 0.54, "agility": 0.24, "speed": 0.22},
                {"damage": 0.50, "agility": 0.26, "speed": 0.24},
                {"damage": 0.47, "agility": 0.28, "speed": 0.25},
            ],
        },
        "灵修": {
            "hp_step": [14, 15, 16, 16],
            "growth_weights": [
                {"damage": 0.51, "agility": 0.21, "speed": 0.28},
                {"damage": 0.53, "agility": 0.20, "speed": 0.27},
                {"damage": 0.56, "agility": 0.18, "speed": 0.26},
                {"damage": 0.59, "agility": 0.17, "speed": 0.24},
            ],
        },
    },
}


def main() -> None:
    for name, tables in CANDIDATES.items():
        sim._GROWTH_BY_ROUTE = tables
        print(f"\n== {name} ==")
        for level in sim.MILESTONES:
            cells = []
            for armed in (False, True):
                tixiu_wins = draws = 0
                for _ in range(BATTLES):
                    f_ti = sim.build_route_fighter("体修", level, armed)
                    f_ling = sim.build_route_fighter("灵修", level, armed)
                    result = sim.ENGINE.resolve_combat(
                        f_ti, f_ling, combat_type="spar", merge_count=10
                    )
                    if result.winner == "draw":
                        draws += 1
                    elif result.winner == "体修":
                        tixiu_wins += 1
                decided = BATTLES - draws
                cells.append(
                    f"{'armed' if armed else 'bare'}: {tixiu_wins / decided:.1%}"
                )
            ti = sim.expected_route_attrs("体修", level)
            li = sim.expected_route_attrs("灵修", level)
            print(
                f"  L{level}: {' | '.join(cells)}   "
                f"体[{ti['hp']:.0f}/{ti['damage']:.0f}/{ti['agility']:.0f}/{ti['speed']:.0f}] "
                f"灵[{li['hp']:.0f}/{li['damage']:.0f}/{li['agility']:.0f}/{li['speed']:.0f}]"
            )


if __name__ == "__main__":
    main()
