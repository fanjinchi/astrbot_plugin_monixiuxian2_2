#!/usr/bin/env python3
"""Narrative lint gate for content-design CSVs and config description fields.

Checks (spec `content-sync-pipeline` 叙事文案 lint 闸门):
- 禁用词：world-bible.md §5.3 清单（现代/出戏词 + 机制承诺词）不得进文案正文
- 数值承诺：百分号、阿拉伯数字数值表述不得进文案
- 长度上限：单条描述不超过设定上限（默认 60 字，可 ``--max-len`` 覆盖）
- 品级冠词：品级词（凡/灵/玄/地/天）只作名称冠词，不进描述正文
- 名字一致性：canon 表 name 列与 config 同 id/key 条目 name 必须一致
- canon 列：``canon_origin/tone_tier/story_hook/narrative_status`` 四列存在、
  取值域合法（tone_tier 四档 / narrative_status 三态）、canon_origin 可在 bible 查证

严重度规则（design.md 风险节）：
- ``status=legacy`` 行恒 WARN（参照行，与 validate_budget.py 一致）
- ``narrative_status=定稿`` 行违例 → FAIL；其余（占位/待写/空）→ WARN
- ``--strict`` 关闭"占位行放宽"，占位/待写行违例也计 FAIL
- 名字不一致是数据完整性问题，非 legacy 行恒 FAIL（spec 名字一致性场景）

Usage:
    uv run python design_docs/content-design/lint_narrative.py [--strict] [--max-len N]

Returns:
    Exit code 0 when no FAIL, 1 otherwise.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent
CONFIG_DIR = DESIGN_DIR.parent.parent / "config"

# ===== 禁用词清单（world-bible.md §5.3，bible 修订时人工同步此处） =====
# 现代/出戏词：系统、等级、属性、装备、技能、buff、debuff、CD、mmo、氪金、
#   充值、抽卡、数值、本体、目标、冷却、经验、任务完成度……
# 超规格词：在天品武器上写"最强/无敌/唯一"；描述里承诺机制（"+30% 伤害"等）。
BANNED_WORDS = (
    "系统",
    "等级",
    "属性",
    "装备",
    "技能",
    "buff",
    "debuff",
    "CD",
    "mmo",
    "氪金",
    "充值",
    "抽卡",
    "数值",
    "本体",
    "目标",
    "冷却",
    "经验",
    "任务完成度",
    "最强",
    "无敌",
    "唯一",
)

# 含禁词子串但属正当叙事的整词白名单（design.md 风险节：误报逐条评审后入常量）
BANNED_WHITELIST = (
    "实战经验",
    "经验丰富",
    "经验之谈",
    "既定目标",
)

# 数值承诺：百分号与阿拉伯数字（含全角）
PERCENT_RE = re.compile(r"%")
DIGIT_RE = re.compile(r"[0-9０-９]")

# 品级冠词（world-bible.md §5.1）：品级词 + 品/阶/级 作描述正文的品级描述符。
# 注：品级词作"名称冠词"（灵剑/玄铁甲/地阶功法）是 §5.1 允许的命名用法，
# 且"灵剑/玄甲"等与"飞剑/心剑/龟壳玄甲"在机器层面无法可靠区分，故只检查
# 无歧义的"X品/X阶/X级"描述符（"天品宝剑""地阶功法""凡级货色"）。
GRADE_RANK_RE = re.compile(r"[凡灵玄地天][品阶级]")

DEFAULT_MAX_LEN = 60  # design.md 开放问题：按域设限，初版统一 60 可调

# canon 四列取值域（spec content-sync-pipeline）
TONE_TIERS = ("正经", "正经+冷幽默", "玩梗灰", "平淡")
NARRATIVE_STATUSES = ("占位", "待写", "定稿")
CANON_COLS = ("canon_origin", "tone_tier", "story_hook", "narrative_status")

# canon_origin 词表（world-bible.md §2.2 六州 / §2.2 秘境 / §3.2 五宗 + 通用出处）
CANON_STATES = ("云州", "沧州", "朔州", "蛮州", "青州", "中州")
CANON_SECTS = (
    "青云门",
    "金刚寺",
    "天机阁",
    "万毒门",
    "血魔宗",
    "合欢宗",
    "散修",
    "妖域",
    "凡人江湖",
)
CANON_RIFTS = ("青云秘境", "落日峡谷", "万妖洞", "玄冰地宫", "上古遗迹", "青云剑冢")
CANON_REGIONS = ("青云山",)
CANON_GENERIC = ("散修日常", "上古遗宝", "传承之地", "现有配置", "原创")
CANON_NAMES = CANON_STATES + CANON_SECTS + CANON_RIFTS + CANON_REGIONS

# canon_origin 组分分隔符（"云州·青云山" 拆为 [云州, 青云山] 逐个查证）
_ORIGIN_SEP_RE = re.compile(r"[·•・/、,，\s]+")


def _load_csv(filename: str) -> list[dict]:
    """Load a content-design CSV into a list of dict rows."""
    with (DESIGN_DIR / filename).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> dict | list:
    """Load a config JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _severity(status: str, narrative_status: str, strict: bool) -> str:
    """Map a violation to FAIL/WARN per the narrative-status gate.

    Args:
        status: The numeric design status column (``draft``/``final``/``legacy``).
        narrative_status: The canon ``narrative_status`` column.
        strict: Whether ``--strict`` (placeholder rows also FAIL) is set.

    Returns:
        ``"FAIL"`` or ``"WARN"``.
    """
    if status == "legacy":
        return "WARN"  # 参照行：与 validate_budget.py 一致，不计 FAIL
    if narrative_status == "定稿":
        return "FAIL"
    return "FAIL" if strict else "WARN"


