import aiosqlite
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE COLLATE NOCASE,
    txt_record TEXT,
    site_verified INTEGER NOT NULL DEFAULT 0,
    postmaster_registered INTEGER NOT NULL DEFAULT 0,
    cloudflare_txt_added INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db() -> None:
    async with await get_db() as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def upsert_domains(domains: list[str]) -> int:
    now = _now()
    added = 0
    async with await get_db() as db:
        for raw in domains:
            domain = raw.strip().lower().rstrip(".")
            if not domain or " " in domain:
                continue
            try:
                await db.execute(
                    "INSERT INTO domains (domain, created_at, updated_at) VALUES (?, ?, ?)",
                    (domain, now, now),
                )
                added += 1
            except aiosqlite.IntegrityError:
                pass
        await db.commit()
    return added


async def list_domains(q: str | None = None, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM domains WHERE 1=1"
    params: list = []
    if q:
        sql += " AND domain LIKE ?"
        params.append(f"%{q.strip().lower()}%")
    if status == "missing_postmaster":
        sql += " AND postmaster_registered = 0"
    elif status == "not_verified":
        sql += " AND site_verified = 0"
    elif status == "verified":
        sql += " AND site_verified = 1"
    elif status == "in_postmaster":
        sql += " AND postmaster_registered = 1"
    sql += " ORDER BY domain ASC"
    async with await get_db() as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_domain(domain_id: int) -> None:
    async with await get_db() as db:
        await db.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
        await db.commit()


async def domain_stats() -> dict:
    async with await get_db() as db:
        cur = await db.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(site_verified) AS verified,
              SUM(postmaster_registered) AS in_postmaster,
              SUM(cloudflare_txt_added) AS cf_txt,
              SUM(CASE WHEN txt_record IS NOT NULL AND txt_record != '' AND txt_record NOT LIKE 'ERROR%' THEN 1 ELSE 0 END) AS has_token
            FROM domains
            """
        )
        row = await cur.fetchone()
    return {
        "total": row["total"] or 0,
        "verified": row["verified"] or 0,
        "in_postmaster": row["in_postmaster"] or 0,
        "cf_txt": row["cf_txt"] or 0,
        "has_token": row["has_token"] or 0,
        "missing_postmaster": (row["total"] or 0) - (row["in_postmaster"] or 0),
    }


async def update_domain(domain: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [domain.lower()]
    async with await get_db() as db:
        await db.execute(f"UPDATE domains SET {cols} WHERE domain = ?", values)
        await db.commit()


async def create_job(job_type: str, total: int = 0) -> int:
    async with await get_db() as db:
        cur = await db.execute(
            "INSERT INTO jobs (job_type, status, total, started_at) VALUES (?, 'running', ?, ?)",
            (job_type, total, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def append_job_log(job_id: int, message: str, level: str = "info") -> None:
    async with await get_db() as db:
        await db.execute(
            "INSERT INTO job_logs (job_id, level, message, created_at) VALUES (?, ?, ?, ?)",
            (job_id, level, message, _now()),
        )
        await db.commit()


async def finish_job(
    job_id: int,
    status: str,
    success_count: int,
    fail_count: int,
    message: str = "",
) -> None:
    async with await get_db() as db:
        await db.execute(
            """
            UPDATE jobs
            SET status = ?, success_count = ?, fail_count = ?, message = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, success_count, fail_count, message, _now(), job_id),
        )
        await db.commit()


async def list_jobs(limit: int = 20) -> list[dict]:
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_job(job_id: int) -> dict | None:
    async with await get_db() as db:
        cur = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        if not row:
            return None
        job = dict(row)
        cur = await db.execute(
            "SELECT * FROM job_logs WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        )
        logs = await cur.fetchall()
        job["logs"] = [dict(l) for l in logs]
        return job


async def get_running_job() -> dict | None:
    async with await get_db() as db:
        cur = await db.execute(
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
    return dict(row) if row else None
