"""排放批争用锁（原子抢占，败方只记争用痕）。"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit

router = APIRouter(tags=["locks"])


def require_lock(conn, lock_key: str, holder: str) -> None:
    """原子抢锁：靠主键唯一约束仲裁，禁止 SELECT-再-INSERT 竞态。"""
    for _ in range(3):
        try:
            conn.execute(
                "INSERT INTO effluent_locks(lock_key,holder,acquired_at) VALUES (?,?,?)",
                (lock_key, holder, now_iso()),
            )
            return
        except sqlite3.IntegrityError:
            pass
        row = conn.execute(
            "SELECT holder FROM effluent_locks WHERE lock_key=?", (lock_key,)
        ).fetchone()
        if row is None:
            continue  # 持有人刚释放，重试抢占
        if row["holder"] == holder:
            return  # 同会话重入
        conn.execute(
            """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
               VALUES (?,?,?,?,?)""",
            (lock_key, holder, "争用失败", f"持有人={row['holder']}", now_iso()),
        )
        conn.commit()  # 争用痕须先落盘再做事务回滚
        raise HTTPException(409, f"锁被占用：{lock_key} 持有人 {row['holder']}")
    raise HTTPException(409, f"锁争用：{lock_key}")


def release(conn, lock_key: str, holder: str) -> None:
    conn.execute(
        "DELETE FROM effluent_locks WHERE lock_key=? AND holder=?",
        (lock_key, holder),
    )


@router.get("/api/locks")
def list_locks(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        locks = [dict(r) for r in conn.execute("SELECT * FROM effluent_locks").fetchall()]
        logs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM contention_log ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ]
        return {"locks": locks, "contention": logs}


@router.post("/api/locks/acquire")
def acquire(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        require_lock(conn, lock_key, user)
        write_audit(conn, user, "lock_acquire", lock_key, {})
        conn.commit()
        return {"ok": True, "lock_key": lock_key, "holder": user}


@router.post("/api/locks/release")
def release_api(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        release(conn, lock_key, user)
        write_audit(conn, user, "lock_release", lock_key, {})
        conn.commit()
        return {"ok": True}