def _origin_registered(origin: str) -> bool:
    """Return True when a canon_origin is traceable to the bible vocabulary.

    规则（spec 出处不可查证场景）：非空 origin 要么是 bible 认可的通用出处类
    （散修日常 / 上古遗宝 / 传承之地 …），要么按分隔符拆成组分后每一组分都在
    州域/宗门/秘境/区域名词表内（"云州·青云山" ✓，"云州·落星湖" ✗）。
    """
    if not origin:
        return False
    if origin in CANON_GENERIC:
        return True
    registered = set(CANON_NAMES) | set(CANON_GENERIC)
    parts = [p for p in _ORIGIN_SEP_RE.split(origin) if p]
    return bool(parts) and all(p in registered for p in parts)


def _text_violations(text: str, max_len: int) -> list[str]:
    """Return human-readable violations for a description text (empty = clean).

    Args:
        text: The description body to check.
        max_len: The description length cap.

    Returns:
        List of violation detail strings.
    """
    if not text:
        return []
    problems = []
    sanitized = text
    for phrase in BANNED_WHITELIST:
        sanitized = sanitized.replace(phrase, "")
    for word in BANNED_WORDS:
        if word in sanitized:
            problems.append(f"含禁词「{word}」")
    if PERCENT_RE.search(text):
        problems.append("含百分号（数值承诺）")
    if DIGIT_RE.search(text):
        problems.append("含阿拉伯数字（数值承诺）")
    if len(text) > max_len:
        problems.append(f"长度 {len(text)} 字超上限 {max_len}")
    m = GRADE_RANK_RE.search(text)
    if m:
        problems.append(f"品级冠词「{m.group(0)}」进正文")
    return problems


def _id_name_map_from_list(cfg: list) -> dict[str, str]:
    """Build {id: name} from a flat config list keyed by id/name."""
    return {str(e.get("id", "")): e.get("name", "") for e in cfg if isinstance(e, dict)}


def _load_name_maps() -> dict[str, dict[str, str]]:
    """Load config id/key → name maps for every canon domain."""
    maps: dict[str, dict[str, str]] = {}
    # weapons.json（list）
    maps["weapons"] = _id_name_map_from_list(_load_json(CONFIG_DIR / "weapons.json"))
    # heart_methods.json（dict["心法列表"]）
    hearts = _load_json(CONFIG_DIR / "heart_methods.json")
    maps["heart_methods"] = _id_name_map_from_list(hearts.get("心法列表", []))
    # skills.json（dict[group → list]）
    skills_cfg = _load_json(CONFIG_DIR / "skills.json")
    skill_map: dict[str, str] = {}
    for entries in skills_cfg.values():
        skill_map.update(_id_name_map_from_list(entries))
    maps["skills"] = skill_map
    # adventure_config.json event_groups（dict[group → list]，按 key）
    adv = _load_json(CONFIG_DIR / "adventure_config.json")
    event_map: dict[str, str] = {}
    for group, events in adv.get("event_groups", {}).items():
        for ev in events:
            event_map[str(ev.get("key", ""))] = ev.get("name", "")
    maps["events"] = event_map
    # enemies.json templates（list of groups，按 key）
    en = _load_json(CONFIG_DIR / "enemies.json")
    enemy_map: dict[str, str] = {}
    for group in en.get("enemy_groups", []):
        for tpl in group.get("templates", []):
            enemy_map[str(tpl.get("key", ""))] = tpl.get("name", "")
    maps["enemies"] = enemy_map
    # rift_config.json rifts（id 为 int，统一 str 比较）
    rift = _load_json(CONFIG_DIR / "rift_config.json")
    maps["rifts"] = {
        str(r.get("id", "")): r.get("name", "") for r in rift.get("rifts", [])
    }
    return maps


