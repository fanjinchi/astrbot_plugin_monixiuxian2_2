#!/usr/bin/env python3
"""网页测试平台命令行客户端。

供 AI/脚本发起测试并与网页端共享同一数据源：
- 会话与消息：conversations / send / feed / wait（带 --expect 子串匹配，退出码 0/1）
- 批注：annotations / annotate
- 测试用例：case list/new/show/run/run-all --tag，runs list/show

用法示例::

    WEBTEST_URL=http://127.0.0.1:8765 WEBTEST_TOKEN=secret python scripts/test_platform_cli.py \\
        conversations create --kind private --name 闭关测试
    python scripts/test_platform_cli.py send --conversation 1 --sender test_player_001 --text "闭关"
    python scripts/test_platform_cli.py wait --conversation 1 --expect "修炼" --timeout 30 --after 1
    python scripts/test_platform_cli.py case run cultivate-basic-flow
    python scripts/test_platform_cli.py runs show 3

环境变量：WEBTEST_URL（默认 http://127.0.0.1:8765）、WEBTEST_TOKEN。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"


class CliError(Exception):
    """CLI 用户可见错误。"""


def _request(
    base: str, token: str, method: str, path: str, body=None, timeout: float = 30
) -> dict:
    """发 HTTP 请求并解析 JSON，非 2xx 抛 CliError。"""
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
        raise CliError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CliError(
            f"无法连接测试平台（{exc.reason}），请确认已启用 webtest 平台"
        ) from exc


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="修仙插件网页测试平台 CLI")
    parser.add_argument(
        "--url", default=os.environ.get("WEBTEST_URL", DEFAULT_URL), help="测试平台地址"
    )
    parser.add_argument(
        "--token", default=os.environ.get("WEBTEST_TOKEN", ""), help="访问令牌"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # conversations
    p = sub.add_parser("conversations", help="会话管理")
    p.add_argument("action", choices=["list", "create", "archive", "delete"])
    p.add_argument("--id", type=int, help="会话 id")
    p.add_argument("--kind", choices=["private", "group"], default="private")
    p.add_argument("--name", help="会话名称")
    p.add_argument("--group-id", help="群聊 group_id")
    p.add_argument(
        "--member", action="append", default=[], help="成员 user_id:nickname（可多次）"
    )

    # send
    p = sub.add_parser("send", help="注入一条玩家消息")
    p.add_argument("--conversation", type=int, required=True)
    p.add_argument("--sender", required=True, help="玩家 user_id（须在该会话中）")
    p.add_argument("--text", required=True)

    # feed
    p = sub.add_parser("feed", help="拉取会话消息")
    p.add_argument("--conversation", type=int, required=True)
    p.add_argument("--after", type=int, default=0, help="只取 id 大于该值的消息")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")

    # wait
    p = sub.add_parser("wait", help="等待期望子串出现（供自动化断言）")
    p.add_argument("--conversation", type=int, required=True)
    p.add_argument("--expect", required=True, help="期望出现的子串")
    p.add_argument("--after", type=int, default=0)
    p.add_argument("--timeout", type=float, default=30.0, help="超时秒数")

    # annotations
    p = sub.add_parser("annotations", help="列出会话全部批注")
    p.add_argument("--conversation", type=int, required=True)
    p = sub.add_parser("annotate", help="给消息加批注")
    p.add_argument("--message", type=int, required=True)
    p.add_argument("--text", required=True)

    # cases
    p = sub.add_parser("case", help="用例管理")
    p.add_argument("action", choices=["list", "new", "show", "run", "run-all"])
    p.add_argument("name", nargs="?", help="用例名")
    p.add_argument("--tag", help="run-all 按标签筛选")
    p.add_argument("--steps-json", help="new 时的完整用例 JSON（否则输出模板）")

    # runs
    p = sub.add_parser("runs", help="运行记录")
    p.add_argument("action", choices=["list", "show"])
    p.add_argument("case", nargs="?", help="list 的用例名")
    p.add_argument("--id", type=int, help="show 的运行 id")
    return parser


def main(argv=None) -> int:
    """CLI 入口，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "conversations":
            return _conversations(args)
        if args.command == "send":
            return _send(args)
        if args.command == "feed":
            return _feed(args)
        if args.command == "wait":
            return _wait(args)
        if args.command == "annotations":
            return _annotations(args)
        if args.command == "annotate":
            return _annotate(args)
        if args.command == "case":
            return _case(args)
        if args.command == "runs":
            return _runs(args)
    except CliError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    return 0


def _conversations(args) -> int:
    if args.action == "list":
        _print(_request(args.url, args.token, "GET", "/api/conversations"))
    elif args.action == "create":
        members = []
        for m in args.member:
            uid, _, nick = m.partition(":")
            members.append({"user_id": uid, "nickname": nick or uid})
        body = {"kind": args.kind, "name": args.name}
        if args.kind == "group":
            body["group_id"] = args.group_id or f"group_{int(time.time())}"
        else:
            body["members"] = members
        _print(_request(args.url, args.token, "POST", "/api/conversations", body))
    elif args.action == "archive":
        if not args.id:
            raise CliError("archive 需要 --id")
        _print(
            _request(
                args.url,
                args.token,
                "PATCH",
                f"/api/conversations/{args.id}",
                {"archived": True},
            )
        )
    elif args.action == "delete":
        if not args.id:
            raise CliError("delete 需要 --id")
        _print(
            _request(args.url, args.token, "DELETE", f"/api/conversations/{args.id}")
        )
    return 0


