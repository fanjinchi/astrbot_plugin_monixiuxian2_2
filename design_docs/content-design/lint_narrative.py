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
- 叙事待写：``narrative_status`` 为占位/待写/空的行恒 WARN（含无 description 的
  轻量 canon 表），让回填进度在基线 WARN 数中可见

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

# copy_variants.csv 变体设计表（season-1-tier1-copywriting tasks 1.1/1.2）
COPY_VARIANTS_COLS = (
    "domain",
    "scene",
    "level_band",
    "state",
    "route",
    "variant_no",
    "text",
    "tone_tier",
    "narrative_status",
    "note",
    "group",
)
# domain：四域 + 机缘（tasks 2.4 fortune 节场景）+ 事件域；事件域 scene = 事件 key
DOMAINS = ("breakthrough", "cultivation", "combat", "fortune", "adventure_event")
# level_band：境界段分桶键 + 事件帧区间值（区间导入时展开到两桶，不倍增文本）
LEVEL_BANDS = ("通用", "练气", "筑基", "金丹", "元婴", "练气-筑基", "金丹-元婴")
# 长度上限按域参数化：突破/战斗/修炼/机缘短句，事件长句（proposal 分档约定）
# 数值以 12 册定稿剧本实测分布校准（tasks 5.5 灌入后）：突破帧三拍结构
# 上限 104、机缘 111、事件域 180（灌入前 60/120 按单句预估，与成稿冲突，
# 保留“短句域<事件域”的分档语义，数值按各域实测 max 取整）
DOMAIN_MAX_LEN = {
    "breakthrough": 120,
    "cultivation": 80,
    "combat": 80,
    "fortune": 120,
    "adventure_event": 180,
}

_WHITELIST_VAR_RE = re.compile(r"\{([a-zA-Z_0-9]+)\}")

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