def _check_name_consistency(
    rows: list[dict],
    table: str,
    name_map: dict[str, str],
    id_field: str,
    results: list[str],
) -> None:
    """Check canon 表 name 列 vs config 同 id/key 条目 name（不一致即 FAIL）。"""
    for r in rows:
        cid = str(r.get(id_field, "")).strip()
        cname = (r.get("name") or "").strip()
        cfg_name = name_map.get(cid)
        if cfg_name is None:
            continue  # 新增条目（config 无此 id），同步时会 append，无一致性问题
        if cname != cfg_name:
            status = (r.get("status") or "").strip()
            verdict = "WARN" if status == "legacy" else "FAIL"
            results.append(
                f"{verdict} {table}.csv[{cid}] 名字不一致：CSV「{cname}」"
                f" vs config「{cfg_name}」"
            )


def _check_canon_columns(rows: list[dict], table: str, results: list[str]) -> None:
    """Check canon 四列存在性、取值域与 canon_origin 可查证性（task 4.2）。"""
    missing_cols = [c for c in CANON_COLS if c not in (rows[0] if rows else {})]
    if missing_cols:
        results.append(f"FAIL {table}.csv 缺 canon 列 {sorted(missing_cols)}")
        return
    for r in rows:
        cid = str(r.get("id") or r.get("key") or "").strip()
        status = (r.get("status") or "").strip()
        narrative = (r.get("narrative_status") or "").strip()
        tone = (r.get("tone_tier") or "").strip()
        origin = (r.get("canon_origin") or "").strip()
        if tone not in TONE_TIERS:
            verdict = "WARN" if status == "legacy" else "FAIL"
            results.append(
                f"{verdict} {table}.csv[{cid}] tone_tier 非法取值「{tone or '（空）'}」"
                f"（允许 {TONE_TIERS}）"
            )
        if narrative and narrative not in NARRATIVE_STATUSES:
            verdict = "WARN" if status == "legacy" else "FAIL"
            results.append(
                f"{verdict} {table}.csv[{cid}] narrative_status 非法取值「{narrative}」"
                f"（允许 {NARRATIVE_STATUSES}）"
            )
        if not origin:
            # 空 canon_origin 只 WARN 不 FAIL（design.md 风险节：允许渐进回填）
            results.append(f"WARN {table}.csv[{cid}] canon_origin 为空（允许渐进回填）")
        elif not _origin_registered(origin):
            verdict = "WARN" if status == "legacy" else "FAIL"
            results.append(
                f"{verdict} {table}.csv[{cid}] canon_origin「{origin}」未在 bible 登记"
                f"（州域/宗门/秘境名词表或通用出处类）"
            )


def _check_description(
    rows: list[dict],
    table: str,
    results: list[str],
    strict: bool,
    max_len: int,
) -> None:
    """Run text checks on a canon 表 description 列（占位/定稿按严重度门禁）。"""
    for r in rows:
        cid = str(r.get("id") or r.get("key") or "").strip()
        desc = (r.get("description") or "").strip()
        status = (r.get("status") or "").strip()
        narrative = (r.get("narrative_status") or "").strip()
        for problem in _text_violations(desc, max_len):
            verdict = _severity(status, narrative, strict)
            results.append(f"{verdict} {table}.csv[{cid}] description {problem}")
        if narrative in ("占位", "待写") or not narrative:
            results.append(
                f"WARN {table}.csv[{cid}] narrative_status={narrative or '（空）'}，叙事待写"
            )


