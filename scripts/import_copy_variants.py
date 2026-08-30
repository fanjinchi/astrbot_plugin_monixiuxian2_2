#!/usr/bin/env python3
"""灌入剧本册到 copy_variants.csv（season-1-tier1-copywriting tasks 5.5）。

解析 design_docs/剧情/ 下 12 册定稿剧本的 `#### {key}-{NN}｜...` 帧标题与正文，
按 scene_key_registry.md 的场景键映射为 copy_variants.csv 设计表行
（设计框架见 design.md D1/D5），供 lint_narrative.py 闸门扫描。

帧标题格式（各册一致，元数据以「 · 」分隔）：
- 突破册:   帧名 · 段位(练气/筑基/金丹/元婴/全段通用) · 路线(灵修/体修) · tone
- 修炼册:   帧名 · 段位(练气-筑基/金丹-元婴/通用) · tone
- 战斗册:   帧名 · tone（无段位 → 通用）
- 事件册通帧: 帧名 · 段位(练气-筑基/金丹-元婴/全段通用) · tone
- 事件册州条(册1-4): 州名 · 帧名（首段为州名 → state=州、tone=册头档位→见
  BOOK_TONE，逐帧标题无 tone 位）
- 事件册州条(册5-9): 据点帧名 · tone（首段非州名 → state=本宗州、tone=第二段）

归一规则：
- 键名：MD 连字符形（pity-hint/lose-streak/comprehend-success/weapon-drop 等）
  → scene_key_registry 下划线键；其余键原样。
- tone：冷幽默→正经+冷幽默；「玩梗灰（血魔宗彩蛋）」剥括号→玩梗灰；剥
  「（样张 X.Y 基准）」标注；death 帧「留命出路」→正经（子类语义留在帧名里）。
- 段位：「全段通用」→通用；其余原样（须在 LEVEL_BANDS 合法集）。
- group：散修/突破/修炼/战斗 → 空；事件册 5-9 → sect_qingyun/sect_jingang/
  sect_tianji/sect_wandu/sect_xuemo（design D5 组属性先行登记，config 立组随
  bd n6o）。四宗与青云门同源 scene key，group 列使 variant_no 唯一性按
  (domain, scene, group) 判定，避免跨组重复 FAIL。
- 正文：帧标题后连续非空行（跳过 `>` 引用块），剥行尾「（样张 X.Y 基准帧）」
  标注，段落以换行拼接为 text；narrative_status=定稿、note=帧名。

Usage:
    uv run python scripts/import_copy_variants.py
"""

import csv
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
STORY_DIR = SCRIPT_DIR / "design_docs" / "剧情"
CSV_PATH = SCRIPT_DIR / "design_docs" / "content-design" / "copy_variants.csv"

# 六州（与 lint STATES 一致，州条判别与 state 取值共用）
STATES = ("云州", "沧州", "朔州", "蛮州", "青州", "中州")
ROUTES = ("灵修", "体修", "通用")
TONE_TIERS = ("正经", "正经+冷幽默", "玩梗灰", "平淡")
LEVEL_BANDS = ("通用", "练气", "筑基", "金丹", "元婴", "练气-筑基", "金丹-元婴")

# 帧标题元数据（冒号前=行内元数据段名，仅作可读性注释，不参与解析）

# key 归一表：MD 标题连字符键 → scene_key_registry 登记键
KEY_RENAME = {
    "pity-hint": "pity_hint",
    "lose-streak": "lose_streak_reward",
    "comprehend-success": "comprehend_success",
    "comprehend-fail": "comprehend_fail",
    "comprehend-universal": "comprehend_universal",
    "weapon-drop": "weapon_drop",
    "heart-method-drop": "heart_method_drop",
    "pill-drop": "pill_drop",
}

# 键 → 域（01 突破册横跨 breakthrough + fortune，按键划分）
KEY_DOMAIN = {
    "weapon_drop": "fortune",
    "heart_method_drop": "fortune",
    "pill_drop": "fortune",
}

