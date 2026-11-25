"""日切窗与影子流量草案的公共口径。

对账页、总览页、采样页、排放口页、处理厂页一律经此取值，禁止各页自算。
"""
from __future__ import annotations


def sample_day(created_at: str | None) -> str:
    """采样归属日：取入库时间日期段（YYYY-MM-DD）。"""
    return (created_at or "")[:10]


def get_window(conn, day: str | None = None):
    """取日切窗：指定日则精确取；否则取最近关闭窗，无关闭窗退最近窗。"""
    if day is not None:
        return conn.execute(
            "SELECT * FROM daycut_windows WHERE day=?", (day,)
        ).fetchone()
    row = conn.execute(
        "SELECT * FROM daycut_windows WHERE status='关闭' ORDER BY day DESC LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM daycut_windows ORDER BY day DESC LIMIT 1"
        ).fetchone()
    return row


def _filters(
    outfall_id: int | None = None,
    plant_id: int | None = None,
    permit_ref: str | None = None,
) -> tuple[str, list]:
    where = ""
    params: list = []
    if outfall_id is not None:
        where += " AND s.outfall_id=?"
        params.append(outfall_id)
    if plant_id is not None:
        where += " AND o.plant_id=?"
        params.append(plant_id)
    if permit_ref is not None:
        where += " AND s.permit_ref=?"
        params.append(permit_ref)
    return where, params


def formal_flow_m3_24h(conn, day: str, outfall_id=None, plant_id=None, permit_ref=None):
    """正式区日流量（m3/d）= 当日样本小时流量 × 24。"""
    where, params = _filters(outfall_id, plant_id, permit_ref)
    row = conn.execute(
        """SELECT COALESCE(SUM(s.flow_m3h),0) f, COUNT(*) c
           FROM sample_batches s JOIN outfalls o ON o.id=s.outfall_id
           WHERE s.status NOT IN ('作废') AND substr(s.created_at,1,10)=? """
        + where,
        [day, *params],
    ).fetchone()
    return round(float(row["f"]) * 24.0, 3), int(row["c"])


def draft_flow_m3_24h(conn, day: str, outfall_id=None, plant_id=None, permit_ref=None):
    """影子草案日流量（m3/d），只计仍为草案者，未升正不得混入正式区。"""
    where, params = _filters(outfall_id, plant_id, permit_ref)
    row = conn.execute(
        """SELECT COALESCE(SUM(d.flow_m3h),0) f, COUNT(*) c
           FROM daycut_flow_drafts d JOIN sample_batches s ON s.id=d.sample_id
           JOIN outfalls o ON o.id=s.outfall_id
           WHERE d.status='草案' AND d.day=? """
        + where,
        [day, *params],
    ).fetchone()
    return round(float(row["f"]) * 24.0, 3), int(row["c"])


def daycut_snapshot(
    conn,
    day: str | None = None,
    outfall_id: int | None = None,
    plant_id: int | None = None,
    permit_ref: str | None = None,
) -> dict:
    """五页共用的日切快照（同源口径）。"""
    win = get_window(conn, day)
    if win is None:
        return {
            "day": None,
            "status": None,
            "closed_at": None,
            "minutes": "",
            "formal_flow_m3": 0.0,
            "draft_flow_m3": 0.0,
            "sample_count": 0,
            "draft_count": 0,
        }
    d = win["day"]
    formal, count = formal_flow_m3_24h(conn, d, outfall_id, plant_id, permit_ref)
    draft, draft_count = draft_flow_m3_24h(conn, d, outfall_id, plant_id, permit_ref)
    return {
        "day": d,
        "status": win["status"],
        "closed_at": win["closed_at"],
        "minutes": win["minutes"],
        "formal_flow_m3": formal,
        "draft_flow_m3": draft,
        "sample_count": count,
        "draft_count": draft_count,
    }


def window_is_closed(conn, day: str) -> bool:
    win = get_window(conn, day)
    return bool(win and win["status"] == "关闭")