def _check_config_descriptions(strict: bool, max_len: int) -> list[str]:
    """Scan config-only description fields（events/enemies/bounty/routes）。

    这些域 description 文本只活在 config（design D2），按对应 canon 表的
    narrative_status 定严重度；无 canon 表的路由/悬赏按"占位"处理。
    """
    results: list[str] = []

    # events narrative_status lookup（key → narrative_status）
    event_status: dict[str, str] = {}
    try:
        for r in _load_csv("events-canon.csv"):
            event_status[str(r.get("key", "")).strip()] = (
                r.get("narrative_status") or ""
            ).strip()
    except FileNotFoundError:
        pass

    adv = _load_json(CONFIG_DIR / "adventure_config.json")
    for route in adv.get("routes", []):
        for problem in _text_violations(
            (route.get("description") or "").strip(), max_len
        ):
            results.append(
                f"WARN adventure_config.json routes[{route.get('key')}] {problem}"
            )
    for group, events in adv.get("event_groups", {}).items():
        for ev in events:
            narrative = event_status.get(str(ev.get("key", "")), "占位")
            sev = "FAIL" if narrative == "定稿" else ("FAIL" if strict else "WARN")
            for problem in _text_violations((ev.get("desc") or "").strip(), max_len):
                results.append(
                    f"{sev} adventure_config.json event_groups.{group}.{ev.get('key')} {problem}"
                )

    # enemies narrative_status lookup（key → narrative_status）
    enemy_status: dict[str, str] = {}
    try:
        for r in _load_csv("enemies-canon.csv"):
            enemy_status[str(r.get("key", "")).strip()] = (
                r.get("narrative_status") or ""
            ).strip()
    except FileNotFoundError:
        pass

    en = _load_json(CONFIG_DIR / "enemies.json")
    for group in en.get("enemy_groups", []):
        for problem in _text_violations(
            (group.get("description") or "").strip(), max_len
        ):
            results.append(
                f"WARN enemies.json {group.get('key')}.description {problem}"
            )
        for tpl in group.get("templates", []):
            narrative = enemy_status.get(str(tpl.get("key", "")), "占位")
            sev = "FAIL" if narrative == "定稿" else ("FAIL" if strict else "WARN")
            for problem in _text_violations(
                (tpl.get("description") or "").strip(), max_len
            ):
                results.append(
                    f"{sev} enemies.json {group.get('key')}.{tpl.get('key')} {problem}"
                )

    # bounty_templates（无 canon 表，按"占位"处理）
    bounty = _load_json(CONFIG_DIR / "bounty_templates.json")
    for tpl in bounty.get("templates", []):
        for problem in _text_violations(
            (tpl.get("description") or "").strip(), max_len
        ):
            results.append(
                f"WARN bounty_templates.json templates[{tpl.get('id')}] {problem}"
            )

    return results


def main() -> int:
    """Run all narrative lint checks and print a report. Returns exit code."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="占位/待写行违例也计 FAIL（写作期全量自检）",
    )
    parser.add_argument(
        "--max-len",
        type=int,
        default=DEFAULT_MAX_LEN,
        help=f"描述长度上限（默认 {DEFAULT_MAX_LEN}）",
    )
    args = parser.parse_args()
    max_len = args.max_len

    name_maps = _load_name_maps()
    all_lines: list[str] = []

    # 有 description 列的 canon 表：canon 列 + 名字一致 + 文本检查
    desc_tables = (
        ("weapons.csv", "weapons", "id"),
        ("skills.csv", "skills", "id"),
        ("heart_methods.csv", "heart_methods", "id"),
    )
    # 无 description 列的 canon 表：canon 列 + 名字一致
    canon_tables = (
        ("events-canon.csv", "events", "key"),
        ("enemies-canon.csv", "enemies", "key"),
        ("rifts-canon.csv", "rifts", "id"),
    )

    for filename, table, id_field in desc_tables:
        rows = _load_csv(filename)
        print(f"\n== {filename} ({len(rows)} rows) ==")
        lines: list[str] = []
        _check_canon_columns(rows, table, lines)
        _check_name_consistency(rows, table, name_maps[table], id_field, lines)
        _check_description(rows, table, lines, args.strict, max_len)
        all_lines.extend(lines)
        for line in lines:
            print(" ", line)

    for filename, table, id_field in canon_tables:
        rows = _load_csv(filename)
        print(f"\n== {filename} ({len(rows)} rows) ==")
        lines: list[str] = []
        _check_canon_columns(rows, table, lines)
        _check_name_consistency(rows, table, name_maps[table], id_field, lines)
        all_lines.extend(lines)
        for line in lines:
            print(" ", line)

    print("\n== config description 字段（events/enemies/bounty/routes） ==")
    config_lines = _check_config_descriptions(args.strict, max_len)
    all_lines.extend(config_lines)
    for line in config_lines:
        print(" ", line)

    fails = sum(line.startswith("FAIL") for line in all_lines)
    warns = sum(line.startswith("WARN") for line in all_lines)
    print(f"\nSummary: {fails} FAIL, {warns} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
