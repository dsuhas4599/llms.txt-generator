"""Persistence for sites, crawl results, and llms.txt. Postgres or SQLite."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent
_default_db = _backend_dir / "llms_txt.db"


def _is_postgres() -> bool:
    url = os.getenv("DATABASE_URL", "").strip()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _get_db_path() -> Path:
    url = os.getenv("DATABASE_URL", "").strip()
    if url and url.startswith("sqlite"):
        if url == "sqlite:///:memory:":
            return Path(":memory:")
        path = url.replace("sqlite:///", "").strip()
        return Path(path)
    return _default_db


@contextmanager
def get_conn():
    if _is_postgres():
        import psycopg2
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        path = _get_db_path()
        conn = sqlite3.connect(str(path) if path != Path(":memory:") else ":memory:")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _run(conn, sql: str, params: tuple = ()):
    if _is_postgres():
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    return conn.execute(sql.replace("%s", "?"), params)


def _fetchone(conn, sql: str, params: tuple = ()) -> dict | None:
    if _is_postgres():
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    cur = conn.execute(sql.replace("%s", "?"), params)
    row = cur.fetchone()
    return dict(row) if row else None


def _fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    if _is_postgres():
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    cur = conn.execute(sql.replace("%s", "?"), params)
    return [dict(r) for r in cur.fetchall()]


def _normalize_site(row: dict | None) -> dict | None:
    return row


def init_db():
    if _is_postgres():
        _init_db_postgres()
    else:
        _init_db_sqlite()


def _init_db_sqlite():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_url TEXT NOT NULL UNIQUE,
                name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                monitor_schedule TEXT,
                next_crawl_at TEXT
            );
            CREATE TABLE IF NOT EXISTS crawl_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                finished_at TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                raw_pages TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llms_txt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                crawl_result_id INTEGER NOT NULL REFERENCES crawl_results(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                generated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_crawl_results_site_id ON crawl_results(site_id);
            CREATE INDEX IF NOT EXISTS idx_llms_txt_site_id ON llms_txt(site_id);
        """)


def _init_db_postgres():
    statements = [
        """CREATE TABLE IF NOT EXISTS sites (
            id BIGSERIAL PRIMARY KEY,
            root_url TEXT NOT NULL UNIQUE,
            name TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            monitor_schedule TEXT,
            next_crawl_at TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS crawl_results (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            finished_at TIMESTAMPTZ NOT NULL,
            page_count INTEGER NOT NULL,
            raw_pages JSONB NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS llms_txt (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            crawl_result_id BIGINT NOT NULL REFERENCES crawl_results(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_crawl_results_site_id ON crawl_results(site_id)",
        "CREATE INDEX IF NOT EXISTS idx_llms_txt_site_id ON llms_txt(site_id)",
        "ALTER TABLE sites ADD COLUMN IF NOT EXISTS next_crawl_at TIMESTAMPTZ",
    ]
    with get_conn() as conn:
        for stmt in statements:
            _run(conn, stmt)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def site_create(root_url: str, name: str | None = None, monitor_schedule: str | None = None) -> dict:
    now = _now()
    root_url = root_url.strip()
    name_val = (name or "").strip() or None

    with get_conn() as conn:
        if _is_postgres():
            row = _fetchone(
                conn,
                """INSERT INTO sites (root_url, name, created_at, updated_at, monitor_schedule)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (root_url, name_val, now, now, monitor_schedule),
            )
            return _normalize_site(row) or {}
        cur = _run(
            conn,
            """INSERT INTO sites (root_url, name, created_at, updated_at, monitor_schedule)
               VALUES (%s, %s, %s, %s, %s)""",
            (root_url, name_val, now, now, monitor_schedule),
        )
        return _fetchone(conn, "SELECT * FROM sites WHERE id = %s", (cur.lastrowid,))


def site_get_all() -> list[dict]:
    sql = """SELECT s.*,
                    (SELECT finished_at FROM crawl_results WHERE site_id = s.id ORDER BY finished_at DESC LIMIT 1) AS last_crawl_at,
                    (SELECT generated_at FROM llms_txt WHERE site_id = s.id ORDER BY generated_at DESC LIMIT 1) AS last_generated_at
             FROM sites s ORDER BY s.updated_at DESC"""
    with get_conn() as conn:
        rows = _fetchall(conn, sql)
    return [_normalize_site(r) or r for r in rows]


def site_get_by_id(site_id: int) -> dict | None:
    sql = """SELECT s.*,
                    (SELECT finished_at FROM crawl_results WHERE site_id = s.id ORDER BY finished_at DESC LIMIT 1) AS last_crawl_at,
                    (SELECT generated_at FROM llms_txt WHERE site_id = s.id ORDER BY generated_at DESC LIMIT 1) AS last_generated_at
             FROM sites s WHERE s.id = %s"""
    with get_conn() as conn:
        row = _fetchone(conn, sql, (site_id,))
    return _normalize_site(row)


def site_get_by_url(root_url: str) -> dict | None:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT * FROM sites WHERE root_url = %s", (root_url.strip(),))
    return _normalize_site(row)


def crawl_result_save(site_id: int, page_count: int, raw_pages: list[dict]) -> int:
    now = _now()
    raw_json = json.dumps(raw_pages)

    with get_conn() as conn:
        if _is_postgres():
            row = _fetchone(
                conn,
                """INSERT INTO crawl_results (site_id, finished_at, page_count, raw_pages) VALUES (%s, %s, %s, %s::jsonb) RETURNING id""",
                (site_id, now, page_count, raw_json),
            )
            return row["id"]
        cur = _run(
            conn,
            "INSERT INTO crawl_results (site_id, finished_at, page_count, raw_pages) VALUES (%s, %s, %s, %s)",
            (site_id, now, page_count, raw_json),
        )
        return cur.lastrowid


def llms_txt_save(site_id: int, crawl_result_id: int, content: str) -> int:
    now = _now()

    with get_conn() as conn:
        if _is_postgres():
            row = _fetchone(
                conn,
                """INSERT INTO llms_txt (site_id, crawl_result_id, content, generated_at) VALUES (%s, %s, %s, %s) RETURNING id""",
                (site_id, crawl_result_id, content, now),
            )
            _run(conn, "UPDATE sites SET updated_at = %s WHERE id = %s", (now, site_id))
            return row["id"]
        cur = _run(
            conn,
            "INSERT INTO llms_txt (site_id, crawl_result_id, content, generated_at) VALUES (%s, %s, %s, %s)",
            (site_id, crawl_result_id, content, now),
        )
        _run(conn, "UPDATE sites SET updated_at = %s WHERE id = %s", (now, site_id))
        return cur.lastrowid


def llms_txt_get_latest(site_id: int) -> dict | None:
    with get_conn() as conn:
        return _fetchone(
            conn,
            "SELECT * FROM llms_txt WHERE site_id = %s ORDER BY generated_at DESC LIMIT 1",
            (site_id,),
        )


def sites_get_due_for_crawl() -> list[dict]:
    now = _now()
    sql = """SELECT s.* FROM sites s
             WHERE s.next_crawl_at IS NULL OR s.next_crawl_at <= %s
             ORDER BY COALESCE(s.next_crawl_at, '1970-01-01') ASC"""
    with get_conn() as conn:
        rows = _fetchall(conn, sql, (now,))
    return rows


def site_update_next_crawl_at(site_id: int, next_at: str) -> None:
    with get_conn() as conn:
        _run(conn, "UPDATE sites SET next_crawl_at = %s, updated_at = %s WHERE id = %s", (next_at, next_at, site_id))
