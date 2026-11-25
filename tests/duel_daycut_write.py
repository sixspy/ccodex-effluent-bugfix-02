"""BF02 争用并发脚本：双会话同日抢对账锁回写流量。

用法：
  python -I tests/duel_daycut_write.py --base-url http://127.0.0.1:8000
  python -I tests/duel_daycut_write.py --self-check      # 自起临时库+服务

判定口径（当班日切修复纪要）：
  1) 闭窗日：甲会话在途持对账锁时，乙/丙两路并发回写同日流量必须 409，
     败方只记争用痕，正式区零改；
  2) 开窗日：两路并发回写只许串行落定，最终正式流量必等于某一方提交值，
     绝无撕裂/半写；争用痕不得出现在正式区。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY_CLOSED = "2026-11-18"
DAY_OPEN = "2026-11-19"
PERMIT = "DP-2026-E01"


def _http(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _post(base, path, token, body=None, params=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _http("POST", url, token, body if body is not None else {})


def _get(base, path, token, params=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _http("GET", url, token)[1]


def _login(base, user, pw):
    st, data = _http(
        "POST", base + "/api/login", None, {"username": user, "password": pw}
    )
    assert st == 200, (st, data)
    return data["token"]


def _formal_flow(base, token, code):
    for row in _get(base, "/api/samples", token)["items"]:
        if row["sample_code"] == code:
            return float(row["flow_m3h"])
    raise SystemExit(f"缺采样 {code}")


def _fire_concurrent(base, targets, day, sample):
    """targets: [(name, token, flow)]；同刻起跑两路回写。"""
    barrier = threading.Barrier(len(targets))
    out: list[tuple[str, int, dict]] = []

    def run(name, token, flow):
        barrier.wait()
        st, body = _post(
            base, f"/api/reconcile/{PERMIT}/flow-patch", token,
            {"day": day, "sample_code": sample, "flow_m3h": flow},
        )
        out.append((name, st, body))

    th = [
        threading.Thread(target=run, args=(n, t, f)) for n, t, f in targets
    ]
    for t in th:
        t.start()
    for t in th:
        t.join(timeout=30)
    return out


def _check_closed(base):
    admin = _login(base, "admin", "admin123")
    writer = _login(base, "writer", "writer123")
    sample = "SM-OF-E1-A-002"
    lock_key = f"reconcile:{DAY_CLOSED}"

    before = _formal_flow(base, admin, sample)
    assert before == 2900, before

    # 甲会话在途持锁（模拟在途回写），乙丙两路并发打同日写口。
    st, _ = _post(base, "/api/locks/acquire", admin, None, {"lock_key": lock_key})
    assert st == 200, st
    out = _fire_concurrent(
        base, [("w1", writer, 1111), ("w2", writer, 2222)],
        DAY_CLOSED, sample,
    )
    assert sorted(s for _, s, _ in out) == [409, 409], out
    assert _formal_flow(base, admin, sample) == before, "闭窗日正式流量被改"

    loselog = _get(base, "/api/locks", admin)["contention"]
    held_losers = [c for c in loselog if c["lock_key"] == lock_key and c["actor"] == "writer"]
    assert len(held_losers) >= 1, loselog
    _post(base, "/api/locks/release", admin, None, {"lock_key": lock_key})

    # 锁释放后，闭窗日仍须拒写（不是靠锁，是靠日切标志）。
    st, body = _post(
        base, f"/api/reconcile/{PERMIT}/flow-patch", writer,
        {"day": DAY_CLOSED, "sample_code": sample, "flow_m3h": 3333},
    )
    assert st == 409 and "日切" in str(body.get("detail", "")), (st, body)
    assert _formal_flow(base, admin, sample) == before
    print("closed-day duel ok", [s for _, s, _ in out])


def _check_open(base):
    admin = _login(base, "admin", "admin123")
    writer = _login(base, "writer", "writer123")
    sample = "SM-OF-E1-B-001"
    before = _formal_flow(base, admin, sample)
    assert before == 1200, before

    out = _fire_concurrent(
        base, [("admin", admin, 1301), ("writer", writer, 1302)],
        DAY_OPEN, sample,
    )
    after = _formal_flow(base, admin, sample)
    assert after in (1301.0, 1302.0), f"开窗日撕裂写：{after}"
    winners = [x for x in out if x[1] == 200]
    assert winners, out
    assert any(float(w[2]["flow_m3h"]) == after for w in winners), out
    for _, st, _ in out:
        assert st in (200, 409), out
    print("open-day duel ok", [s for _, s, _ in out], "final", after)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _self_check() -> int:
    tmp = tempfile.mkdtemp(prefix="bf02-duel-")
    db_path = os.path.join(tmp, "duel.db")
    port = _free_port()
    env = dict(os.environ)
    env["EFFLUENT_DB_PATH"] = db_path
    env["PYTHONPATH"] = str(ROOT / "backend")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--app-dir", "backend",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1):
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise SystemExit("服务未就绪")
        _check_closed(base)
        _check_open(base)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        return _self_check()
    if not args.base_url:
        ap.error("需要 --base-url 或 --self-check")
    base = args.base_url.rstrip("/")
    _check_closed(base)
    _check_open(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
