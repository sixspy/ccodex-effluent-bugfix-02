"""审计轨迹只读（含日切拒写/偏航/升正痕迹）。"""
from __future__ import annotations

from fastapi import APIRouter

from auth import AuthHeader, require_user
from db import connect

router = APIRouter(tags=["audit"])

DAYCUT_ACTIONS = (
    "flow_patch_rejected",
    "daycut_deviation",
    "daycut_draft",
    "daycut_promote",
    "daycut_reopen",
)


@router.get("/api/audit")
def list_audit(authorization: AuthHeader = None, limit: int = 100):
    require_user(authorization)
    limit = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/audit/daycut")
def list_daycut_audit(authorization: AuthHeader = None, limit: int = 100):
    """只取日切相关审计痕（拒写/偏航/草案/升正/解封）。"""
    require_user(authorization)
    limit = max(1, min(limit, 500))
    marks = ",".join("?" for _ in DAYCUT_ACTIONS)
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM audit_trail WHERE action IN ({marks})
                ORDER BY id DESC LIMIT ?""",
            (*DAYCUT_ACTIONS, limit),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}
