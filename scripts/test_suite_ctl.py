#!/usr/bin/env python3
"""Functional test suite control script for the cultivation plugin.

Commands:
  sync-cases          Deploy functional_tests/cases/**/*.json to the platform flat cases dir.
  run                 Run cases by --case or --tag, with optional --repeat N.
  export              Export recent runs into functional_tests/results/<date>_<target>/.
  fixture --profile pvp  Prepare fixed PvP test player rows in the plugin test database.

This script intentionally uses only the Python standard library (urllib/sqlite3)
and mirrors the REST calls used by the platform CLI. It never ships as game code.

Examples:
  WEBTEST_URL=http://127.0.0.1:8765 WEBTEST_TOKEN=secret \\
    uv run python scripts/test_suite_ctl.py sync-cases
  WEBTEST_URL=http://127.0.0.1:8765 WEBTEST_TOKEN=secret \\
    uv run python scripts/test_suite_ctl.py run --tag pvp --repeat 3
  WEBTEST_URL=http://127.0.0.1:8765 WEBTEST_TOKEN=secret \\
    uv run python scripts/test_suite_ctl.py export --target pvp-effects
  uv run python scripts/test_suite_ctl.py fixture --profile pvp --yes
  uv run python scripts/test_suite_ctl.py run --tag sect --fixture --fixture-profile sect
  uv run python scripts/test_suite_ctl.py fixture --profile sect --yes
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8765"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL_TESTS_DIR = PROJECT_ROOT / "functional_tests"
DISCOVERED_JSON_PATTERN = "**/*.json"
LAST_RUN_MANIFEST = FUNCTIONAL_TESTS_DIR / ".last-run.json"

PVP_TEST_IDS = ("900000001", "900000002", "900000003")

# sect profile：宗门功能用例。GM 沿用 900000001，业务玩家为 900000002
# （青云门成员预置）与 900000003（无宗门，用于反例/对照组）。
SECT_TEST_IDS = ("900000002", "900000003")
# 新建型用例使用的固定 ID（GM 指令需数字 ID 定位），fixture 每次重置为无宗门初始态。
SECT_FRESH_TEST_IDS = ("900000004", "900000005", "900000006")
SECT_FACTION_ID = "qingyun"
SECT_SECT_NAME = "青云门"
# 成员预置：贡献 2500（达标内门 2000/4 级、不达标亲传 8000/6 级）、境界 2
# （匹配 chain_qy_01 区间 [0,2]）、储物戒含宗门之宝青云镇山剑（配置带
# treasure+sect_id 标记，离宗自动回收）、已习得宗门绑定功法 qy_001。
SECT_MEMBER_PRESET = {
    "level_index": 2,
    "sect_position": 4,  # 外门弟子
    "sect_contribution": 2500,
    "storage_ring_items": {"青云镇山剑": 1, "青铜剑": 1},
    "sect_treasure_claims": ["wpn_qy_001"],
    "sect_master_progress": {
        "chain_id": "chain_qy_01",
        "stage_index": 0,
        "progress": 0,
        "done": False,
    },
}
SECT_SECT_SKILL_IDS = ("qy_001",)  # 青云剑诀：师承任务来源 + 宗门绑定
SECT_INITIAL_MATERIALS = 500  # 供建设用例升级洞天(200)+丹房(200)
# 商店种子：丹阁固定上架筑基丹（原价 5000），供折扣用例结算价格断言。
SECT_SHOP_SEED = [{"name": "筑基丹", "type": "pill", "price": 5000, "stock": 5}]

PVP_PROFILE_SKILL_IDS = (
    "common_001",  # 基础吐纳 damage_bonus
    "draft_kuangfeng",  # 狂风诀 combo
    "draft_zhenshan",  # 震山锤 stun
    "draft_yiyahuan",  # 以牙还牙 counter
    "common_002",  # 铁布衫 damage_reduction
    "verify_heal_001",  # 回春诀 heal
    "verify_vampire_001",  # 噬血剑意 vampire
    "verify_dot_001",  # 蚀骨咒 dot
    "draft_ningshen",  # 凝神诀 buff
    "draft_lingshe",  # 灵蛇缠身 debuff
    "verify_unavoidable_001",  # 破风剑意 unavoidable
    "draft_pojun",  # 破军诀 pierce
    "draft_tieji",  # 铁棘功 reflect
    "verify_survive_001",  # 涅槃诀 survive ultimate
    "verify_fatigue_001",  # 燃血诀 fatigue
    "spirit_001",  # 万剑归宗 massive_damage ultimate
    "draft_huitian",  # 回天圣手 heal ultimate
    "draft_jiuyou",  # 九幽噬魂咒 dot ultimate
)


class CtlError(Exception):
    """User-facing control script error."""


def _request(
    base: str, token: str, method: str, path: str, body=None, timeout: float = 60
) -> dict:
    """Send an HTTP JSON request to the test platform.

    Args:
        base: Platform base URL.
        token: Bearer token (may be empty).
        method: HTTP method.
        path: API path.
        body: Optional JSON-serializable payload.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON response.

    Raises:
        CtlError: On HTTP/connection errors.
    """
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("error", "")
        except Exception:
            pass
        raise CtlError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CtlError(
            f"无法连接测试平台（{exc.reason}），请确认已启用 webtest 平台"
        ) from exc


def _wait_run(base: str, token: str, run_id: int, timeout: float = 600.0) -> dict:
    """Poll GET /api/runs/{id} until the run reaches a terminal state.

    Args:
        base: Platform base URL.
        token: Bearer token.
        run_id: Run id.
        timeout: Total polling timeout in seconds.

    Returns:
        The terminal run record.

    Raises:
        CtlError: On timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        run = _request(base, token, "GET", f"/api/runs/{run_id}")
        if run and run.get("status") != "running":
            return run
        if time.monotonic() > deadline:
            raise CtlError(f"运行 {run_id} 超时未结束")
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# sync-cases
# ---------------------------------------------------------------------------


