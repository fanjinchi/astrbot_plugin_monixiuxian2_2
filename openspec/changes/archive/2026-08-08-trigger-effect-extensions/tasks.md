# Tasks: trigger-effect-extensions

## 1. Engine foundation: FighterState & status effect model

- [x] 1.1 Add `StatusEffect` dataclass (source_name/kind/effect_value/tick_rate/duration/remaining/params + snapshot damage) and `status_effects: list[StatusEffect]` on FighterState (managers/combat_manager.py)
- [x] 1.2 Add one-shot / charge fields on FighterState: `next_attack_unavoidable: bool`, `survive_charges: int` (default from skill config), `reflect` flag handling per D4/D6
- [x] 1.3 Add `status_stack_cap` to config/game_config.json (default 3) and thread through CombatEngine config loading

## 2. Status effect lifecycle (battle-status-effects)

- [x] 2.1 Implement round-start tick in resolve loop (after round_start trigger skills): dot damage (`max(1, snapshot_damage × effect_value × tick_rate)`), duration decrement, expiry removal
- [x] 2.2 Implement same-source refresh (reset remaining, update value, no extra stack) and cross-source stacking cap (cap=status_stack_cap, over-cap logged in battle log)
- [x] 2.3 Implement buff/debuff multiplicative modifiers applied at damage formula / initiative read points (damage/armor/speed) without mutating base FighterState fields
- [x] 2.4 Battle-end cleanup: status_effects and one-shot flags die with FighterState (verify no persistence path exists; add test)

## 3. Effect registry extension (EFFECT_HANDLERS)

- [x] 3.1 Implement `heal` handler: heal_percent (default effect_value) of max_hp; vampire mode = heal self by `effect_value × dealt_damage` when configured (source-side)
- [x] 3.2 Implement `dot` handler: snapshot expected attack damage into a new status effect (D2 semantics; dodge → 0 snapshot recorded)
- [x] 3.3 Implement `buff`/`debuff`/`fatigue` handlers: enqueue status effect with duration (default 1); fatigue is a debuff kind (D8)
- [x] 3.4 Implement `pierce` handler: damage increment computed against armor-mitigated baseline — bypass armor by `pierce_rate` (0-1) of the reduction
- [x] 3.5 Implement `unavoidable` handler: set `next_attack_unavoidable` one-shot flag (D4)
- [x] 3.6 Implement `reflect` handler: set reflect flag with reflect_rate; consumed on incoming hit, refunds `reflect_rate × actual damage` as fixed damage (no armor), never reflects reflect, max 1 per round (D6)
- [x] 3.7 Implement `survive` handler: grant `survive_charges` (survive_count, default 1) on trigger (ultimate/trigger skill both)

## 4. Judgment hook points

- [x] 4.1 unavoidable consumption: skip dodge/block/counter checks when next_attack_unavoidable set; reset after the attack (PVE + PVP shared path)
- [x] 4.2 survive in victory check: when hp ≤ 0 and survive_charges > 0 → hp=1, charges-1, apply survive recovery (default 0), battle log entry; otherwise normal defeat
- [x] 4.3 reflect application on incoming damage (after armor/actual damage determined), including survive interplay (reflect lethal → opponent survive check still runs)
- [x] 4.4 round_start allowance extension: buff/debuff (self-buff semantics) added to the allowed list; others still warning-skipped

## 5. Ultimate non-damage dispatch

- [x] 5.1 Rework ultimate trigger path (managers/combat_manager.py:621 area): gate (min_action_index + hp conditions) and once-per-battle limit unchanged; after passing, dispatch by effect_type through EFFECT_HANDLERS instead of inline ultimate_mult only
- [x] 5.2 Backward compat: normalization layer injects `effect_type: damage_bonus` for ultimates lacking one; existing config behavior unchanged (regression tests must pass untouched)

## 6. Normalization layer passthrough

- [x] 6.1 core/skill_manager.py: passthrough new optional keys (duration/tick_rate/heal_percent/pierce_rate/reflect_rate/survive_count) in trigger_skill/ultimate normalization; default-inject effect_type (damage_bonus) when absent
- [x] 6.2 Verify route-multiplier interplay: route mult applies to rate (trigger) and value (ultimate) only; new optional keys untouched by multiplier (design D10)

## 7. Sync script contract extension

- [x] 7.1 Extend SKILL_EFFECT_TYPES to the full 13-type vocabulary; add same-source assertion (test) that it matches EFFECT_HANDLERS keys
- [x] 7.2 `_build_skill`: validate new optional keys (duration int ≥1, tick_rate/heal_percent/pierce_rate/reflect_rate numeric with value ranges, survive_count int ≥1); reject invalid values
- [x] 7.3 `_validate_ultimate`: same new-key validation for ultimate entries
- [x] 7.4 validate_budget.py: damage-equivalent conversion — heal value×max_hp, dot value×duration, pierce value×(1+0.5), buff/debuff/reflect/survive/unavoidable value-based with WARN, fatigue excluded; unimplemented effect_type → FAIL not WARN

## 8. Tests

- [x] 8.1 Unit tests per effect (≥2 scenarios each): heal (incl. vampire), dot (multi-round + refresh + stack cap + expiry), buff/debuff (modifier applied, not persisted), pierce (armor bypass math), unavoidable (dodge/block/counter skipped), reflect (refund math, no reflect-chain), survive (lethal saved once, exhausted → defeat), fatigue (debuff semantics)
- [x] 8.2 Status lifecycle tests: round-start tick order, expiry, battle-end cleanup, no DB writes
- [x] 8.3 Ultimate dispatch tests: non-damage ultimate (heal/survive) via gate+limit; legacy ultimate without effect_type keeps damage semantics
- [x] 8.4 Sync contract tests: new-key validation reject cases, vocabulary sync assertion, validate_budget conversion cases
- [x] 8.5 Integration: PVP and PVE combat with new effects via loadout (both CombatManager adapter and CombatEngine entry); full suite stays green (current 363)

## 9. Design tables & verification skills

- [x] 9.1 skills-ultimates.md: flip §2.2/§6 needs_code status for implemented effects (heal/dot/buff/debuff/pierce/unavoidable/survive/reflect; fatigue as 天魔解体 option); update §5 open questions
- [x] 9.2 Add limited verification skills to skills.csv (e.g., 治疗/吸血 1-2, DOT 1, 免死大招 1, 必中 1) with 0.x values within budget; run sync --dry-run then write; validate_budget 0 FAIL
- [x] 9.3 schema-and-engine-fit.md: check off P3 needs_code row (bd tt3 scope) with implementation date; note reflect decision

## 10. Wrap-up

- [x] 10.1 Close bd `tt3` (效果引擎化) with reference to this change; keep `dhh` open for rebalancing
- [x] 10.2 ruff format + ruff check; full pytest green
- [x] 10.3 openspec validate --specs passed; archive change after merge per AGENTS.md session rules; commit + push