# 事件册文件顺序与组属性（文件序号 → group；散修册留空）
EVENT_BOOKS = [
    ("04-历练事件剧本-1-安逸日常篇.md", ""),
    ("04-历练事件剧本-2-行路遇险篇.md", ""),
    ("04-历练事件剧本-3-血火机缘篇.md", ""),
    ("04-历练事件剧本-4-危局求生篇.md", ""),
    ("04-历练事件剧本-5-宗门篇.md", "sect_qingyun"),
    ("04-历练事件剧本-6-金刚寺篇.md", "sect_jingang"),
    ("04-历练事件剧本-7-天机阁篇.md", "sect_tianji"),
    ("04-历练事件剧本-8-万毒门篇.md", "sect_wandu"),
    ("04-历练事件剧本-9-血魔宗篇.md", "sect_xuemo"),
]
# 宗门组本宗州（state 落本宗州，不落他州）
SECT_STATE = {
    "sect_qingyun": "云州",
    "sect_jingang": "朔州",
    "sect_tianji": "云州",
    "sect_wandu": "蛮州",
    "sect_xuemo": "沧州",
}
# 册1-4 州条无 tone 位 → 各事件 tone 档位（册头 tone 总览）
# 注：通用帧标题带 tone 位，州条继承同一事件档位；若通用帧 tone 与其冲突，
# 以册头总览为准（事件域 tone 是事件级属性，导入任务按事件消费）。
BOOK_TONE = {  # scene → tone_tier（散修册 11 事件）
    "herb_bloom": "正经",
    "travel_insight": "正经",
    "ally_help": "正经+冷幽默",
    "steady_path": "正经",
    "beast_skirmish": "正经",
    "secret_cache": "正经",
    "blood_battle": "正经",
    "ancient_trial": "正经",
    "trade_windfall": "玩梗灰",
    "ambush_fail": "正经",
    "lost_in_fog": "正经",
}

FRAME_RE = re.compile(r"^####\s+(.+?)\s*$")
KEY_NO_RE = re.compile(r"^(.*?)-(\d{2})$")
# 剥「（样张 8.1 基准帧）」「（样张 8.8 基准）」「（血魔宗彩蛋）」等尾标注
PAREN_TAIL_RE = re.compile(r"（[^）]*）$")


def normalize_tone(value: str) -> str:
    """归一帧标题 tone 位为 TONE_TIERS 合法值。"""
    value = value.strip()
    value = PAREN_TAIL_RE.sub("", value).strip()  # 剥「（样张 …）」等尾标注
    if value == "冷幽默":
        return "正经+冷幽默"
    if value == "留命出路":  # death 帧子类标记，实际 tone 正经
        return "正经"
    if value not in TONE_TIERS:
        raise ValueError(f"非法 tone「{value}」")
    return value


def normalize_band(value: str) -> str:
    """归一帧标题段位位为 LEVEL_BANDS 合法值（全段通用→通用）。"""
    value = value.strip()
    if value == "全段通用":
        return "通用"
    if value not in LEVEL_BANDS:
        raise ValueError(f"非法段位「{value}」")
    return value