def _validate_case(case: dict, path: Path) -> None:
    """Validate a case object against the platform loader contract.

    Args:
        case: Parsed case JSON.
        path: Source file path used in error messages.

    Raises:
        CtlError: If required fields are missing or ``name`` mismatches.
    """
    if not isinstance(case, dict):
        raise CtlError(f"{path}: 用例必须是 JSON 对象")
    for field in ("name", "description", "scenario", "steps"):
        if not case.get(field):
            raise CtlError(f"{path}: 缺少必填字段 {field!r}")
    if path.stem != case["name"]:
        raise CtlError(
            f"{path}: 文件名必须等于用例 name（{path.stem} != {case['name']}）"
        )
    if not isinstance(case["steps"], list) or not case["steps"]:
        raise CtlError(f"{path}: steps 必须是非空数组")
    valid_types = ("send", "expect", "expect_not", "sleep")
    for i, step in enumerate(case["steps"]):
        if not isinstance(step, dict) or step.get("type") not in valid_types:
            raise CtlError(f"{path}: steps[{i}] 缺少合法的 type 字段（{valid_types}）")
        if step["type"] == "send" and not (step.get("player") and step.get("text")):
            raise CtlError(f"{path}: steps[{i}] send 必填 player/text")
        if step["type"] in ("expect", "expect_not") and not (
            step.get("match") and step.get("timeout")
        ):
            raise CtlError(f"{path}: steps[{i}] {step['type']} 必填 match/timeout")
        if step.get("combine") is not None and not isinstance(step["combine"], bool):
            raise CtlError(f"{path}: steps[{i}].combine 必须是布尔值")
        if step["type"] == "sleep" and not (
            step.get("seconds") and step["seconds"] > 0
        ):
            raise CtlError(f"{path}: steps[{i}] sleep.seconds 必须是正数")
    if case.get("deterministic") is not None and not isinstance(
        case["deterministic"], bool
    ):
        raise CtlError(f"{path}: case.deterministic 必须是布尔值")
    if case.get("seed") is not None and (
        not isinstance(case["seed"], int) or isinstance(case["seed"], bool)
    ):
        raise CtlError(f"{path}: case.seed 必须是整数")


def _load_source_cases(cases_root: Path) -> list[tuple[str, dict, Path]]:
    """Load and validate all canonical case files under a root.

    Args:
        cases_root: Root directory to scan recursively.

    Returns:
        List of ``(name, case, path)`` tuples.

    Raises:
        CtlError: On validation or name-collision errors.
    """
    found: list[tuple[str, dict, Path]] = []
    seen: dict[str, Path] = {}
    for path in sorted(cases_root.glob(DISCOVERED_JSON_PATTERN)):
        if not path.is_file():
            continue
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CtlError(f"{path}: JSON 解析失败: {exc}") from exc
        _validate_case(case, path)
        name = case["name"]
        if name in seen:
            raise CtlError(
                f"用例 name 全局重复: {name!r} 同时出现在 {seen[name]} 与 {path}"
            )
        seen[name] = path
        found.append((name, case, path))
    if not found:
        raise CtlError(f"{cases_root}: 未找到任何 .json 用例")
    return found


