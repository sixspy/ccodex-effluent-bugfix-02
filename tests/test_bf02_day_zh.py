"""BF02 争用：两路会话同日回写同一日切日流量须抢对账锁，败方只记争用痕、零改。"""
from __future__ import annotations

from bf02_utils import cumulative, sample_by_code

DAY = "2026-11-18"
PERMIT = "DP-2026-E01"
SAMPLE = "SM-OF-E1-A-002"


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_second_session_waits_on_reconcile_lock(client, admin_headers):
    """甲会话抢锁持锁期间，乙会话同日回写必须 409 且零改。"""
    other = _login(client, "writer", "writer123")
    before = sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"]
    cum_before = cumulative(client, admin_headers, PERMIT)

    held = client.post("/api/locks/acquire", headers=admin_headers,
                       params={"lock_key": f"reconcile:{DAY}"})
    assert held.status_code == 200, held.text

    loser = client.post(
        f"/api/reconcile/{PERMIT}/flow-patch",
        headers=other,
        json={"day": DAY, "sample_code": SAMPLE, "flow_m3h": 4321},
    )
    assert loser.status_code == 409, loser.text

    assert sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"] == before
    assert cumulative(client, admin_headers, PERMIT) == cum_before
    locks = client.get("/api/locks", headers=admin_headers).json()
    assert any(
        c["lock_key"] == f"reconcile:{DAY}" and c["actor"] == "writer"
        for c in locks["contention"]
    ), "败方只记争用痕"

    client.post("/api/locks/release", headers=admin_headers,
                params={"lock_key": f"reconcile:{DAY}"})
    win = client.post(
        f"/api/reconcile/{PERMIT}/flow-patch",
        headers=other,
        json={"day": DAY, "sample_code": SAMPLE, "flow_m3h": 4321},
    )
    assert win.status_code == 409, win.text


def test_duel_daycut_write_script(client):
    """并发双请求打同日写口：恰一方成功（或全部拒写），正式区绝不双写。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).with_name("duel_daycut_write.py")
    assert script.exists(), "缺并发脚本 duel_daycut_write.py"
    env = dict(os.environ)
    env["BF02_BASE_URL"] = "http://testserver-unused"
    proc = subprocess.run(
        [sys.executable, "-I", str(script), "--self-check"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_reopen_contends_with_inflight_writer(client, admin_headers):
    """解封不得抢占在途回写锁：持锁期间 reopen 必须 409 且窗仍关闭、草案未升正。"""
    writer = _login(client, "writer", "writer123")
    day = DAY
    r = client.post(
        f"/api/daycut/{day}/drafts",
        headers=writer,
        json={"sample_code": SAMPLE, "flow_m3h": 3200},
    )
    assert r.status_code == 200, r.text

    lock_key = f"reconcile:{day}"
    assert client.post(
        "/api/locks/acquire", headers=admin_headers, params={"lock_key": lock_key}
    ).status_code == 200

    blocked = client.post(f"/api/daycut/{day}/reopen", headers=writer, json={})
    assert blocked.status_code == 409, blocked.text
    assert sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"] == 2900
    drafts_now = client.get("/api/daycut/drafts", headers=admin_headers,
                            params={"day": day}).json()["items"]
    assert [d["status"] for d in drafts_now] == ["草案"]

    client.post("/api/locks/release", headers=admin_headers, params={"lock_key": lock_key})
    ok = client.post(f"/api/daycut/{day}/reopen", headers=writer, json={})
    assert ok.status_code == 200, ok.text


def test_draft_blocked_while_reopen_holds_lock(client, admin_headers):
    """解封在途持锁时，落草案必须 409，防孤儿草案。"""
    writer = _login(client, "writer", "writer123")
    lock_key = f"reconcile:{DAY}"
    assert client.post(
        "/api/locks/acquire", headers=admin_headers, params={"lock_key": lock_key}
    ).status_code == 200
    blocked = client.post(
        f"/api/daycut/{DAY}/drafts",
        headers=writer,
        json={"sample_code": SAMPLE, "flow_m3h": 3300},
    )
    assert blocked.status_code == 409, blocked.text
    client.post("/api/locks/release", headers=admin_headers, params={"lock_key": lock_key})
    listed = client.get("/api/daycut/drafts", headers=admin_headers,
                        params={"day": DAY}).json()["items"]
    assert listed == []
