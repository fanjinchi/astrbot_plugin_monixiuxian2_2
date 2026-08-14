"""独立端到端冒烟（56 项断言）：不依赖运行中的 AstrBot，验证服务器/适配器/注入/
出站捕获/批注/归档/群聊/用例引擎（运行-轨迹-失败记录实际回复-轨迹不随会话删除丢失）/
WebSocket/CLI 全链路。

运行（AstrBot uv 环境）::

    cd ~/code/AstrBot && uv run python -u testplatform_plugin/tests/e2e_smoke.py

注意：HTTP 客户端必须用 aiohttp（异步），不能用同步 urllib——否则会阻塞事件循环，
与同进程内的 aiohttp 服务器互相死锁（CLI 子进程同理须经 asyncio.to_thread）。
"""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = "/home/guigui/orca/workspaces/astrbot_plugin_monixiuxian2_2/testplatform"
sys.path.insert(0, REPO)

import aiohttp

from testplatform_plugin.adapter.webtest_adapter import WebTestAdapter
from testplatform_plugin.server.app_state import app_state

BASE = "http://127.0.0.1:8765"
TOKEN = "smoke-secret"
DATA_DIR = Path("/tmp/webtest_smoke_data")

results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  | {detail}" if detail else ""), flush=True)


async def api(sess, method, path, body=None, token=TOKEN, expect_status=200):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with sess.request(method, BASE + path, json=body, headers=headers) as resp:
        try:
            data = await resp.json()
        except Exception:
            data = None
        check(f"{method} {path}", resp.status == expect_status, f"status={resp.status}")
        return data