def _send(args) -> int:
    msg = _request(
        args.url,
        args.token,
        "POST",
        f"/api/conversations/{args.conversation}/messages",
        {"sender": args.sender, "text": args.text},
    )
    _print(msg)
    return 0


def _feed(args) -> int:
    q = urllib.parse.urlencode({"after": args.after, "limit": 10000})
    data = _request(
        args.url,
        args.token,
        "GET",
        f"/api/conversations/{args.conversation}/messages?{q}",
    )
    if args.json:
        _print(data)
    else:
        for m in data["messages"]:
            who = "玩家" if m["direction"] == "in" else "机器人"
            print(f"[{m['id']}] {who} {m['sender']}: {m['text']}")
    return 0


def _wait(args) -> int:
    """轮询等待期望子串；找到返回 0，超时返回 1（供断言使用）。"""
    deadline = time.monotonic() + args.timeout
    last_id = args.after
    seen_texts = []
    while time.monotonic() < deadline:
        q = urllib.parse.urlencode({"after": last_id, "limit": 10000})
        data = _request(
            args.url,
            args.token,
            "GET",
            f"/api/conversations/{args.conversation}/messages?{q}",
        )
        for m in data["messages"]:
            if m["id"] > last_id:
                last_id = m["id"]
            if args.expect in (m["text"] or ""):
                print(
                    f"命中: 消息 {m['id']}（{m['direction']} {m['sender']}）: {m['text']}"
                )
                return 0
            seen_texts.append(f"{m['id']}:{m['text']}")
        time.sleep(0.5)
    print(f"超时（{args.timeout}s），未找到期望子串 {args.expect!r}", file=sys.stderr)
    if seen_texts:
        print("已见消息:", file=sys.stderr)
        for t in seen_texts:
            print(f"  {t}", file=sys.stderr)
    return 1


def _annotations(args) -> int:
    q = urllib.parse.urlencode({"after": 0, "limit": 10000})
    data = _request(
        args.url,
        args.token,
        "GET",
        f"/api/conversations/{args.conversation}/messages?{q}",
    )
    anns = [m for m in data["messages"] if m.get("annotation")]
    if not anns:
        print("（无批注）")
        return 0
    for m in anns:
        print(f"[消息 {m['id']}] {m['direction']} {m['sender']}: {m['text']}")
        print(f"  批注: {m['annotation']['text']}")
    return 0


def _annotate(args) -> int:
    _print(
        _request(
            args.url,
            args.token,
            "POST",
            f"/api/messages/{args.message}/annotation",
            {"text": args.text},
        )
    )
    return 0


def _case(args) -> int:
    if args.action == "list":
        _print(_request(args.url, args.token, "GET", "/api/cases"))
    elif args.action == "new":
        if not args.name:
            raise CliError("new 需要用例名")
        if args.steps_json:
            try:
                content = json.loads(args.steps_json)
            except ValueError as exc:
                raise CliError(f"steps-json 解析失败: {exc}") from exc
            content["name"] = args.name
            _print(
                _request(
                    args.url,
                    args.token,
                    "POST",
                    "/api/cases",
                    {"name": args.name, "content": content},
                )
            )
        else:
            tpl = _request(
                args.url, args.token, "POST", "/api/cases", {"name": args.name}
            )
            print("# 已创建模板，请编辑用例 JSON 后 PUT 保存：")
            print(f"#   curl -X PUT {args.url}/api/cases/{args.name} -d '{{...}}'")
            _print(tpl)
    elif args.action == "show":
        if not args.name:
            raise CliError("show 需要用例名")
        _print(
            _request(
                args.url,
                args.token,
                "GET",
                f"/api/cases/{urllib.parse.quote(args.name)}",
            )
        )
    elif args.action == "run":
        if not args.name:
            raise CliError("run 需要用例名")
        run = _request(
            args.url,
            args.token,
            "POST",
            f"/api/cases/{urllib.parse.quote(args.name)}/runs",
        )
        _print(run)
        print(f"结果: {run['status']}" + (" ✓" if run["status"] == "passed" else ""))
        return 0 if run["status"] == "passed" else 1
    elif args.action == "run-all":
        data = _request(args.url, args.token, "GET", "/api/cases")
        cases = data["cases"]
        if args.tag:
            cases = [c for c in cases if args.tag in (c.get("tags") or [])]
        if not cases:
            raise CliError("没有匹配的用例")
        failed = []
        for c in cases:
            try:
                run = _request(
                    args.url,
                    args.token,
                    "POST",
                    f"/api/cases/{urllib.parse.quote(c['name'])}/runs",
                )
                print(f"[{c['name']}] {run['status']}")
                if run["status"] != "passed":
                    failed.append(c["name"])
            except CliError as exc:
                print(f"[{c['name']}] 错误: {exc}")
                failed.append(c["name"])
        if failed:
            print(f"失败用例: {', '.join(failed)}", file=sys.stderr)
            return 1
        return 0
    return 0


def _runs(args) -> int:
    if args.action == "list":
        if not args.case:
            raise CliError("runs list 需要用例名")
        _print(
            _request(
                args.url,
                args.token,
                "GET",
                f"/api/cases/{urllib.parse.quote(args.case)}/runs",
            )
        )
    elif args.action == "show":
        if not args.id:
            raise CliError("runs show 需要 --id")
        _print(_request(args.url, args.token, "GET", f"/api/runs/{args.id}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
