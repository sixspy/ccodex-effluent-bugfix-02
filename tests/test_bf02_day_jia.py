"""BF02 甲：日切已关闭后，正式流量回写必须拒写且正式区零改。"""
from __future__ import annotations

from bf02_utils import (
    audit,
    cumulative,
    day_flow,
    sample_by_code,
    samples,
)

DAY = "2026-11-18"
PERMIT = "DP-2026-E01"
CLOSED_SAMPLE = "SM-OF-E1-A-002"


def test_closed_daycut_formal_flow_write_rejected(client, admin_headers):
    """失败测甲：日切关闭后正式流量仍被改（对账累计随动）。"""
    before = sample_by_code(client, admin_headers, CLOSED_SAMPLE)
    assert before["flow_m3h"] == 2900
    cum_before = cumulative(client, admin_headers, PERMIT)
    day_before = day_flow(client, admin_headers, DAY)

    r = client.post(
        f"/api/reconcile/{PERMIT}/flow-patch",
        headers=admin_headers,
        json={"day": DAY, "sample_code": CLOSED_SAMPLE, "flow_m3h": 9999},
    )

    assert r.status_code in (409, 423), r.text
    assert "日切" in str(r.json().get("detail", ""))
    after = sample_by_code(client, admin_headers, CLOSED_SAMPLE)
    assert after["flow_m3h"] == 2900, "日切已关闭，正式区流量被改写"
    assert cumulative(client, admin_headers, PERMIT) == cum_before, "对账累计被改"
    assert day_flow(client, admin_headers, DAY)["formal_flow_m3"] == day_before[
        "formal_flow_m3"
    ], "日切日正式流量被改"
    actions = [a["action"] for a in audit(client, admin_headers)]
    assert "flow_patch_rejected" in actions, "拒写无审计痕"
    daycut_audit = client.get("/api/audit/daycut", headers=admin_headers)
    assert daycut_audit.status_code == 200, daycut_audit.text
    assert "flow_patch_rejected" in [
        a["action"] for a in daycut_audit.json()["items"]
    ], "审计服务未暴露日切拒写痕"


def test_closed_daycut_force_flag_is_deviation_and_rejected(client, admin_headers):
    """纪要：偏离纪要记日切偏航拒写。"""
    before = sample_by_code(client, admin_headers, CLOSED_SAMPLE)
    r = client.post(
        f"/api/reconcile/{PERMIT}/flow-patch",
        headers=admin_headers,
        json={
            "day": DAY,
            "sample_code": CLOSED_SAMPLE,
            "flow_m3h": 7777,
            "force": True,
        },
    )
    assert r.status_code in (409, 423), r.text
    assert sample_by_code(client, admin_headers, CLOSED_SAMPLE)["flow_m3h"] == before[
        "flow_m3h"
    ]
    assert "daycut_deviation" in [a["action"] for a in audit(client, admin_headers)]


def test_open_day_formal_write_still_allowed(client, admin_headers):
    """对照组：未封窗日期正式回写仍可执行（防止一刀切）。"""
    day = "2026-11-19"
    code = "SM-OF-E1-B-001"
    before = sample_by_code(client, admin_headers, code)
    assert before["flow_m3h"] == 1200
    r = client.post(
        f"/api/reconcile/{PERMIT}/flow-patch",
        headers=admin_headers,
        json={"day": day, "sample_code": code, "flow_m3h": 1300},
    )
    assert r.status_code == 200, r.text
    assert sample_by_code(client, admin_headers, code)["flow_m3h"] == 1300


def test_five_pages_share_day_flow_source(client, admin_headers):
    """总览 / 对账 / 采样 / 排放口 / 处理厂 五页日流量须同源同值。"""
    day = DAY
    day_payload = day_flow(client, admin_headers, day)
    expected = day_payload["formal_flow_m3"]

    dash = client.get("/api/dashboard", headers=admin_headers).json()
    assert dash["daycut"]["day"] == day
    assert dash["daycut"]["formal_flow_m3"] == expected

    rec = client.get(f"/api/reconcile/{PERMIT}", headers=admin_headers).json()
    assert rec["daycut"]["formal_flow_m3"] == expected

    smp = client.get("/api/samples", headers=admin_headers).json()
    assert smp["daycut"]["formal_flow_m3"] == expected

    # 排放口页与处理厂页：东城厂两块口都落在同日切窗
    of_detail = client.get("/api/outfalls/1", headers=admin_headers).json()
    assert of_detail["daycut"]["formal_flow_m3"] > 0
    plant_detail = client.get("/api/plants/1", headers=admin_headers).json()
    assert plant_detail["daycut"]["day"] == day
    assert plant_detail["daycut"]["formal_flow_m3"] == (
        of_detail["daycut"]["formal_flow_m3"]
        + client.get("/api/outfalls/2", headers=admin_headers).json()["daycut"][
            "formal_flow_m3"
        ]
    ), "处理厂页与排放口页不同源"

    # 样本列表里的日流量字段与窗口径一致
    assert smp["daycut"]["day"] == day
    assert all(
        s["day_flow_m3"] == s["flow_m3h"] * 24
        for s in samples(client, admin_headers)
        if s["day"] == day
    )
