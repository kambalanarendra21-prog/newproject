from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import aiosqlite
from passlib.context import CryptContext

from .config import DB_PATH as DB_PATH

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('super', 'sub')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE COLLATE NOCASE,
    owner_id INTEGER,
    txt_record TEXT,
    site_verified INTEGER NOT NULL DEFAULT 0,
    postmaster_registered INTEGER NOT NULL DEFAULT 0,
    cloudflare_txt_added INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(owner_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    user_id INTEGER,
    total INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_secrets (
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, kind),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.executescript(SCHEMA)
        # Safe migrations for older DBs
        cur = await conn.execute("PRAGMA table_info(domains)")
        cols = {row[1] for row in await cur.fetchall()}
        if "owner_id" not in cols:
            await conn.execute("ALTER TABLE domains ADD COLUMN owner_id INTEGER")
        cur = await conn.execute("PRAGMA table_info(jobs)")
        job_cols = {row[1] for row in await cur.fetchall()}
        if "user_id" not in job_cols:
            await conn.execute("ALTER TABLE jobs ADD COLUMN user_id INTEGER")
        await conn.commit()


async def ensure_super_user(username: str, password: str, display_name: str = "Super Admin") -> None:
    """Create the main/super account once; keep username/password synced from env."""
    uname = username.strip().lower()
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM users WHERE role = 'super' LIMIT 1")
        row = await cur.fetchone()
        if row:
            await conn.execute(
                """
                UPDATE users
                SET username = ?, password_hash = ?, is_active = 1
                WHERE id = ?
                """,
                (uname, hash_password(password), row["id"]),
            )
            await conn.execute(
                "UPDATE domains SET owner_id = ? WHERE owner_id IS NULL",
                (row["id"],),
            )
            await conn.commit()
            return
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, is_active, created_at)
            VALUES (?, ?, ?, 'super', 1, ?)
            """,
            (uname, hash_password(password), display_name, _now()),
        )
        cur = await conn.execute("SELECT id FROM users WHERE username = ?", (uname,))
        super_row = await cur.fetchone()
        if super_row:
            await conn.execute(
                "UPDATE domains SET owner_id = ? WHERE owner_id IS NULL",
                (super_row["id"],),
            )
        await conn.commit()


async def clear_demo_seed_once() -> bool:
    """No-op. Kept so older startup code does not wipe live accounts or domains."""
    return False


def count_users() -> int:
    if not Path(DB_PATH).exists():
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM users")
            row = cur.fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0


def get_user_secret(user_id: int, kind: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_secrets (
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, kind)
            )
            """
        )
        cur = conn.execute(
            "SELECT payload FROM user_secrets WHERE user_id = ? AND kind = ?",
            (int(user_id), kind),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def upsert_user_secret(user_id: int, kind: str, payload: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_secrets (
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, kind)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_secrets (user_id, kind, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, kind) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (int(user_id), kind, payload, _now()),
        )
        conn.commit()


async def get_user_by_username(username: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at FROM users ORDER BY role ASC, username ASC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def create_user(username: str, password: str, display_name: str, role: str = "sub") -> int:
    if role not in ("super", "sub"):
        raise ValueError("Invalid role")
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (username.strip().lower(), hash_password(password), display_name.strip(), role, _now()),
        )
        await conn.commit()
        return cur.lastrowid


async def set_user_active(user_id: int, is_active: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ? AND role != 'super'",
            (1 if is_active else 0, user_id),
        )
        await conn.commit()



async def update_user_profile(user_id: int, display_name: str | None = None, password: str | None = None) -> None:
    """Allow a logged-in user to update their own display name and/or password."""
    if display_name is None and password is None:
        return
    async with aiosqlite.connect(DB_PATH) as conn:
        if display_name is not None:
            name = display_name.strip()
            if not name:
                raise ValueError("Display name cannot be empty")
            await conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                (name, user_id),
            )
        if password is not None:
            if len(password) < 8:
                raise ValueError("Password must be at least 8 characters")
            await conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user_id),
            )
        await conn.commit()