# copy_variants.csv 取值域（见 lint_narrative.py 顶部注释）
STATES = CANON_STATES + ("通用",)  # 六州 + 通用（非地域文案）
ROUTES = ("灵修", "体修", "通用")

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
    # bounty_templates.json templates（id 为 int，统一 str 比较）
    bounty = _load_json(CONFIG_DIR / "bounty_templates.json")
    maps["bounty"] = {
        str(t.get("id", "")): t.get("name", "") for t in bounty.get("templates", [])
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


def _check_narrative_backlog(rows: list[dict], table: str, results: list[str]) -> None:
    """Emit a backlog WARN for rows whose narrative is not yet written.

    无 description 列的轻量 canon 表不走 ``_check_description``（那里有同款
    WARN），在此单独登记，让回填进度体现在基线 WARN 数中。
    """
    for r in rows:
        cid = str(r.get("id") or r.get("key") or "").strip()
        narrative = (r.get("narrative_status") or "").strip()
        if narrative in ("占位", "待写") or not narrative:
            results.append(
                f"WARN {table}.csv[{cid}] narrative_status={narrative or '（空）'}，叙事待写"
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
    narrative_status 定严重度；无 canon 表的路由按"占位"处理。
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

    # bounty_templates narrative_status lookup（id → narrative_status）
    bounty_status: dict[str, str] = {}
    try:
        for r in _load_csv("bounty-canon.csv"):
            bounty_status[str(r.get("id", "")).strip()] = (
                r.get("narrative_status") or ""
            ).strip()
    except FileNotFoundError:
        pass

    bounty = _load_json(CONFIG_DIR / "bounty_templates.json")
    for tpl in bounty.get("templates", []):
        narrative = bounty_status.get(str(tpl.get("id", "")), "占位")
        sev = "FAIL" if narrative == "定稿" else ("FAIL" if strict else "WARN")
        for problem in _text_violations(
            (tpl.get("description") or "").strip(), max_len
        ):
            results.append(
                f"{sev} bounty_templates.json templates[{tpl.get('id')}] {problem}"
            )

    return results


def _load_var_whitelist() -> dict[str, set[str]]:
    """Build {domain.scene: set(var)} from runtime narrative templates.

    scene key 登记表（tasks 1.4）的运行时事实源：narrative_config.json 各
    场景模板的 ``{var}`` 插值 + adventure_config 事件 desc（静态文本，白名单
    多为空）。事件域 scene 用事件 key；四宗组复用同源 key（config 立组随
    bd n6o，未登记前 lint 按未知 scene WARN 提示）。
    """
    whitelist: dict[str, set[str]] = {}
    try:
        narr = _load_json(CONFIG_DIR / "narrative_config.json")
    except FileNotFoundError:
        narr = {}
    for domain, scenes in narr.items():
        if not isinstance(scenes, dict):
            continue
        for scene, tpl in scenes.items():
            if isinstance(tpl, str):
                whitelist[f"{domain}.{scene}"] = set(_WHITELIST_VAR_RE.findall(tpl))
    try:
        adv = _load_json(CONFIG_DIR / "adventure_config.json")
    except FileNotFoundError:
        adv = {}
    for events in adv.get("event_groups", {}).values():
        for ev in events:
            key = str(ev.get("key", "")).strip()
            if key:
                whitelist[f"adventure_event.{key}"] = set(
                    _WHITELIST_VAR_RE.findall(ev.get("desc") or "")
                )
    return whitelist


def _check_copy_variants(rows: list[dict], results: list[str], strict: bool) -> None:
    """Check copy_variants.csv：取值域 / 域长度 / 禁词 / {var} 白名单 / 编号唯一。

    无 status 列（design D1），严重度仅按 narrative_status 定档：定稿行违例
    → FAIL；占位/待写 → WARN（--strict 时也 FAIL）；仅有表头（未填充）→
    WARN 提示写作期渐进。
    """
    if not rows:
        results.append("WARN copy_variants.csv 仅有表头（写作填充后自动通过）")
        return
    missing_cols = [c for c in COPY_VARIANTS_COLS if c not in rows[0]]
    if missing_cols:
        results.append(f"FAIL copy_variants.csv 缺列 {sorted(missing_cols)}")
        return
    whitelist = _load_var_whitelist()
    seen_variants: dict[tuple[str, str, str], set[str]] = {}
    for i, r in enumerate(rows, start=2):
        domain = (r.get("domain") or "").strip()
        scene = (r.get("scene") or "").strip()
        text = (r.get("text") or "").strip()
        status = (r.get("narrative_status") or "").strip()
        where = f"copy_variants.csv:{i} [{domain}.{scene}]"
        # 严重度定档：定稿行违例必 FAIL；占位/待写仅 --strict 时 FAIL
        verdict = "FAIL" if status == "定稿" else ("FAIL" if strict else "WARN")

        if domain not in DOMAINS:
            results.append(
                f"FAIL {where} domain 非法取值「{domain or '（空）'}」（允许 {DOMAINS}）"
            )
            continue
        if not scene:
            results.append(f"{verdict} {where} scene 为空")
            continue
        level_band = (r.get("level_band") or "").strip()
        if level_band not in LEVEL_BANDS:
            results.append(
                f"{verdict} {where} level_band 非法取值「{level_band or '（空）'}」"
                f"（允许 {LEVEL_BANDS}）"
            )
        state = (r.get("state") or "").strip()
        if state not in STATES:
            results.append(
                f"{verdict} {where} state 非法取值「{state or '（空）'}」（允许 {STATES}）"
            )
        route = (r.get("route") or "").strip()
        if route not in ROUTES:
            results.append(
                f"{verdict} {where} route 非法取值「{route or '（空）'}」（允许 {ROUTES}）"
            )
        tone = (r.get("tone_tier") or "").strip()
        if tone not in TONE_TIERS:
            results.append(
                f"{verdict} {where} tone_tier 非法取值「{tone or '（空）'}」"
                f"（允许 {TONE_TIERS}）"
            )
        if status not in NARRATIVE_STATUSES:
            results.append(
                f"{verdict} {where} narrative_status 非法取值「{status or '（空）'}」"
                f"（允许 {NARRATIVE_STATUSES}）"
            )

        # 编号唯一性：同 domain.scene.group 内 variant_no 不得重复（对应剧本编号
        # 01-11；group 列承载组属性，四宗与青云门同源 scene key 借此分离）
        variant_no = (r.get("variant_no") or "").strip()
        group = (r.get("group") or "").strip()
        if variant_no:
            seen = seen_variants.setdefault((domain, scene, group), set())
            if variant_no in seen:
                results.append(
                    f"FAIL {where} variant_no「{variant_no}」重复"
                    f"（同 scene 内需唯一，组 «{group or '散修'}»）"
                )
            seen.add(variant_no)

        if not text:
            results.append(f"{verdict} {where} text 为空")
            continue
        # 脱 {var} 槽再跑文本检查：变量名含数字（{name1} 等）不应触发数字违例
        plain = _WHITELIST_VAR_RE.sub("", text)
        for problem in _text_violations(
            plain, DOMAIN_MAX_LEN.get(domain, DEFAULT_MAX_LEN)
        ):
            results.append(f"{verdict} {where} text {problem}")

        # {var} 白名单：变量必须在该场景运行时模板的插值白名单内；
        # 未知 scene → WARN（回核提示，不阻塞写作期）
        wild_key = f"{domain}.{scene}"
        allowed = whitelist.get(wild_key)
        if allowed is None:
            results.append(
                f"WARN {where} scene 未在运行时模板登记（见 scene_key_registry.md；"
                "四宗组待 bd n6o 立组时登记）"
            )
        else:
            for var in _WHITELIST_VAR_RE.findall(text):
                if var not in allowed:
                    results.append(
                        f"{verdict} {where} 变量 {{{var}}} 不在「{wild_key}」白名单"
                        f"（允许 {sorted(allowed)}，见 scene_key_registry.md）"
                    )


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
    # 无 description 列的 canon 表：canon 列 + 名字一致 + 叙事待写 backlog
    canon_tables = (
        ("events-canon.csv", "events", "key"),
        ("enemies-canon.csv", "enemies", "key"),
        ("rifts-canon.csv", "rifts", "id"),
        ("bounty-canon.csv", "bounty", "id"),
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
        _check_narrative_backlog(rows, table, lines)
        all_lines.extend(lines)
        for line in lines:
            print(" ", line)

    print("\n== config description 字段（events/enemies/bounty/routes） ==")
    config_lines = _check_config_descriptions(args.strict, max_len)
    all_lines.extend(config_lines)
    for line in config_lines:
        print(" ", line)

    print("\n== copy_variants.csv（变体设计表） ==")
    variants_lines: list[str] = []
    _check_copy_variants(_load_csv("copy_variants.csv"), variants_lines, args.strict)
    all_lines.extend(variants_lines)
    for line in variants_lines:
        print(" ", line)

    fails = sum(line.startswith("FAIL") for line in all_lines)
    warns = sum(line.startswith("WARN") for line in all_lines)
    print(f"\nSummary: {fails} FAIL, {warns} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