def cmd_sync_cases(args: argparse.Namespace) -> int:
    """Implement ``sync-cases``: flatten canonical cases into the platform dir."""
    cases_root = Path(args.cases_root)
    platform_dir = Path(args.platform_cases_dir)
    platform_dir.mkdir(parents=True, exist_ok=True)
    found = _load_source_cases(cases_root)
    for name, case, src in found:
        dst = platform_dir / f"{name}.json"
        shutil.copyfile(src, dst)
        print(f"已同步 {name} -> {dst}")
    # metadata 文件此前用于同步追踪，平台 loader 已过滤但仍建议不写入平台目录；
    # 这里清理历史残留，后续 sync 不再生成。
    for meta in platform_dir.glob("*.meta.json"):
        meta.unlink(missing_ok=True)
    print(f"同步完成：{len(found)} 个用例已拍平到 {platform_dir}")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _select_cases(args: argparse.Namespace, base: str, token: str) -> list[dict]:
    """Select platform cases by exact name or tag.

    Args:
        args: Parsed arguments.
        base: Platform base URL.
        token: Bearer token.

    Returns:
        List of case metadata dicts as returned by GET /api/cases.
    """
    data = _request(base, token, "GET", "/api/cases")
    cases = data.get("cases") or []
    if args.case:
        matched = [c for c in cases if c["name"] == args.case]
        if not matched:
            raise CtlError(f"用例不存在: {args.case}")
        return matched
    if args.tag:
        matched = [c for c in cases if args.tag in (c.get("tags") or [])]
        if not matched:
            raise CtlError(f"没有 tag={args.tag!r} 的用例")
        return matched
    raise CtlError("请指定 --case 或 --tag")


EFFECT_EVIDENCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "damage_bonus": ("攻势更盛！",),
    "combo": ("攻势更盛！",),
    "stun": ("被眩晕，下回合无法出手",),
    "counter": ("触发【", "】反击，"),
    "damage_reduction": ("受到的伤害降低",),
    "heal": ("恢复 ", " 气血！"),
    "vampire": ("吸取 ", " 气血！"),
    "dot": ("侵蚀，损失 ", " 气血！"),
    "buff": ("的【", "】作用于 "),
    "debuff": ("的【", "】作用于 "),
    "unavoidable": ("身形一闪，躲过了",),  # Absence hint is handled separately.
    "pierce": (
        "攻击",
    ),  # Piercing has no dedicated log; it is inferred from damage vs armor.
    "reflect": ("反弹 ", " 点伤害！"),
    "survive": ("获得【", "】庇护！"),
    "fatigue": ("的【", "】作用于 "),
    "ultimate_damage": ("施展大招【", "】，天地变色！"),
    "ultimate_heal": ("施展大招【", "】，天地变色！"),
    "ultimate_dot": ("施展大招【", "】，天地变色！"),
    "ultimate_survive": ("获得【", "】庇护！"),
    "sect_event": ("🏯 宗门际遇",),
}


def _count_evidence(run: dict) -> dict[str, int]:
    """Count occurrences of known effect pattern fragments in a run record.

    Args:
        run: A platform run record containing ``steps_result``/``run_messages``.

    Returns:
        Mapping of evidence key to occurrence count (0 when not found).
    """
    texts: list[str] = []
    steps_result = run.get("steps_result") or []
    for step in steps_result:
        for actual in step.get("actual") or []:
            texts.append(actual)
    for msg in run.get("run_messages") or []:
        if isinstance(msg, dict) and msg.get("text"):
            texts.append(msg["text"])
    joined = "\n".join(texts)
    evidence: dict[str, int] = {}
    for key, fragments in EFFECT_EVIDENCE_PATTERNS.items():
        count = sum(joined.count(frag) for frag in fragments)
        if count:
            evidence[key] = count
    return evidence