async def reset_user_password(user_id: int, password: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
        await conn.commit()


async def upsert_domains(domains: list[str], owner_id: int | None = None) -> int:
    now = _now()
    added = 0
    async with aiosqlite.connect(DB_PATH) as conn:
        for raw in domains:
            domain = raw.strip().lower().rstrip(".")
            if not domain or " " in domain:
                continue
            try:
                await conn.execute(
                    """
                    INSERT INTO domains (domain, owner_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (domain, owner_id, now, now),
                )
                added += 1
            except aiosqlite.IntegrityError:
                # If domain exists and has no owner, claim it for this user
                if owner_id is not None:
                    await conn.execute(
                        """
                        UPDATE domains
                        SET owner_id = COALESCE(owner_id, ?), updated_at = ?
                        WHERE domain = ? AND owner_id IS NULL
                        """,
                        (owner_id, now, domain),
                    )
        await conn.commit()
    return added


async def list_domains(
    q: str | None = None,
    status: str | None = None,
    owner_id: int | None = None,
) -> list[dict]:
    sql = """
        SELECT domains.*, users.username AS owner_username, users.display_name AS owner_name
        FROM domains
        LEFT JOIN users ON users.id = domains.owner_id
        WHERE 1=1
    """
    params: list = []
    if owner_id is not None:
        sql += " AND domains.owner_id = ?"
        params.append(owner_id)
    if q:
        sql += " AND domains.domain LIKE ?"
        params.append(f"%{q.strip().lower()}%")
    if status == "missing_postmaster":
        sql += " AND domains.postmaster_registered = 0"
    elif status == "not_verified":
        sql += " AND domains.site_verified = 0"
    elif status == "verified":
        sql += " AND domains.site_verified = 1"
    elif status == "in_postmaster":
        sql += " AND domains.postmaster_registered = 1"
    sql += " ORDER BY domains.domain ASC"
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_domain(domain_id: int, owner_id: int | None = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        if owner_id is None:
            cur = await conn.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
        else:
            cur = await conn.execute(
                "DELETE FROM domains WHERE id = ? AND owner_id = ?",
                (domain_id, owner_id),
            )
        await conn.commit()
        return cur.rowcount > 0


async def domain_stats(owner_id: int | None = None) -> dict:
    sql = """
        SELECT
          COUNT(*) AS total,
          SUM(site_verified) AS verified,
          SUM(postmaster_registered) AS in_postmaster,
          SUM(cloudflare_txt_added) AS cf_txt,
          SUM(CASE WHEN txt_record IS NOT NULL AND txt_record != '' AND txt_record NOT LIKE 'ERROR%' THEN 1 ELSE 0 END) AS has_token
        FROM domains
    """
    params: list = []
    if owner_id is not None:
        sql += " WHERE owner_id = ?"
        params.append(owner_id)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
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
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(f"UPDATE domains SET {cols} WHERE domain = ?", values)
        await conn.commit()


async def create_job(job_type: str, total: int = 0, user_id: int | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO jobs (job_type, status, user_id, total, started_at) VALUES (?, 'running', ?, ?, ?)",
            (job_type, user_id, total, _now()),
        )
        await conn.commit()
        return cur.lastrowid


async def append_job_log(job_id: int, message: str, level: str = "info") -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO job_logs (job_id, level, message, created_at) VALUES (?, ?, ?, ?)",
            (job_id, level, message, _now()),
        )
        await conn.commit()


async def finish_job(
    job_id: int,
    status: str,
    success_count: int,
    fail_count: int,
    message: str = "",
) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE jobs
            SET status = ?, success_count = ?, fail_count = ?, message = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, success_count, fail_count, message, _now(), job_id),
        )
        await conn.commit()


async def list_jobs(limit: int = 20, user_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM jobs"
    params: list = []
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_job(job_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        if not row:
            return None
        job = dict(row)
        cur = await conn.execute(
            "SELECT * FROM job_logs WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        )
        logs = await cur.fetchall()
        job["logs"] = [dict(l) for l in logs]
        return job


async def get_running_job(user_id: int | None = None) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        if user_id is None:
            cur = await conn.execute(
                "SELECT * FROM jobs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM jobs WHERE status = 'running' AND user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
        row = await cur.fetchone()
    return dict(row) if row else None
