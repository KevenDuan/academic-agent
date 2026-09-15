from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True)
class Session:
    session_id: str
    title: str
    paper_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    message_id: int
    session_id: str
    role: str
    content: str | None
    tool_calls: object | None
    created_at: str
    metadata: object | None = None


def selected_passage_from_metadata(
    metadata: object | None,
) -> dict[str, object] | None:
    if not isinstance(metadata, dict):
        return None
    passage = metadata.get("selected_passage")
    if not isinstance(passage, dict) or not passage.get("text"):
        return None
    return passage


class SessionStore:
    """Persist local chat sessions in SQLite."""

    valid_roles = {"system", "user", "assistant", "tool"}

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            data_dir = user_data_path("AcademicAgent", appauthor=False, ensure_exists=True)
            database_path = data_dir / "sessions.db"
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA secure_delete = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    paper_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL
                        REFERENCES sessions(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                    ON sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session_created_at
                    ON messages(session_id, created_at, message_id);
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(messages)")
            }
            if "metadata_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE messages ADD COLUMN metadata_json TEXT"
                )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def create_session(self, title: str = "新对话", paper_id: str | None = None) -> Session:
        session_id = str(uuid.uuid4())
        timestamp = self._now()
        clean_title = title.strip() or "新对话"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO sessions(session_id, title, paper_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, clean_title, paper_id, timestamp, timestamp),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Session:
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"会话不存在：{session_id}")
        return self._to_session(row)

    def list_sessions(self) -> list[Session]:
        rows = self._connection.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [self._to_session(row) for row in rows]

    def rename_session(self, session_id: str, title: str) -> None:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("会话标题不能为空")
        self._update_session(session_id, title=clean_title)

    def set_paper(self, session_id: str, paper_id: str | None) -> None:
        self._update_session(session_id, paper_id=paper_id)

    def _update_session(self, session_id: str, **values: str | None) -> None:
        if not values:
            return
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = [*values.values(), session_id]
        with self._connection:
            cursor = self._connection.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?", parameters
            )
        if cursor.rowcount == 0:
            raise KeyError(f"会话不存在：{session_id}")

    def delete_session(self, session_id: str) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        self.compact()

    def compact(self) -> None:
        free_pages = self._connection.execute("PRAGMA freelist_count").fetchone()[0]
        if free_pages:
            self._connection.execute("VACUUM")
        self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str | None,
        tool_calls: object | None = None,
        metadata: object | None = None,
    ) -> Message:
        if role not in self.valid_roles:
            raise ValueError(f"不支持的消息角色：{role}")
        timestamp = self._now()
        tool_calls_json = (
            json.dumps(tool_calls, ensure_ascii=False) if tool_calls is not None else None
        )
        metadata_json = (
            json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        )
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO messages(
                    session_id, role, content, tool_calls_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    tool_calls_json,
                    metadata_json,
                    timestamp,
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (timestamp, session_id),
            )
        return Message(
            message_id=int(cursor.lastrowid),
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            created_at=timestamp,
            metadata=metadata,
        )

    def get_messages(self, session_id: str) -> list[Message]:
        rows = self._connection.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at, message_id
            """,
            (session_id,),
        ).fetchall()
        return [self._to_message(row) for row in rows]

    @staticmethod
    def _to_session(row: sqlite3.Row) -> Session:
        return Session(
            session_id=row["session_id"],
            title=row["title"],
            paper_id=row["paper_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _to_message(row: sqlite3.Row) -> Message:
        raw_tool_calls = row["tool_calls_json"]
        raw_metadata = row["metadata_json"]
        return Message(
            message_id=row["message_id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            tool_calls=json.loads(raw_tool_calls) if raw_tool_calls else None,
            created_at=row["created_at"],
            metadata=json.loads(raw_metadata) if raw_metadata else None,
        )

    def close(self) -> None:
        self._connection.close()