def parse_book(path: Path, domain: str, group: str) -> list[dict]:
    """解析一册剧本为 copy_variants 行列表。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict] = []
    i = 0
    while i < len(lines):
        m = FRAME_RE.match(lines[i])
        if not m:
            i += 1
            continue
        header = m.group(1)
        key_no_m = KEY_NO_RE.match(header.split("｜", 1)[0])
        if not key_no_m:
            raise ValueError(f"{path.name}:{i + 1} 标题缺编号「{header}」")
        key = KEY_RENAME.get(key_no_m.group(1), key_no_m.group(1))
        variant_no = key_no_m.group(2)
        variant_start = i + 1
        meta = header.split("｜", 1)[1].split(" · ") if "｜" in header else []
        # 帧正文：标题后连续非空行，至下一个 ####/###/## 或文件尾
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not re.match(r"^#{2,4}\s", lines[j]):
            line = lines[j].strip()
            if line and not line.startswith(">"):
                body.append(PAREN_TAIL_RE.sub("", line))
            j += 1
        i = j
        text = "\n".join(body).strip()
        if not text:
            raise ValueError(f"{path.name}:{key}-{variant_no} 正文为空")

        row = {
            "domain": domain,
            "scene": key,
            "variant_no": variant_no,
            "text": text,
            "narrative_status": "定稿",
            "group": group,
        }
        # 州条判别：首段为州名 → 散修册州条（state=州，tone=册头档位）
        if meta and meta[0] in STATES:
            if not meta[1]:
                raise ValueError(
                    f"{path.name}:{variant_start}:{key}-{variant_no} 州条缺帧名"
                )
            row.update(
                level_band="通用",
                state=meta[0],
                route="通用",
                tone_tier=BOOK_TONE.get(key) or "正经",
                note=meta[1],
            )
        elif len(meta) == 4:  # 突破册：帧名 · 段位 · 路线 · tone
            route = meta[2]
            if route not in ROUTES:
                raise ValueError(
                    f"{path.name}:{variant_start}:{key}-{variant_no} 非法路线「{route}」"
                )
            row.update(
                level_band=normalize_band(meta[1]),
                state="通用",
                route=route,
                tone_tier=normalize_tone(meta[3]),
                note=meta[0],
            )
        elif len(meta) == 3:  # 修炼册 / 事件册通帧：帧名 · 段位 · tone
            row.update(
                level_band=normalize_band(meta[1]),
                state="通用",
                route="通用",
                tone_tier=normalize_tone(meta[2]),
                note=meta[0],
            )
        elif len(meta) == 2 and group:  # 宗门册州条：据点帧名 · tone（首段非州名）
            row.update(
                level_band="通用",
                state=SECT_STATE[group],
                route="通用",
                tone_tier=normalize_tone(meta[1]),
                note=meta[0],
            )
        elif len(meta) == 2:  # 战斗册：帧名 · tone（无段位 → 通用）
            row.update(
                level_band="通用",
                state="通用",
                route="通用",
                tone_tier=normalize_tone(meta[1]),
                note=meta[0],
            )
        else:
            raise ValueError(
                f"{path.name}:{variant_start}:{key}-{variant_no} 标题元数据异常「{header}」"
            )
        rows.append(row)
    return rows


def check_rows(rows: list[dict]) -> None:
    """全表结构性校验：变体号按 (domain, scene, group) 连续无重复。"""
    seen: dict[tuple[str, str, str], list[str]] = {}
    for r in rows:
        seen.setdefault((r["domain"], r["scene"], r["group"]), []).append(
            r["variant_no"]
        )
    for (domain, scene, group), nos in sorted(seen.items()):
        expect = [f"{n:02d}" for n in range(1, len(nos) + 1)]
        if nos != expect:
            raise ValueError(
                f"{domain}.{scene}({group or '散修'}) 编号 {nos} 不连续（期望 {expect}）"
            )


def main() -> int:
    """Run the import; exit 0 on success."""
    rows: list[dict] = []
    for filename, group in EVENT_BOOKS:
        rows.extend(parse_book(STORY_DIR / filename, "adventure_event", group))
    # 突破册：success/death/survive/revive/pity_hint/lose_streak_reward/
    # comprehend_* → breakthrough；weapon/heart-method/pill-drop → fortune
    rows.extend(parse_book(STORY_DIR / "01-突破剧本.md", "breakthrough", ""))
    # fortune 键按 KEY_DOMAIN 归域（无领域字段的键在 breakthrough 域）
    for r in rows:
        r["domain"] = KEY_DOMAIN.get(r["scene"], r["domain"])
    rows.extend(parse_book(STORY_DIR / "02-修炼结算剧本.md", "cultivation", ""))
    rows.extend(parse_book(STORY_DIR / "03-战斗说书人剧本.md", "combat", ""))
    check_rows(rows)

    # 已有数据行时拒绝覆盖（本脚本只从空表/表头表起步）
    existing = list(csv.DictReader(CSV_PATH.open(encoding="utf-8", newline="")))
    data_rows = [r for r in existing if any((r.get(c) or "").strip() for c in r)]
    if data_rows:
        print(f"错误：copy_variants.csv 已有 {len(data_rows)} 数据行，拒绝覆盖")
        return 1

    header = [
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
    ]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)

    by_domain: dict[str, int] = {}
    for r in rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    print(f"灌入完成：共 {len(rows)} 行 → {CSV_PATH}")
    print("  分域：", "，".join(f"{k} {v}" for k, v in sorted(by_domain.items())))
    groups = sorted({r["group"] for r in rows if r["group"]})
    print("  组属性：", "，".join(groups) if groups else "（无）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
