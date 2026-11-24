import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "repolens.db"
_initialized = False


def _add_column_if_missing(cursor: sqlite3.Cursor, table: str, col_def: str) -> None:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
    except sqlite3.OperationalError:
        pass


def init_db(conn: sqlite3.Connection | None = None) -> None:
    should_close = False
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        should_close = True

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT    NOT NULL UNIQUE,
            clone_path      TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'READY',
            progress        INTEGER NOT NULL DEFAULT 0,
            files_processed INTEGER NOT NULL DEFAULT 0,
            error_message   TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    _add_column_if_missing(cursor, "repos", "status TEXT NOT NULL DEFAULT 'READY'")
    _add_column_if_missing(cursor, "repos", "progress INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(cursor, "repos", "files_processed INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(cursor, "repos", "error_message TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
            path        TEXT    NOT NULL,
            language    TEXT    NOT NULL,
            file_hash   TEXT    NOT NULL,
            UNIQUE(repo_id, path)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            kind            TEXT    NOT NULL,
            name            TEXT    NOT NULL,
            start_line      INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            source          TEXT    NOT NULL,
            symbol_id       TEXT,
            enclosing_class TEXT,
            signature       TEXT,
            fields_json     TEXT,
            calls_json      TEXT
        )
    """)

    _add_column_if_missing(cursor, "symbols", "symbol_id TEXT")
    _add_column_if_missing(cursor, "symbols", "enclosing_class TEXT")
    _add_column_if_missing(cursor, "symbols", "signature TEXT")
    _add_column_if_missing(cursor, "symbols", "fields_json TEXT")
    _add_column_if_missing(cursor, "symbols", "calls_json TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS imports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
            from_file   TEXT    NOT NULL,
            to_module   TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call_edges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
            caller      TEXT    NOT NULL,
            callee      TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol_id   INTEGER NOT NULL UNIQUE REFERENCES symbols(id) ON DELETE CASCADE,
            vector      BLOB    NOT NULL
        )
    """)

    conn.commit()
    if should_close:
        conn.close()


def get_connection() -> sqlite3.Connection:
    global _initialized
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _initialized:
        _initialized = True
        init_db(conn=conn)
    return conn