def cmd_run(args: argparse.Namespace) -> int:
    """Implement ``run``: start case runs, poll, and save a local manifest."""
    cases = _select_cases(args, args.url, args.token)
    manifest_runs: list[dict] = []
    failed_runs = 0
    total_runs = len(cases) * max(1, args.repeat)
    run_index = 0
    for case in cases:
        for repeat in range(1, max(1, args.repeat) + 1):
            run_index += 1
            if args.fixture:
                fixture_args = argparse.Namespace(
                    profile=args.fixture_profile, db=args.db, yes=True
                )
                cmd_fixture(fixture_args)
            name = case["name"]
            started = _request(
                args.url,
                args.token,
                "POST",
                f"/api/cases/{urllib.parse.quote(name)}/runs",
            )
            if started.get("status") != "started" or not started.get("run"):
                raise CtlError(f"启动运行失败: {started}")
            run_id = started["run"]["id"]
            run = _wait_run(args.url, args.token, run_id)
            ok = run.get("status") == "passed"
            if not ok:
                failed_runs += 1
            evidence = _count_evidence(run)
            print(
                f"[{run_index}/{total_runs}] {name} (repeat {repeat}): "
                f"{run.get('status')}{' ✓' if ok else ' ✗'}"
            )
            if evidence:
                print(f"    证据: {evidence}")
            manifest_runs.append(
                {
                    "case_name": name,
                    "run_id": run_id,
                    "status": run.get("status"),
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "evidence": evidence,
                }
            )
    LAST_RUN_MANIFEST.write_text(
        json.dumps(
            {
                "synced_at": datetime.now().isoformat(timespec="seconds"),
                "commands": {
                    "case": args.case,
                    "tag": args.tag,
                    "repeat": args.repeat,
                },
                "runs": manifest_runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"运行清单已写入 {LAST_RUN_MANIFEST}")
    if failed_runs:
        print(f"失败运行数: {failed_runs}/{total_runs}", file=sys.stderr)
        return 1
    print(f"全部通过：{total_runs} 次运行")
    return 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _latest_runs_from_platform(
    base: str, token: str, case_names: list[str], limit_per_case: int = 1
) -> list[dict]:
    """Fetch the most recent run records for a set of cases.

    Args:
        base: Platform base URL.
        token: Bearer token.
        case_names: Case names to query.
        limit_per_case: How many recent runs to keep per case.

    Returns:
        List of run records.
    """
    runs: list[dict] = []
    for name in case_names:
        data = _request(
            base, token, "GET", f"/api/cases/{urllib.parse.quote(name)}/runs"
        )
        for run in (data.get("runs") or [])[:limit_per_case]:
            runs.append(run)
    return runs


def cmd_export(args: argparse.Namespace) -> int:
    """Implement ``export``: write a dated result folder with summary/cases/messages."""
    target = args.target or datetime.now().strftime("%H%M%S")
    run_date = args.date or date.today().isoformat()
    base_dir = FUNCTIONAL_TESTS_DIR / "results" / f"{run_date}_{target}"
    if base_dir.exists():
        base_dir = FUNCTIONAL_TESTS_DIR / "results" / f"{run_date}_{target}_2"
        suffix = 3
        while base_dir.exists():
            base_dir = (
                FUNCTIONAL_TESTS_DIR / "results" / f"{run_date}_{target}_{suffix}"
            )
            suffix += 1
    cases_dir = base_dir / "cases"
    messages_dir = base_dir / "messages"
    cases_dir.mkdir(parents=True, exist_ok=True)
    messages_dir.mkdir(parents=True, exist_ok=True)

    if LAST_RUN_MANIFEST.exists():
        manifest = json.loads(LAST_RUN_MANIFEST.read_text(encoding="utf-8"))
        run_ids = [r["run_id"] for r in manifest.get("runs", [])]
        runs = [
            _request(args.url, args.token, "GET", f"/api/runs/{rid}") for rid in run_ids
        ]
    else:
        all_cases = (
            _request(args.url, args.token, "GET", "/api/cases").get("cases") or []
        )
        runs = _latest_runs_from_platform(
            args.url, args.token, [c["name"] for c in all_cases]
        )
        if args.date:
            day_start = datetime.fromisoformat(f"{args.date}T00:00:00").timestamp()
            day_end = day_start + 86400
            runs = [
                r
                for r in runs
                if (r.get("started_at") or 0) >= day_start
                and (r.get("started_at") or 0) < day_end
            ]

    passed, failed, unstable, skipped = [], [], [], []
    for run in runs:
        name = run.get("case_name", f"run_{run.get('id')}")
        status = run.get("status", "unknown")
        if status == "passed":
            passed.append(name)
        elif status in ("failed", "error"):
            failed.append((name, run.get("id"), status))
        elif status == "skipped":
            skipped.append(name)
        else:
            unstable.append((name, run.get("id"), status))
        case_file = cases_dir / f"{name}__run{run.get('id')}.json"
        case_file.write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        run_messages = run.get("run_messages")
        if run_messages:
            msg_file = messages_dir / f"{name}__run{run.get('id')}.json"
            msg_file.write_text(
                json.dumps(run_messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    evidence_agg: dict[str, dict] = {}
    for run in runs:
        evidence = _count_evidence(run)
        if not evidence:
            continue
        name = run.get("case_name", f"run_{run.get('id')}")
        entry = evidence_agg.setdefault(name, {"total": 0, "evidence": {}})
        entry["total"] += 1
        for key, count in evidence.items():
            entry["evidence"][key] = entry["evidence"].get(key, 0) + count

    lines = [
        f"# 功能测试结果：{run_date}_{target}",
        "",
        f"- 导出时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 运行记录数：{len(runs)}",
        f"- 通过：{len(passed)}",
        f"- 失败/错误：{len(failed)}",
        f"- 不稳定：{len(unstable)}",
        f"- 跳过：{len(skipped)}",
        "",
        "## 通过用例",
        "",
    ]
    lines.extend(f"- {n}" for n in sorted(set(passed)))
    lines += ["", "## 失败/错误用例", ""]
    lines.extend(f"- {n} (run {rid}, {status})" for n, rid, status in failed)
    lines += ["", "## 不稳定用例", ""]
    lines.extend(f"- {n} (run {rid}, {status})" for n, rid, status in unstable)
    lines += ["", "## 跳过用例", ""]
    lines.extend(f"- {n}" for n in sorted(set(skipped)))
    lines += ["", "## 效果证据聚合（抽样）", ""]
    if evidence_agg:
        for name, entry in sorted(evidence_agg.items()):
            ev_str = ", ".join(f"{k}= {v}" for k, v in entry["evidence"].items())
            lines.append(f"- {name}: {ev_str}（采样 {entry['total']} 次）")
    else:
        lines.append("- 本次运行未捕获到效果证据片段。")
    lines += [
        "",
        "## 证据路径",
        "",
        "- 逐用例结果：`cases/`",
        "- 消息轨迹：`messages/`",
        "",
        "> 随机/概率效果用例使用 `--repeat` 聚合并在 summary 中记录证据强度。",
        "",
    ]
    (base_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"已导出结果到 {base_dir}")
    return 0 if not failed else 1


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------


def _default_plugin_db_path() -> Path:
    """Return the most likely plugin database path under the local AstrBot install.

    Returns:
        A Path to the default ``xiuxian_data_v2.db`` file.
    """
    home = Path.home()
    candidates = [
        home
        / "code/AstrBot/data/plugin_data/astrbot_plugin_monixiuxian2/xiuxian_data_v2.db",
        home
        / "code/AstrBot/data/plugin_data/astrbot_plugin_monixiuxian2/xiuxian_data_lite.db",
        home
        / ".astrbot/data/plugin_data/astrbot_plugin_monixiuxian2/xiuxian_data_v2.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _resolve_db_path(args: argparse.Namespace) -> Path:
    """Resolve the plugin database path argument with a helpful error if absent."""
    db = Path(args.db or _default_plugin_db_path()).expanduser()
    if not db.exists():
        raise CtlError(
            f"插件数据库不存在: {db}\n请用 --db 指定专用测试实例的数据库路径"
        )
    return db


def _backup_players(
    conn: sqlite3.Connection, ids: list[str], backup_path: Path
) -> None:
    """Back up current rows for the fixed test ids before mutation.

    Args:
        conn: Open sqlite connection.
        ids: User ids to back up.
        backup_path: Destination JSON file.
    """
    players = []
    placeholders = ",".join("?" for _ in ids)
    for row in conn.execute(
        f"SELECT * FROM players WHERE user_id IN ({placeholders})", ids
    ):
        players.append(dict(row))
    skills = []
    for row in conn.execute(
        f"SELECT * FROM player_skills WHERE user_id IN ({placeholders})", ids
    ):
        skills.append(dict(row))
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(
            {
                "backup_time": datetime.now().isoformat(timespec="seconds"),
                "players": players,
                "player_skills": skills,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"已备份现有固定 ID 数据 -> {backup_path}")


def _upsert_player(conn: sqlite3.Connection, user_id: str, user_name: str) -> None:
    """Insert or reset one fixed test player to a deterministic PvP baseline.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
        user_name: Display name.
    """
    conn.execute(
        """
        INSERT INTO players (
            user_id, user_name, level_index, spiritual_root, cultivation_type,
            lifespan, experience, gold, state, cultivation_start_time,
            last_check_in_date, level_up_rate, breakthrough_fail_streak,
            weapon, armor, main_technique, techniques,
            damage, agility, speed, hp, armor_value, study_target,
            battle_report_merge_count, sect_id, sect_position, sect_contribution,
            sect_task, sect_elixir_get, blessed_spot_flag, blessed_spot_name,
            active_pill_effects, permanent_pill_gains, has_resurrection_pill,
            has_debuff_shield, pills_inventory, storage_ring, storage_ring_items,
            daily_pill_usage, last_daily_reset
        ) VALUES (
            ?, ?, 1, '天灵根', '灵修',
            1000, 0, 100000, '空闲', 0,
            '', 0, 0,
            '', '', '', '[]',
            100, 50, 50, 1000, 0, '',
            0, 0, 4, 0,
            0, 0, 0, '',
            '[]', '{}', 0,
            0, '{}', '乾坤储物戒', ?, '{}', ''
        )
        ON CONFLICT(user_id) DO UPDATE SET
            user_name = excluded.user_name,
            level_index = excluded.level_index,
            spiritual_root = excluded.spiritual_root,
            cultivation_type = excluded.cultivation_type,
            lifespan = excluded.lifespan,
            experience = excluded.experience,
            gold = excluded.gold,
            state = excluded.state,
            cultivation_start_time = excluded.cultivation_start_time,
            last_check_in_date = excluded.last_check_in_date,
            level_up_rate = excluded.level_up_rate,
            breakthrough_fail_streak = excluded.breakthrough_fail_streak,
            weapon = excluded.weapon,
            armor = excluded.armor,
            main_technique = excluded.main_technique,
            techniques = excluded.techniques,
            damage = excluded.damage,
            agility = excluded.agility,
            speed = excluded.speed,
            hp = excluded.hp,
            armor_value = excluded.armor_value,
            study_target = excluded.study_target,
            battle_report_merge_count = excluded.battle_report_merge_count,
            sect_id = excluded.sect_id,
            sect_position = excluded.sect_position,
            sect_contribution = excluded.sect_contribution,
            sect_task = excluded.sect_task,
            sect_elixir_get = excluded.sect_elixir_get,
            blessed_spot_flag = excluded.blessed_spot_flag,
            blessed_spot_name = excluded.blessed_spot_name,
            active_pill_effects = excluded.active_pill_effects,
            permanent_pill_gains = excluded.permanent_pill_gains,
            has_resurrection_pill = excluded.has_resurrection_pill,
            has_debuff_shield = excluded.has_debuff_shield,
            pills_inventory = excluded.pills_inventory,
            storage_ring = excluded.storage_ring,
            storage_ring_items = excluded.storage_ring_items,
            daily_pill_usage = excluded.daily_pill_usage,
            last_daily_reset = excluded.last_daily_reset
        """,
        (
            user_id,
            user_name,
            json.dumps(
                {
                    "青铜剑": 1,
                    "青云天剑": 1,
                    "混元至宝鼎": 1,
                    "弑龙帝枪": 1,
                    "长春功": 1,
                    "战神诀": 1,
                    "疾风迅雷功": 1,
                },
                ensure_ascii=False,
            ),
        ),
    )


def _write_sect_skills(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert sect-bound skills for the member preset player.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
    """
    if user_id != SECT_TEST_IDS[0]:
        return
    now = int(time.time())
    for skill_id in SECT_SECT_SKILL_IDS:
        conn.execute(
            "INSERT OR REPLACE INTO player_skills "
            "(user_id, skill_id, star_level, source, learned_at, origin_sect_id, sect_bound) "
            "VALUES (?, ?, 1, 'master_task', ?, ?, 1)",
            (user_id, skill_id, now, SECT_FACTION_ID),
        )


def _apply_sect_member_preset(
    conn: sqlite3.Connection, user_id: str, sect_row_id: int | None
) -> None:
    """Apply deterministic sect-profile overrides to a fixed test player.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
        sect_row_id: The ``sects.sect_id`` of 青云门 (None when unseeded).
    """
    if user_id == SECT_TEST_IDS[0]:  # 900000002 宗门成员
        preset = SECT_MEMBER_PRESET
        if sect_row_id is None:
            raise CtlError(
                f"测试库中未找到宗门「{SECT_SECT_NAME}」——"
                "需先重载插件使 ensure_system_sects 播种默认宗门"
            )
        conn.execute(
            "UPDATE players SET level_index = ?, sect_id = ?, sect_position = ?, "
            "sect_contribution = ?, sect_treasure_claims = ?, "
            "sect_master_progress = ?, storage_ring_items = ?, level_up_rate = 100 "
            "WHERE user_id = ?",
            (
                preset["level_index"],
                sect_row_id,
                preset["sect_position"],
                preset["sect_contribution"],
                json.dumps(preset["sect_treasure_claims"], ensure_ascii=False),
                json.dumps(preset["sect_master_progress"], ensure_ascii=False),
                json.dumps(preset["storage_ring_items"], ensure_ascii=False),
                user_id,
            ),
        )
    else:  # 900000003 非成员对照
        conn.execute(
            "UPDATE players SET level_index = 1, sect_id = 0, sect_position = 4, "
            "sect_contribution = 0, sect_treasure_claims = '[]', "
            "sect_master_progress = '{}', storage_ring_items = '{}', level_up_rate = 0 "
            "WHERE user_id = ?",
            (user_id,),
        )
    # 清理旧 profile 残留的技能（如 pvp 的 18 个技能），再写本 profile 的绑定功法。
    conn.execute("DELETE FROM player_skills WHERE user_id = ?", (user_id,))
    _write_sect_skills(conn, user_id)


def _reset_fresh_player(conn: sqlite3.Connection, user_id: str) -> None:
    """Reset a fresh-type test player to a pristine, sectless state.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
    """
    conn.execute(
        "UPDATE players SET level_index = 1, sect_id = 0, sect_position = 4, "
        "sect_contribution = 0, sect_treasure_claims = '[]', "
        "sect_master_progress = '{}', storage_ring_items = '{}', level_up_rate = 0 "
        "WHERE user_id = ?",
        (user_id,),
    )
    conn.execute("DELETE FROM player_skills WHERE user_id = ?", (user_id,))
    _ensure_idle_cd(conn, user_id)


def _ensure_idle_cd(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert an idle user_cd row so busy-state writes work for a fresh player.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
    """
    # set_user_busy 只 UPDATE 不 INSERT，必须预置 idle 行，否则闭关后 user_cd 仍为空。
    conn.execute(
        "INSERT OR REPLACE INTO user_cd "
        "(user_id, type, create_time, scheduled_time, extra_data) "
        "VALUES (?, 0, 0, 0, '{}')",
        (user_id,),
    )


def _reset_sect_rows(conn: sqlite3.Connection) -> None:
    """Reset operational columns of all system (default) sects to a clean baseline.

    Only resets scale/materials/building levels; never touches names/owners
    or destroy state (``status``/``destruction_tier`` preserved).

    Args:
        conn: Open sqlite connection.
    """
    conn.execute(
        "UPDATE sects SET sect_scale = 100, sect_materials = ?, "
        "sect_fairyland = 0, elixir_room_level = 0 WHERE is_system = 1",
        (SECT_INITIAL_MATERIALS,),
    )


def _seed_shop(conn: sqlite3.Connection) -> None:
    """Seed the pill pavilion with a deterministic item for discount math.

    Args:
        conn: Open sqlite connection.
    """
    conn.execute(
        "INSERT OR REPLACE INTO shop (shop_id, last_refresh_time, current_items) "
        "VALUES ('pill_pavilion', ?, ?)",
        (int(time.time()), json.dumps(SECT_SHOP_SEED, ensure_ascii=False)),
    )


def _write_pvp_skills(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert the full set of PvP verification skill ids for one player.

    Args:
        conn: Open sqlite connection.
        user_id: Fixed test user id.
    """
    now = int(time.time())
    for skill_id in PVP_PROFILE_SKILL_IDS:
        conn.execute(
            "INSERT OR REPLACE INTO player_skills "
            "(user_id, skill_id, star_level, source, learned_at) VALUES (?, ?, 1, 'fixture', ?)",
            (user_id, skill_id, now),
        )


def _resolve_sect_row(conn: sqlite3.Connection) -> int | None:
    """Return the sects.sect_id of the default 青云门, or None.

    Args:
        conn: Open sqlite connection.

    Returns:
        The 青云门 sect_id or None when not seeded.
    """
    row = conn.execute(
        "SELECT sect_id FROM sects WHERE faction_id = ? LIMIT 1", (SECT_FACTION_ID,)
    ).fetchone()
    return int(row[0]) if row else None


def cmd_fixture(args: argparse.Namespace) -> int:
    """Implement ``fixture``: write a deterministic baseline to the test DB.

    ``pvp`` writes the PvP verification baseline; ``sect`` writes the sect
    domain baseline (member preset, sect rows, shop seed, idle cds).
    """
    db_path = _resolve_db_path(args)
    if args.profile == "pvp":
        ids = list(PVP_TEST_IDS)
    elif args.profile == "sect":
        ids = list(SECT_TEST_IDS)
    else:
        raise CtlError(f"不支持的 fixture profile: {args.profile}")
    if not args.yes:
        answer = input(
            f"即将直接写测试数据库 {db_path}（仅固定 ID {ids}）。确认继续？[y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("已取消")
            return 1

    backup_path = FUNCTIONAL_TESTS_DIR / ".fixture-backup.json"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _backup_players(conn, ids + ["900000001"], backup_path)
        names = {
            "900000001": "测试GM",
            "900000002": "测试玩家1",
            "900000003": "测试玩家2",
        }
        if args.profile == "pvp":
            for user_id in ids:
                _upsert_player(conn, user_id, names[user_id])
                _write_pvp_skills(conn, user_id)
                _ensure_idle_cd(conn, user_id)
            conn.execute("DELETE FROM combat_cooldowns WHERE user_id IN (?,?,?)", ids)
        else:  # sect
            sect_row_id = _resolve_sect_row(conn)
            for user_id in ids:
                _upsert_player(conn, user_id, names[user_id])
                _apply_sect_member_preset(conn, user_id, sect_row_id)
                _ensure_idle_cd(conn, user_id)
            for user_id in SECT_FRESH_TEST_IDS:
                _upsert_player(conn, user_id, f"测试玩家{user_id[-1]}")
                _reset_fresh_player(conn, user_id)
            conn.execute(
                "DELETE FROM combat_cooldowns WHERE user_id IN (?,?,?)", PVP_TEST_IDS
            )
            _reset_sect_rows(conn)
            _seed_shop(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"fixture {args.profile} 完成：{len(ids)} 个固定测试玩家已重置")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="修仙插件功能测试套件控制脚本",
        epilog="示例见脚本 docstring。",
    )
    parser.add_argument(
        "--url", default=os.environ.get("WEBTEST_URL", DEFAULT_URL), help="测试平台地址"
    )
    parser.add_argument(
        "--token", default=os.environ.get("WEBTEST_TOKEN", ""), help="访问令牌"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync-cases", help="同步用例到平台 cases 目录")
    sync.add_argument(
        "--cases-root",
        default=str(FUNCTIONAL_TESTS_DIR / "cases"),
        help="用例源目录（默认 functional_tests/cases）",
    )
    sync.add_argument(
        "--platform-cases-dir",
        default=str(
            Path.home()
            / "code/AstrBot/data/plugin_data/astrbot_plugin_testplatform/cases"
        ),
        help="平台顶层 cases 目录",
    )
    sync.set_defaults(func=cmd_sync_cases)

    run = sub.add_parser("run", help="运行用例（按 --case 或 --tag）")
    run.add_argument("--case", help="用例名")
    run.add_argument("--tag", help="按标签运行")
    run.add_argument("--repeat", type=int, default=1, help="每个用例重复运行次数")
    run.add_argument(
        "--fixture",
        action="store_true",
        help="每轮重复前执行 fixture（用于随机效果采样/固定基线）",
    )
    run.add_argument(
        "--fixture-profile",
        choices=["pvp", "sect"],
        default="pvp",
        help="--fixture 使用的 profile（默认 pvp）",
    )
    run.add_argument("--db", default=None, help="fixture 使用的插件数据库路径")
    run.set_defaults(func=cmd_run)

    export = sub.add_parser("export", help="导出最近运行结果")
    export.add_argument("--target", required=True, help="测试目标名（短横线小写英文）")
    export.add_argument("--date", default=None, help="运行日期 YYYY-MM-DD（默认今天）")
    export.set_defaults(func=cmd_export)

    fixture = sub.add_parser("fixture", help="准备测试基线数据")
    fixture.add_argument("--profile", choices=["pvp", "sect"], default="pvp")
    fixture.add_argument("--db", default=None, help="插件数据库路径覆盖")
    fixture.add_argument("--yes", action="store_true", help="跳过确认提示")
    fixture.set_defaults(func=cmd_fixture)
    return parser


def main(argv=None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CtlError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
