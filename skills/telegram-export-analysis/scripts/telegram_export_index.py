#!/usr/bin/env python3
"""Import official Telegram Desktop JSON exports into a private SQLite FTS index."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER PRIMARY KEY,
    export_path TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    row_id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    chat_name TEXT NOT NULL,
    chat_type TEXT,
    message_id TEXT NOT NULL,
    published_at TEXT,
    author TEXT,
    author_id TEXT,
    text TEXT NOT NULL,
    message_type TEXT,
    last_seen_import INTEGER NOT NULL REFERENCES imports(import_id),
    UNIQUE(chat_id, message_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content='messages',
    content_rowid='row_id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.row_id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
    VALUES ('delete', old.row_id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
    VALUES ('delete', old.row_id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.row_id, new.text);
END;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser("import", help="import one complete Telegram Desktop JSON export")
    import_parser.add_argument("--export", type=Path, required=True)
    import_parser.add_argument("--database", type=Path, required=True)

    search_parser = commands.add_parser("search", help="search an existing FTS index")
    search_parser.add_argument("--database", type=Path, required=True)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args()


def ensure_private_database_path(database: Path) -> None:
    database.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    mode = stat.S_IMODE(database.parent.stat().st_mode)
    if mode & 0o077:
        raise ValueError(
            f"database directory must be private (mode 700): {database.parent}; "
            "create a dedicated directory with `mkdir -m 700 <directory>`"
        )


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(flatten_text(item) for item in value)
    if isinstance(value, dict):
        return flatten_text(value.get("text", ""))
    if value is None:
        return ""
    raise ValueError(f"unsupported Telegram text value: {type(value).__name__}")


def export_chats(payload: dict[str, Any]) -> list[dict[str, Any]]:
    chats = payload.get("chats", {}).get("list")
    if not isinstance(chats, list):
        raise ValueError("expected Telegram Desktop JSON field `chats.list`")
    return chats


def required_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, (str, int)):
        raise ValueError(f"missing or invalid {field} in {context}")
    return str(value)


def message_rows(chats: list[dict[str, Any]], import_id: int) -> tuple[list[tuple[Any, ...]], list[str]]:
    rows: list[tuple[Any, ...]] = []
    imported_chat_ids: list[str] = []
    for chat in chats:
        if not isinstance(chat, dict):
            raise ValueError("invalid chat entry")
        chat_id = required_string(chat.get("id"), "chat.id", "chat")
        chat_name = required_string(chat.get("name"), "chat.name", f"chat {chat_id}")
        messages = chat.get("messages")
        if not isinstance(messages, list):
            raise ValueError(f"missing or invalid messages in chat {chat_id}")
        imported_chat_ids.append(chat_id)
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError(f"invalid message in chat {chat_id}")
            message_id = required_string(message.get("id"), "message.id", f"chat {chat_id}")
            rows.append(
                (
                    chat_id,
                    chat_name,
                    chat.get("type"),
                    message_id,
                    message.get("date"),
                    message.get("from"),
                    message.get("from_id"),
                    flatten_text(message.get("text", "")),
                    message.get("type"),
                    import_id,
                )
            )
    return rows, imported_chat_ids


def set_private_modes(database: Path) -> None:
    for path in (database, database.with_name(f"{database.name}-journal"), database.with_name(f"{database.name}-wal"), database.with_name(f"{database.name}-shm")):
        if path.exists():
            path.chmod(0o600)


def import_export(export_path: Path, database: Path) -> None:
    ensure_private_database_path(database)
    if export_path.name != "result.json":
        raise ValueError("expected the official Telegram Desktop `result.json` export file")
    with export_path.open(encoding="utf-8") as export_file:
        payload = json.load(export_file)
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object at the export root")

    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        connection.execute("PRAGMA secure_delete = ON")
        imported_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            "INSERT INTO imports(export_path, imported_at) VALUES (?, ?)",
            (str(export_path.resolve()), imported_at),
        )
        import_id = cursor.lastrowid
        rows, chat_ids = message_rows(export_chats(payload), import_id)
        connection.executemany(
            """
            INSERT INTO messages(
                chat_id, chat_name, chat_type, message_id, published_at, author,
                author_id, text, message_type, last_seen_import
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                chat_name = excluded.chat_name,
                chat_type = excluded.chat_type,
                published_at = excluded.published_at,
                author = excluded.author,
                author_id = excluded.author_id,
                text = excluded.text,
                message_type = excluded.message_type,
                last_seen_import = excluded.last_seen_import
            """,
            rows,
        )
        placeholders = ", ".join("?" for _ in chat_ids)
        if placeholders:
            connection.execute(
                f"DELETE FROM messages WHERE chat_id IN ({placeholders}) AND last_seen_import != ?",
                [*chat_ids, import_id],
            )
        connection.commit()
    finally:
        connection.close()
        set_private_modes(database)

    print(json.dumps({"database": str(database), "imported_messages": len(rows), "imported_chats": len(chat_ids)}, ensure_ascii=False))


def search_index(database: Path, query: str, limit: int) -> None:
    if limit < 1:
        raise ValueError("--limit must be positive")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT messages.chat_id, messages.chat_name, messages.chat_type,
                   messages.message_id, messages.published_at, messages.author,
                   messages.author_id, messages.text, messages.message_type
            FROM messages_fts
            JOIN messages ON messages.row_id = messages_fts.rowid
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    finally:
        connection.close()
    print(json.dumps([dict(row) | {"source_scope": "my_export"} for row in rows], ensure_ascii=False))


def main() -> int:
    args = parse_args()
    try:
        if args.command == "import":
            import_export(args.export.expanduser().resolve(), args.database.expanduser().resolve())
        else:
            search_index(args.database.expanduser().resolve(), args.query, args.limit)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
