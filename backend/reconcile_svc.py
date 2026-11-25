"""排放许可与采样对账证明。

BUGFIX-02 修复要点（当班日切修复纪要）：
- 日切已关闭：正式区流量零改，回写口拒写并记审计痕；
- 日切后修订只许落影子流量草案，解封后原子升正，升正前正式区零改；
- 同日回写须抢对账锁，败方只记争用痕、零改；
- 禁止并存双写；偏离纪要记日切偏航拒写。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from daycut_core import (
    daycut_snapshot,
    get_window,
    sample_day,
    window_is_closed,
)
from db import connect, now_iso, write_audit
from locks import release, require_lock
from validators import validate_flow_cap, validate_permit_match

router = APIRouter(tags=["reconcile"])


def _cumulative_flow_m3(conn, permit_code: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(flow_m3h),0) f FROM sample_batches
           WHERE permit_ref=? AND status NOT IN ('作废')""",
        (permit_code,),
    ).fetchone()
    return round(float(row["f"]) * 24.0, 3)


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT permit_code FROM discharge_permits ORDER BY permit_code"
        ).fetchall()
        return {"items": [_reconcile_permit(conn, r["permit_code"]) for r in rows]}


@router.get("/api/reconcile/{permit_code}")
def reconcile_one(permit_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        if not conn.execute(
            "SELECT id FROM discharge_permits WHERE permit_code=?", (permit_code,)
        ).fetchone():
            raise HTTPException(404, "许可不存在")
        return _reconcile_permit(conn, permit_code)


def _reconcile_permit(conn, permit_code: str) -> dict:
    permit = conn.execute(
        "SELECT * FROM discharge_permits WHERE permit_code=?", (permit_code,)
    ).fetchone()
    samples = conn.execute(
        """SELECT sample_code, flow_m3h, metrics, status, generation, created_at
           FROM sample_batches
           WHERE permit_ref=? AND status NOT IN ('作废')""",
        (permit_code,),
    ).fetchall()
    if not samples:
        return {
            "permit_code": permit_code,
            "balanced": False,
            "reason": "无采样批次",
            "samples": [],
            "cumulative_flow_m3": 0.0,
            "daycut": daycut_snapshot(conn, permit_ref=permit_code),
        }
    caps = {
        "cod": permit["cod_cap"],
        "nh3n": permit["nh3n_cap"],
        "tp": permit["tp_cap"],
    }
    details = []
    all_ok = True
    for s in samples:
        metrics = json.loads(s["metrics"] or "{}")
        ok = validate_permit_match(
            caps, metrics, float(s["flow_m3h"]), float(permit["quota_m3d"])
        )
        if not ok:
            all_ok = False
        details.append(
            {
                "sample_code": s["sample_code"],
                "status": s["status"],
                "generation": s["generation"],
                "metrics": metrics,
                "flow_m3h": s["flow_m3h"],
                "day": sample_day(s["created_at"]),
                "matched": ok,
            }
        )
    seal_rows = conn.execute(
        """SELECT d.seal_ref, d.sample_generation, s.sample_code
           FROM discharge_seals d JOIN sample_batches s ON s.id=d.sample_id
           WHERE s.permit_ref=?""",
        (permit_code,),
    ).fetchall()
    return {
        "permit_code": permit_code,
        "quota_m3d": permit["quota_m3d"],
        "caps": caps,
        "balanced": all_ok,
        "proof_ready": all_ok and len(seal_rows) >= 1,
        "seal_count": len(seal_rows),
        "cumulative_flow_m3": _cumulative_flow_m3(conn, permit_code),
        "daycut": daycut_snapshot(conn, permit_ref=permit_code),
        "samples": details,
        "seals": [dict(x) for x in seal_rows],
    }


@router.get("/api/proof/sample/{sample_code}")
def proof_sample(sample_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    from db import connect

    with connect() as conn:
        sample = conn.execute(
            "SELECT * FROM sample_batches WHERE sample_code=?", (sample_code,)
        ).fetchone()
        if not sample:
            raise HTTPException(404, "采样不存在")
        holds = conn.execute(
            "SELECT * FROM exceed_holds WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        releases = conn.execute(
            "SELECT * FROM discharge_releases WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        seals = conn.execute(
            "SELECT * FROM discharge_seals WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        open_holds = [h for h in holds if h["status"] == "开放"]
        closed = [h for h in holds if h["status"] == "已关闭"]
        return {
            "sample_code": sample_code,
            "status": sample["status"],
            "generation": sample["generation"],
            "released": any(r["status"] == "已准排" for r in releases),
            "sealed": any(s["status"] == "已封批" for s in seals),
            "exceed_closed": len(open_holds) == 0
            and (len(closed) > 0 or sample["status"] != "旁路挂起"),
            "holds": [dict(h) for h in holds],
            "releases": [dict(r) for r in releases],
            "seals": [dict(s) for s in seals],
        }


def _resolve_sample(conn, permit_code: str, body: dict):
    code = body.get("sample_code")
    if code:
        row = conn.execute(
            "SELECT * FROM sample_batches WHERE sample_code=?", (code,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "采样批次不存在")
        if row["permit_ref"] != permit_code:
            raise HTTPException(400, "采样批次不属于该许可")
        return row
    day = body.get("day")
    if day:
        row = conn.execute(
            """SELECT * FROM sample_batches
               WHERE permit_ref=? AND substr(created_at,1,10)=?
               ORDER BY id DESC LIMIT 1""",
            (permit_code, day),
        ).fetchone()
        if row:
            return row
    raise HTTPException(400, "须指定采样编号或日切日")


@router.post("/api/reconcile/{permit_code}/flow-patch")
def patch_day_flow(permit_code: str, body: dict, authorization: AuthHeader = None):
    """日切关闭后正式流量拒写；同日回写抢对账锁，败方零改。"""
    from auth import require_writer

    user = require_writer(authorization)
    try:
        flow = float(body.get("flow_m3h") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "回写流量须为数值")
    force = bool(body.get("force"))
    with connect() as conn:
        sample = _resolve_sample(conn, permit_code, body)
        day = body.get("day") or sample_day(sample["created_at"])
        if not day:
            raise HTTPException(400, "无法确定日切日")
        if sample_day(sample["created_at"]) != day:
            raise HTTPException(400, "采样批次不属于该日切日")

        lock_key = f"reconcile:{day}"
        # 同日回写抢对账锁；败方在此记争用痕并 409，正式区零改。
        require_lock(conn, lock_key, user)
        try:
            if window_is_closed(conn, day):
                action = "daycut_deviation" if force else "flow_patch_rejected"
                write_audit(
                    conn,
                    user,
                    action,
                    permit_code,
                    {
                        "day": day,
                        "sample_code": sample["sample_code"],
                        "attempted_flow_m3h": flow,
                        "formal_flow_unchanged": True,
                        "force": force,
                    },
                )
                release(conn, lock_key, user)
                conn.commit()
                detail = (
                    "日切已关闭，偏离纪要（强制改写）记日切偏航并拒写"
                    if force
                    else "日切已关闭，正式区流量零改，拒写"
                )
                raise HTTPException(409, detail)

            # 开窗日才校验流量：与采样入库口同口径（正值且不超处理厂峰值）。
            if flow <= 0:
                raise HTTPException(400, "回写流量须为正")
            design_cap = conn.execute(
                """SELECT p.design_cap_m3d FROM sample_batches s
                   JOIN outfalls o ON o.id=s.outfall_id
                   JOIN plants p ON p.id=o.plant_id WHERE s.id=?""",
                (sample["id"],),
            ).fetchone()
            if design_cap:
                validate_flow_cap(flow, float(design_cap["design_cap_m3d"]))

            conn.execute(
                "UPDATE sample_batches SET flow_m3h=? WHERE id=?",
                (flow, sample["id"]),
            )
            write_audit(
                conn,
                user,
                "flow_patch",
                permit_code,
                {
                    "day": day,
                    "sample_code": sample["sample_code"],
                    "flow_m3h": flow,
                    "daycut_checked": True,
                },
            )
            release(conn, lock_key, user)
            conn.commit()
            return {
                "ok": True,
                "day": day,
                "sample_code": sample["sample_code"],
                "flow_m3h": flow,
                "daycut_checked": True,
            }
        except Exception:
            conn.rollback()  # 中途失败整体回滚，正式区零改
            release(conn, lock_key, user)  # 锁须释放并单独落盘，防止锁泄漏
            conn.commit()
            raise


@router.get("/api/daycut/flow")
def daycut_flow(day: str | None = None, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        return daycut_snapshot(conn, day)


@router.get("/api/daycut/drafts")
def list_drafts(day: str | None = None, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        win = get_window(conn, day)
        if win is None:
            return {"items": []}
        rows = conn.execute(
            """SELECT * FROM daycut_flow_drafts WHERE day=? ORDER BY id""",
            (win["day"],),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/daycut/{day}/drafts")
def create_draft(day: str, body: dict, authorization: AuthHeader = None):
    """日切后修订只许落影子流量草案：正式区零改。"""
    from auth import require_writer

    user = require_writer(authorization)
    try:
        flow = float(body.get("flow_m3h") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "回写流量须为数值")
    code = body.get("sample_code")
    with connect() as conn:
        if not window_is_closed(conn, day):
            raise HTTPException(400, "日切未关闭，禁止落影子草案")
        if not code:
            raise HTTPException(400, "须指定采样编号")
        sample = conn.execute(
            "SELECT * FROM sample_batches WHERE sample_code=?", (code,)
        ).fetchone()
        if not sample:
            raise HTTPException(404, "采样批次不存在")
        if sample_day(sample["created_at"]) != day:
            raise HTTPException(400, "采样批次不属于该日切日")
        lock_key = f"reconcile:{day}"
        # 与解封/回写共用同日对账锁：解封在途时禁止落草案，防止孤儿草案。
        require_lock(conn, lock_key, user)
        try:
            if not window_is_closed(conn, day):
                raise HTTPException(400, "日切未关闭，禁止落影子草案")
            if flow <= 0:
                raise HTTPException(400, "草案流量须为正")
            # 草案升正后会直写正式区，须与入库/回写同口径预校验峰值。
            design_cap = conn.execute(
                """SELECT p.design_cap_m3d FROM sample_batches s
                   JOIN outfalls o ON o.id=s.outfall_id
                   JOIN plants p ON p.id=o.plant_id WHERE s.id=?""",
                (sample["id"],),
            ).fetchone()
            if design_cap:
                validate_flow_cap(flow, float(design_cap["design_cap_m3d"]))
            cur = conn.execute(
                """INSERT INTO daycut_flow_drafts(day,sample_id,sample_code,permit_ref,
                   flow_m3h,status,note,author,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    day,
                    sample["id"],
                    sample["sample_code"],
                    sample["permit_ref"],
                    flow,
                    "草案",
                    body.get("note", ""),
                    user,
                    now_iso(),
                ),
            )
            write_audit(
                conn,
                user,
                "daycut_draft",
                sample["sample_code"],
                {"day": day, "flow_m3h": flow, "formal_flow_unchanged": True},
            )
            release(conn, lock_key, user)
            conn.commit()
            return {
                "id": cur.lastrowid,
                "day": day,
                "sample_code": sample["sample_code"],
                "flow_m3h": flow,
                "status": "草案",
            }
        except Exception:
            conn.rollback()
            release(conn, lock_key, user)
            conn.commit()
            raise


@router.post("/api/daycut/{day}/reopen")
def reopen_daycut(day: str, authorization: AuthHeader = None):
    """解封日切：草案原子升正。任一步出错整体回滚，正式区零改。"""
    from auth import require_writer

    user = require_writer(authorization)
    with connect() as conn:
        win = get_window(conn, day)
        if win is None:
            raise HTTPException(404, "日切窗不存在")
        if win["status"] != "关闭":
            raise HTTPException(400, "日切未关闭，无需解封")
        lock_key = f"reconcile:{day}"
        # 与回写口/草案口共用同日对账锁：解封期间禁止并存回写或落草案。
        require_lock(conn, lock_key, user)
        try:
            drafts = conn.execute(
                "SELECT * FROM daycut_flow_drafts WHERE day=? AND status='草案' ORDER BY id",
                (day,),
            ).fetchall()
            ts = now_iso()
            for d in drafts:
                conn.execute(
                    "UPDATE sample_batches SET flow_m3h=? WHERE id=?",
                    (d["flow_m3h"], d["sample_id"]),
                )
                conn.execute(
                    "UPDATE daycut_flow_drafts SET status='已升正', promoted_at=? WHERE id=?",
                    (ts, d["id"]),
                )
            conn.execute(
                "UPDATE daycut_windows SET status='开放', reopened_at=?, updated_at=? WHERE day=?",
                (ts, ts, day),
            )
            write_audit(
                conn,
                user,
                "daycut_promote",
                day,
                {"promoted": len(drafts), "atomic": True},
            )
            write_audit(
                conn,
                user,
                "daycut_reopen",
                day,
                {"promoted": len(drafts)},
            )
            release(conn, lock_key, user)
            conn.commit()
            return {
                "ok": True,
                "day": day,
                "status": "开放",
                "promoted": len(drafts),
            }
        except Exception:
            conn.rollback()  # 升正中途失败整体回滚：正式流量/草案/窗状态全回退
            release(conn, lock_key, user)
            conn.commit()
            raise
