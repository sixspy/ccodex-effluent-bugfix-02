"""BF02 乙：日切关闭后修订只许影子草案；解封后原子升正，正式区此前零改。"""
from __future__ import annotations

import pytest

from bf02_utils import audit, cumulative, day_flow, drafts, sample_by_code

DAY = "2026-11-18"
PERMIT = "DP-2026-E01"
SAMPLE = "SM-OF-E1-A-002"


def _draft(client, headers, flow=3100.0, sample=SAMPLE, day=DAY):
    return client.post(
        f"/api/daycut/{day}/drafts",
        headers=headers,
        json={"sample_code": sample, "flow_m3h": flow, "note": "复测修正"},
    )


def test_shadow_draft_does_not_enter_reconcile(client, admin_headers):
    """失败测乙：影子草案未升正却混入对账。"""
    cum_before = cumulative(client, admin_headers, PERMIT)
    formal_before = sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"]
    assert formal_before == 2900

    r = _draft(client, admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "草案"

    # 正式区零改
    assert sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"] == formal_before
    assert cumulative(client, admin_headers, PERMIT) == cum_before, "草案混入对账累计"

    flow = day_flow(client, admin_headers, DAY)
    assert flow["formal_flow_m3"] == formal_before * 24
    assert flow["draft_flow_m3"] == 3100.0 * 24
    assert flow["status"] == "关闭"
    listed = drafts(client, admin_headers, day=DAY)
    assert any(d["status"] == "草案" and d["flow_m3h"] == 3100 for d in listed)


def test_reopen_promotes_draft_atomically(client, admin_headers):
    cum_before = cumulative(client, admin_headers, PERMIT)
    assert _draft(client, admin_headers).status_code == 200

    r = client.post(f"/api/daycut/{DAY}/reopen", headers=admin_headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["promoted"] == 1

    assert sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"] == 3100
    assert cumulative(client, admin_headers, PERMIT) == cum_before + (3100 - 2900) * 24
    flow = day_flow(client, admin_headers, DAY)
    assert flow["status"] == "开放"
    assert flow["formal_flow_m3"] == 3100.0 * 24
    assert flow["draft_flow_m3"] == 0.0
    assert [d["status"] for d in drafts(client, admin_headers, day=DAY)] == ["已升正"]
    actions = [a["action"] for a in audit(client, admin_headers)]
    assert "daycut_reopen" in actions
    assert "daycut_promote" in actions


def test_promotion_is_atomic_on_failure(client, admin_headers, monkeypatch):
    """升正中途出错必须整体回滚：正式流量零改、草案仍为草案、窗仍关闭。"""
    assert _draft(client, admin_headers).status_code == 200

    import reconcile_svc

    real = reconcile_svc.write_audit

    def boom(conn, actor, action, target, payload):
        if action == "daycut_reopen":
            raise RuntimeError("模拟升正中断")
        return real(conn, actor, action, target, payload)

    monkeypatch.setattr(reconcile_svc, "write_audit", boom)
    with pytest.raises(Exception):
        client.post(f"/api/daycut/{DAY}/reopen", headers=admin_headers, json={})

    assert sample_by_code(client, admin_headers, SAMPLE)["flow_m3h"] == 2900
    assert day_flow(client, admin_headers, DAY)["status"] == "关闭"
    assert [d["status"] for d in drafts(client, admin_headers, day=DAY)] == ["草案"]


def test_draft_requires_closed_daycut(client, admin_headers):
    r = _draft(client, admin_headers, day="2026-11-19", sample="SM-OF-E1-B-001")
    assert r.status_code == 400, r.text
    assert "未关闭" in str(r.json().get("detail", ""))
