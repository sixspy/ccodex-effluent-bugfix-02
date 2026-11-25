"""BF02 测试工具：按采样号取数、对账累计、日切流量口径。"""
from __future__ import annotations


def samples(client, headers) -> list[dict]:
    return client.get("/api/samples", headers=headers).json()["items"]


def sample_by_code(client, headers, code: str) -> dict:
    for row in samples(client, headers):
        if row["sample_code"] == code:
            return row
    raise AssertionError(f"夹具缺采样批次：{code}")


def cumulative(client, headers, permit_code: str) -> float:
    data = client.get(f"/api/reconcile/{permit_code}", headers=headers).json()
    return float(data["cumulative_flow_m3"])


def day_flow(client, headers, day: str | None = None) -> dict:
    params = {"day": day} if day else None
    r = client.get("/api/daycut/flow", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def audit(client, headers) -> list[dict]:
    return client.get("/api/audit", headers=headers).json()["items"]


def drafts(client, headers, **params) -> list[dict]:
    r = client.get("/api/daycut/drafts", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]
