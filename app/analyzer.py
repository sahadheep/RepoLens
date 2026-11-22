import json
from pathlib import Path

from app import database, embedder
from app.parser import parse_file
from app.graph import build_graph, rank_files
from app.utils import clone_repo, walk_source_files, hash_file


def validate_github_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("https://github.com/"):
        raise ValueError("Only public GitHub URLs are supported (https://github.com/…)")
    parts = url.replace("https://github.com/", "").split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("URL must be in the form https://github.com/owner/repo")
    return url


def prepare_repo(url: str) -> int:
    clean_url = validate_github_url(url)
    clean_name = clean_url.rstrip("/").replace("https://github.com/", "").replace("/", "__")
    clone_path = Path(__file__).parent.parent / "repos" / clean_name

    conn = database.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO repos (url, clone_path, status, progress, error_message, updated_at)
               VALUES (?, ?, 'PENDING', 0, NULL, datetime('now'))
               ON CONFLICT(url) DO UPDATE SET
                   status = 'PENDING',
                   progress = 0,
                   error_message = NULL,
                   updated_at = datetime('now')""",
            (clean_url, str(clone_path)),
        )
        conn.commit()
        cursor.execute("SELECT id FROM repos WHERE url = ?", (clean_url,))
        return cursor.fetchone()["id"]
    finally:
        conn.close()


def set_repo_status(repo_id: int, status: str, progress: int = 0, error_message: str | None = None, files_processed: int = 0):
    conn = database.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE repos
               SET status = ?, progress = ?, error_message = ?, files_processed = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (status, progress, error_message, files_processed, repo_id),
        )
        conn.commit()
    finally:
        conn.close()


def analyze_repo(url: str, repo_id: int | None = None) -> dict:
    clean_url = validate_github_url(url)

    if repo_id is None:
        repo_id = prepare_repo(clean_url)

    conn = database.get_connection()
    try:
        set_repo_status(repo_id, "CLONING", progress=15)
        clone_path = clone_repo(clean_url)

        cursor = conn.cursor()
        cursor.execute(
            "UPDATE repos SET clone_path = ?, updated_at = datetime('now') WHERE id = ?",
            (str(clone_path), repo_id),
        )
        conn.commit()

        set_repo_status(repo_id, "PARSING", progress=35)
        source_files = walk_source_files(clone_path)
        if not source_files:
            raise ValueError("No supported source files (Python, JavaScript, Java) found in this repo.")

        cursor.execute("DELETE FROM call_edges WHERE repo_id = ?", (repo_id,))
        conn.commit()

        processed = 0
        skipped = 0
        all_file_imports: list[tuple[str, list[str]]] = []
        collected_call_edges: list[tuple[str, str]] = []

        total_source_count = len(source_files)

        for idx, (file_path, language) in enumerate(source_files):
            rel_path = str(file_path.relative_to(clone_path))
            new_hash = hash_file(file_path)

            cursor.execute(
                "SELECT id, file_hash FROM files WHERE repo_id = ? AND path = ?",
                (repo_id, rel_path),
            )
            existing = cursor.fetchone()

            if existing and existing["file_hash"] == new_hash:
                skipped += 1
                cursor.execute(
                    "SELECT to_module FROM imports WHERE repo_id = ? AND from_file = ?",
                    (repo_id, rel_path),
                )
                cached_imports = [r["to_module"] for r in cursor.fetchall()]
                all_file_imports.append((rel_path, cached_imports))
                continue

            analysis = parse_file(file_path, clone_path)
            if analysis is None:
                continue

            if existing:
                file_id = existing["id"]
                cursor.execute(
                    "UPDATE files SET file_hash = ? WHERE id = ?",
                    (new_hash, file_id),
                )
                cursor.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
                cursor.execute(
                    "DELETE FROM imports WHERE repo_id = ? AND from_file = ?",
                    (repo_id, rel_path),
                )
            else:
                cursor.execute(
                    "INSERT INTO files (repo_id, path, language, file_hash) VALUES (?, ?, ?, ?)",
                    (repo_id, rel_path, language, new_hash),
                )
                file_id = cursor.lastrowid

            for sym in analysis.symbols:
                fields_str = json.dumps(sym.fields) if sym.fields else None
                calls_str = json.dumps(sym.calls) if sym.calls else None

                cursor.execute(
                    """INSERT INTO symbols (file_id, kind, name, start_line, end_line, source, symbol_id, enclosing_class, signature, fields_json, calls_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (file_id, sym.kind, sym.name, sym.start_line, sym.end_line, sym.source, sym.id, sym.enclosing_class, sym.signature, fields_str, calls_str),
                )

                if sym.id and sym.calls:
                    for callee in sym.calls:
                        collected_call_edges.append((sym.id, callee))

            for imp in analysis.imports:
                cursor.execute(
                    "INSERT INTO imports (repo_id, from_file, to_module) VALUES (?, ?, ?)",
                    (repo_id, rel_path, imp),
                )

            all_file_imports.append((rel_path, analysis.imports))
            processed += 1

            if idx % 10 == 0:
                cur_progress = 35 + int((idx / max(1, total_source_count)) * 35)
                set_repo_status(repo_id, "PARSING", progress=cur_progress, files_processed=processed + skipped)

            conn.commit()

        if collected_call_edges:
            cursor.executemany(
                "INSERT INTO call_edges (repo_id, caller, callee) VALUES (?, ?, ?)",
                [(repo_id, c[0], c[1]) for c in collected_call_edges],
            )
            conn.commit()

        set_repo_status(repo_id, "INDEXING", progress=75, files_processed=processed + skipped)

        if not all_file_imports:
            cursor.execute("SELECT path FROM files WHERE repo_id = ?", (repo_id,))
            all_paths = [r["path"] for r in cursor.fetchall()]
            all_file_imports = []
            for p in all_paths:
                cursor.execute(
                    "SELECT to_module FROM imports WHERE repo_id = ? AND from_file = ?",
                    (repo_id, p),
                )
                imps = [r["to_module"] for r in cursor.fetchall()]
                all_file_imports.append((p, imps))

        set_repo_status(repo_id, "INDEXING", progress=85, files_processed=processed + skipped)
        embedder.embed_symbols(conn, repo_id)

        total_files = processed + skipped
        msg = f"Done. {processed} files parsed, {skipped} unchanged (skipped)."
        set_repo_status(repo_id, "READY", progress=100, files_processed=total_files)

        return {
            "repo_id": repo_id,
            "url": clean_url,
            "status": "READY",
            "files_processed": total_files,
            "message": msg,
        }
    except Exception as e:
        set_repo_status(repo_id, "FAILED", progress=0, error_message=str(e))
        raise
    finally:
        conn.close()
