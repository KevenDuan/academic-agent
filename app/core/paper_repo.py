from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from platformdirs import user_data_path


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    file_path: str
    title: str
    file_hash: str
    embedding_model: str
    added_at: str
    updated_at: str
    block_count: int


@dataclass(frozen=True)
class IndexedBlock:
    block_id: int
    paper_id: str
    paper_title: str
    page: int
    bbox: tuple[float, float, float, float]
    kind: str
    text: str


class PaperRepository:
    """SQLite source of truth for papers, blocks, and dense embeddings."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        if database_path is None:
            data_dir = user_data_path("AcademicAgent", appauthor=False, ensure_exists=True)
            database_path = data_dir / "papers.db"
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    embedding_model TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_blocks (
                    block_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id TEXT NOT NULL
                        REFERENCES papers(paper_id) ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    block_order INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dimension INTEGER NOT NULL,
                    UNIQUE(paper_id, page, block_order)
                );

                CREATE TABLE IF NOT EXISTS paper_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_paper_blocks_paper
                    ON paper_blocks(paper_id, page, block_order);
                """
            )

    @staticmethod
    def file_hash(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def get_model_info(self) -> tuple[str, int] | None:
        rows = self._connection.execute(
            "SELECT key, value FROM paper_settings WHERE key IN ('model', 'dimension')"
        ).fetchall()
        values = {row["key"]: row["value"] for row in rows}
        if "model" not in values or "dimension" not in values:
            return None
        return values["model"], int(values["dimension"])

    def ensure_model(self, model: str, dimension: int) -> None:
        current = self.get_model_info()
        if current is not None:
            if current != (model, dimension):
                raise RuntimeError(
                    "论文库使用的 Embedding 模型与当前配置不一致："
                    f"{current[0]} ({current[1]}维) != {model} ({dimension}维)"
                )
            return
        with self._connection:
            self._connection.executemany(
                "INSERT OR REPLACE INTO paper_settings(key, value) VALUES (?, ?)",
                (("model", model), ("dimension", str(dimension))),
            )

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        row = self._connection.execute(
            """
            SELECT p.*, COUNT(b.block_id) AS block_count
            FROM papers p
            LEFT JOIN paper_blocks b ON b.paper_id = p.paper_id
            WHERE p.paper_id = ?
            GROUP BY p.paper_id
            """,
            (paper_id,),
        ).fetchone()
        return self._to_paper(row) if row else None

    def list_papers(self) -> list[PaperRecord]:
        rows = self._connection.execute(
            """
            SELECT p.*, COUNT(b.block_id) AS block_count
            FROM papers p
            LEFT JOIN paper_blocks b ON b.paper_id = p.paper_id
            GROUP BY p.paper_id
            ORDER BY p.added_at DESC
            """
        ).fetchall()
        return [self._to_paper(row) for row in rows]

    def update_path(self, paper_id: str, file_path: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE papers SET file_path = ?, updated_at = ? WHERE paper_id = ?",
                (file_path, self._now(), paper_id),
            )

    def replace_paper(
        self,
        paper_id: str,
        file_path: str,
        title: str,
        file_hash: str,
        embedding_model: str,
        blocks: list[tuple[int, int, tuple[float, float, float, float], str, str]],
        embeddings: np.ndarray,
    ) -> PaperRecord:
        if len(blocks) != len(embeddings):
            raise ValueError("文本块数量与 Embedding 数量不一致")
        timestamp = self._now()
        dimension = int(embeddings.shape[1])
        self.ensure_model(embedding_model, dimension)
        with self._connection:
            existing = self._connection.execute(
                "SELECT added_at FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            added_at = existing["added_at"] if existing else timestamp
            self._connection.execute(
                """
                INSERT INTO papers(
                    paper_id, file_path, title, file_hash, embedding_model,
                    added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    file_path = excluded.file_path,
                    title = excluded.title,
                    file_hash = excluded.file_hash,
                    embedding_model = excluded.embedding_model,
                    updated_at = excluded.updated_at
                """,
                (
                    paper_id,
                    file_path,
                    title,
                    file_hash,
                    embedding_model,
                    added_at,
                    timestamp,
                ),
            )
            self._connection.execute(
                "DELETE FROM paper_blocks WHERE paper_id = ?", (paper_id,)
            )
            rows = []
            for block, embedding in zip(blocks, embeddings, strict=True):
                page, order, bbox, kind, text = block
                vector = np.asarray(embedding, dtype=np.float32)
                rows.append(
                    (
                        paper_id,
                        page,
                        order,
                        json.dumps(bbox),
                        kind,
                        text,
                        vector.tobytes(),
                        dimension,
                    )
                )
            self._connection.executemany(
                """
                INSERT INTO paper_blocks(
                    paper_id, page, block_order, bbox_json, kind, text,
                    embedding, embedding_dimension
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        paper = self.get_paper(paper_id)
        if paper is None:
            raise RuntimeError("论文写入数据库失败")
        return paper

    def delete_paper(self, paper_id: str) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
            if not self.list_papers():
                self._connection.execute("DELETE FROM paper_settings")

    def embedding_count(self) -> int:
        return int(
            self._connection.execute("SELECT COUNT(*) FROM paper_blocks").fetchone()[0]
        )

    def load_embeddings(self) -> tuple[np.ndarray, np.ndarray]:
        rows = self._connection.execute(
            """
            SELECT block_id, embedding, embedding_dimension
            FROM paper_blocks ORDER BY block_id
            """
        ).fetchall()
        if not rows:
            model_info = self.get_model_info()
            dimension = model_info[1] if model_info else 0
            return np.empty((0,), dtype=np.int64), np.empty((0, dimension), dtype=np.float32)
        dimension = int(rows[0]["embedding_dimension"])
        vectors = np.vstack(
            [np.frombuffer(row["embedding"], dtype=np.float32) for row in rows]
        )
        if vectors.shape[1] != dimension:
            raise RuntimeError("论文库中的 Embedding 维度损坏")
        ids = np.asarray([row["block_id"] for row in rows], dtype=np.int64)
        return ids, vectors

    def get_blocks(self, block_ids: list[int]) -> dict[int, IndexedBlock]:
        if not block_ids:
            return {}
        placeholders = ",".join("?" for _ in block_ids)
        rows = self._connection.execute(
            f"""
            SELECT b.*, p.title AS paper_title
            FROM paper_blocks b
            JOIN papers p ON p.paper_id = b.paper_id
            WHERE b.block_id IN ({placeholders})
            """,
            block_ids,
        ).fetchall()
        return {
            row["block_id"]: IndexedBlock(
                block_id=row["block_id"],
                paper_id=row["paper_id"],
                paper_title=row["paper_title"],
                page=row["page"],
                bbox=tuple(json.loads(row["bbox_json"])),
                kind=row["kind"],
                text=row["text"],
            )
            for row in rows
        }

    def get_paper_blocks(self, paper_id: str) -> list[IndexedBlock]:
        rows = self._connection.execute(
            """
            SELECT b.*, p.title AS paper_title
            FROM paper_blocks b
            JOIN papers p ON p.paper_id = b.paper_id
            WHERE b.paper_id = ?
            ORDER BY b.page, b.block_order
            """,
            (paper_id,),
        ).fetchall()
        return [
            IndexedBlock(
                block_id=row["block_id"],
                paper_id=row["paper_id"],
                paper_title=row["paper_title"],
                page=row["page"],
                bbox=tuple(json.loads(row["bbox_json"])),
                kind=row["kind"],
                text=row["text"],
            )
            for row in rows
        ]

    @staticmethod
    def _to_paper(row: sqlite3.Row) -> PaperRecord:
        return PaperRecord(
            paper_id=row["paper_id"],
            file_path=row["file_path"],
            title=row["title"],
            file_hash=row["file_hash"],
            embedding_model=row["embedding_model"],
            added_at=row["added_at"],
            updated_at=row["updated_at"],
            block_count=row["block_count"],
        )

    def close(self) -> None:
        self._connection.close()