async def main():
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)
    app_state.setup(
        {"host": "127.0.0.1", "port": 8765, "access_token": TOKEN,
         "default_players": [{"nickname": "测试玩家1", "user_id": "test_player_001"}]},
        DATA_DIR,
    )
    adapter = WebTestAdapter({"enable": True, "id": "webtest"}, {}, asyncio.Queue())
    check("适配器注册", app_state.adapter is adapter)

    # 模拟 AstrBot respond 管线：注入后异步回复
    async def fake_pipeline(event):
        text = event.message_str or ""
        reply = "🧘 道友已进入闭关状态" if "闭关" in text else f"模拟回复：{text}"
        conv_id = await app_state.resolve_session(event.session_id)
        await app_state.capture_outbound(conv_id, reply, [])

    adapter.commit_event = lambda evt: asyncio.get_event_loop().create_task(fake_pipeline(evt))

    await app_state.start_server()
    await asyncio.sleep(0.5)

    try:
        async with aiohttp.ClientSession() as sess:
            # 状态与鉴权
            await api(sess, "GET", "/api/status")
            await api(sess, "GET", "/api/status", token="wrong", expect_status=401)
            await api(sess, "GET", "/api/status", token="", expect_status=401)
            await api(sess, "GET", "/api/conversations", token="wrong", expect_status=401)

            # 建私聊会话（默认玩家）
            conv = await api(sess, "POST", "/api/conversations", {"kind": "private"}, expect_status=201)
            cid = conv["id"]
            check("会话创建含默认玩家", len(conv.get("players", [])) == 1)
            players = await api(sess, "GET", "/api/players")
            check("players 接口", any(p["user_id"] == "test_player_001" for p in players["players"]))

            # 注入消息 → 模拟管线回复 → 轮询出现 out
            msg = await api(sess, "POST", f"/api/conversations/{cid}/messages",
                            {"sender": "test_player_001", "text": "闭关"}, expect_status=201)
            check("注入返回 in 消息", msg["direction"] == "in")
            found = None
            for _ in range(20):
                data = await api(sess, "GET", f"/api/conversations/{cid}/messages")
                outs = [m for m in data["messages"] if m["direction"] == "out"]
                if outs:
                    found = outs[-1]
                    break
                await asyncio.sleep(0.3)
            check("机器人回复出现在 feed", found is not None, found["text"] if found else "")
            check("回复文本正确", found is not None and "闭关状态" in found["text"])

            # 非法注入：未知玩家 / 空文本
            await api(sess, "POST", f"/api/conversations/{cid}/messages",
                      {"sender": "nobody", "text": "hi"}, expect_status=400)
            await api(sess, "POST", f"/api/conversations/{cid}/messages",
                      {"sender": "test_player_001", "text": "  "}, expect_status=400)

            # 批注 CRUD
            mid = msg["id"]
            await api(sess, "POST", f"/api/messages/{mid}/annotation", {"text": "这里需要改成主动提示"}, expect_status=201)
            ann = await api(sess, "GET", f"/api/messages/{mid}/annotation")
            check("批注落库", (ann or {}).get("annotation", {}).get("text", "").startswith("这里需要"))
            await api(sess, "PATCH", f"/api/messages/{mid}/annotation", {"text": "改过的批注"})
            ann2 = await api(sess, "GET", f"/api/messages/{mid}/annotation")
            check("批注更新", (ann2 or {}).get("annotation", {}).get("text") == "改过的批注")
            await api(sess, "DELETE", f"/api/messages/{mid}/annotation")
            await api(sess, "GET", f"/api/messages/{mid}/annotation", expect_status=404)

            # 归档后禁止注入
            await api(sess, "PATCH", f"/api/conversations/{cid}", {"archived": True})
            await api(sess, "POST", f"/api/conversations/{cid}/messages",
                      {"sender": "test_player_001", "text": "x"}, expect_status=400)

            # 群聊会话
            gconv = await api(sess, "POST", "/api/conversations",
                              {"kind": "group", "group_id": "g_1001", "name": "测试群"}, expect_status=201)
            await api(sess, "POST", f"/api/conversations/{gconv['id']}/players",
                      {"user_id": "u2", "nickname": "玩家二"}, expect_status=201)
            await api(sess, "POST", f"/api/conversations/{gconv['id']}/messages",
                      {"sender": "u2", "text": "群聊消息"}, expect_status=201)
            await asyncio.sleep(0.5)
            gdata = await api(sess, "GET", f"/api/conversations/{gconv['id']}/messages")
            check("群聊消息流", any(m["direction"] == "out" for m in gdata["messages"]))

            # 用例模板 + 校验拒绝
            await api(sess, "POST", "/api/cases", {"name": "smoke-case"}, expect_status=201)
            await api(sess, "PUT", "/api/cases/smoke-case",
                      {"content": {"name": "smoke-case", "description": "", "scenario": "s", "steps": []}},
                      expect_status=400)
            await api(sess, "DELETE", "/api/cases/smoke-case")

            # 用例引擎端到端：运行→轨迹→失败记录实际回复
            import shutil as _sh
            _sh.copy2(f"{REPO}/testplatform_plugin/examples/cases/cultivate-basic-flow.json",
                      app_state.cases_dir / "cultivate-basic-flow.json")
            simple = {"name": "smoke-simple", "description": "冒烟用例", "scenario": "验证运行器",
                      "tags": ["smoke"], "conversation": {"kind": "private"},
                      "steps": [{"type": "send", "player": "p1", "text": "闭关"},
                                {"type": "expect", "match": "闭关状态", "timeout": 10}]}
            await api(sess, "PUT", "/api/cases/smoke-simple", {"content": simple})
            run = await api(sess, "POST", "/api/cases/smoke-simple/runs", expect_status=201)
            check("用例运行 passed", run.get("status") == "passed", str(run.get("status")))
            check("轨迹含消息交换", len(run.get("run_messages") or []) >= 2,
                  f"{len(run.get('run_messages') or [])} 条")
            check("逐步骤结果", len(run.get("steps_result") or []) == 2)
            runs = await api(sess, "GET", "/api/cases/smoke-simple/runs")
            check("运行记录列表", len(runs.get("runs") or []) == 1)
            # 失败用例：期望不匹配 → failed 且 actual 记录实际回复
            bad = dict(simple, name="smoke-bad", steps=[{"type": "send", "player": "p1", "text": "闭关"},
                                                        {"type": "expect", "match": "绝不匹配", "timeout": 3}])
            await api(sess, "PUT", "/api/cases/smoke-bad", {"content": bad})
            run2 = await api(sess, "POST", "/api/cases/smoke-bad/runs", expect_status=201)
            check("失败用例 failed", run2.get("status") == "failed")
            step2 = run2["steps_result"][1]
            check("失败记录实际回复", step2.get("actual") and any("闭关状态" in t for t in step2["actual"]),
                  str(step2.get("actual")))
            # 轨迹不随会话删除丢失
            trace_conv_id = run2["conversation_id"]
            await api(sess, "DELETE", f"/api/conversations/{trace_conv_id}")
            kept = await api(sess, "GET", f"/api/runs/{run2['id']}")
            check("删除会话后轨迹仍完整", kept.get("status") == "failed" and len(kept.get("run_messages") or []) > 0)
    
            # WebSocket 快照 + open
            async with sess.ws_connect(f"{BASE}/ws", headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
                snap = json.loads(await ws.receive_str())
                check("WS 连接推快照", snap.get("type") == "snapshot" and len(snap.get("conversations", [])) >= 2)
                await ws.send_str(json.dumps({"type": "open", "conversation_id": cid}))
                msgs_payload = json.loads(await ws.receive_str())
                check("WS open 推历史消息", msgs_payload.get("type") == "messages"
                      and any(m["direction"] == "out" for m in msgs_payload.get("messages", [])))

        # CLI 闭环（独立进程）
        cli = [sys.executable, f"{REPO}/testplatform_plugin/scripts/test_platform_cli.py",
               "--token", TOKEN]
        out = await asyncio.to_thread(subprocess.run, cli + ["conversations", "list"],
                                      capture_output=True, text=True, timeout=40)
        check("CLI conversations list", out.returncode == 0 and f'"id":{cid}' in out.stdout.replace(" ", "").replace("\n", ""))
        out = await asyncio.to_thread(subprocess.run, cli + ["feed", "--conversation", str(cid)],
                                       capture_output=True, text=True, timeout=40)
        check("CLI feed 可见回复", "闭关状态" in out.stdout, out.stderr.strip()[:2000])
        out = await asyncio.to_thread(subprocess.run, cli + ["wait", "--conversation", str(cid), "--expect", "闭关状态", "--timeout", "5"],
                                       capture_output=True, text=True, timeout=40)
        check("CLI wait 命中退出码 0", out.returncode == 0, out.stderr.strip()[:2000])
        out = await asyncio.to_thread(subprocess.run, cli + ["wait", "--conversation", str(cid), "--expect", "绝不存在的文本", "--timeout", "2"],
                                       capture_output=True, text=True, timeout=40)
        check("CLI wait 超时退出码 1", out.returncode == 1)
        out = await asyncio.to_thread(subprocess.run, cli + ["case", "new", "cli-smoke-case"],
                                       capture_output=True, text=True, timeout=40)
        check("CLI case new 生成模板", out.returncode == 0 and "steps" in out.stdout)
        async with aiohttp.ClientSession() as sess2:
            await api(sess2, "DELETE", "/api/cases/cli-smoke-case")
    finally:
        await app_state.shutdown()

    passed = sum(1 for _, c in results if c)
    print(f"\n{passed}/{len(results)} 项通过", flush=True)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
