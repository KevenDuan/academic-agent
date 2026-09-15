from __future__ import annotations

import gc
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import faiss
import numpy as np
from platformdirs import user_data_path

from app.core.paper_repo import IndexedBlock, PaperRecord, PaperRepository
from app.core.pdf_parser import ParsedDocument


class Embedder(Protocol):
    model_name: str
    dimension: int

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class BgeM3Embedder:
    model_name = "BAAI/bge-m3"

    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL_ID") or self.model_name
        self.device = device or os.getenv("EMBEDDING_DEVICE")
        self._model = None
        self.dimension = 1024

    def _load(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._model = SentenceTransformer(self.model_name, device=device)
            actual_dimension = self._model.get_embedding_dimension()
            if actual_dimension is None:
                raise RuntimeError("无法确定 Embedding 模型维度")
            self.dimension = int(actual_dimension)
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        model = self._load()
        vectors = model.encode(
            list(texts),
            batch_size=8,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def close(self) -> None:
        if self._model is None:
            return
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


@dataclass(frozen=True)
class SearchResult:
    block: IndexedBlock
    score: float

    @property
    def citation(self) -> str:
        return f"{self.block.paper_title}，第 {self.block.page + 1} 页"


class RagEngine:
    def __init__(
        self,
        repository: PaperRepository | None = None,
        embedder: Embedder | None = None,
        index_path: str | Path | None = None,
    ) -> None:
        self.repository = repository or PaperRepository()
        self.embedder = embedder or BgeM3Embedder()
        if index_path is None:
            data_dir = user_data_path("AcademicAgent", appauthor=False, ensure_exists=True)
            index_path = data_dir / "papers.faiss"
        self.index_path = Path(index_path).expanduser().resolve()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index = None
        self._lock = threading.RLock()
        self._closed = False

    def add_document(self, document: ParsedDocument) -> tuple[PaperRecord, bool]:
        with self._lock:
            file_hash = self.repository.file_hash(document.path)
            paper_id = file_hash
            existing = self.repository.get_paper(paper_id)
            if existing and existing.embedding_model == self.embedder.model_name:
                self.repository.update_path(paper_id, str(document.path))
                return self.repository.get_paper(paper_id) or existing, False

            blocks = [
                (
                    page.number,
                    block.order,
                    block.bbox,
                    block.kind,
                    block.text.strip(),
                )
                for page in document.pages
                for block in page.blocks
                if block.kind != "formula" and len(block.text.strip()) >= 20
            ]
            if not blocks:
                raise ValueError("该 PDF 没有可索引的文本块")
            embeddings = self.embedder.encode([block[4] for block in blocks])
            if embeddings.shape != (len(blocks), self.embedder.dimension):
                raise RuntimeError("Embedding 模型返回了错误的向量形状")
            title = self._document_title(document)
            paper = self.repository.replace_paper(
                paper_id=paper_id,
                file_path=str(document.path),
                title=title,
                file_hash=file_hash,
                embedding_model=self.embedder.model_name,
                blocks=blocks,
                embeddings=embeddings,
            )
            self._rebuild_index()
            return paper, True

    def remove_paper(self, paper_id: str) -> None:
        with self._lock:
            self.repository.delete_paper(paper_id)
            self._rebuild_index()

    def list_papers(self) -> list[PaperRecord]:
        with self._lock:
            return self.repository.list_papers()

    def paper_evidence(self, identifier: str, max_chars: int = 24000) -> str:
        identifier = identifier.strip()
        if not identifier:
            return "论文 ID、标题或路径不能为空。"
        with self._lock:
            papers = self.repository.list_papers()
            paper = next(
                (
                    item
                    for item in papers
                    if identifier in {item.paper_id, item.title, item.file_path}
                    or identifier.lower() in item.title.lower()
                ),
                None,
            )
            if paper is None:
                return f"论文库中没有找到：{identifier}"
            blocks = self.repository.get_paper_blocks(paper.paper_id)
            parts = [f"论文：{paper.title}（paper_id={paper.paper_id}）"]
            used = len(parts[0])
            for block in blocks:
                chunk = f"\n[第 {block.page + 1} 页]\n{block.text}\n"
                if used + len(chunk) > max_chars:
                    break
                parts.append(chunk)
                used += len(chunk)
            return "".join(parts)

    def contains_document(self, path: str | Path) -> bool:
        with self._lock:
            paper_id = self.repository.file_hash(path)
            return self.repository.get_paper(paper_id) is not None

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if not query.strip() or top_k <= 0:
            return []
        with self._lock:
            if self.repository.embedding_count() == 0:
                return []
            self.repository.ensure_model(self.embedder.model_name, self.embedder.dimension)
            index = self._ensure_index()
            query_vector = self.embedder.encode([query])
            scores, ids = index.search(query_vector, min(top_k, index.ntotal))
            ordered_ids = [int(value) for value in ids[0] if value >= 0]
            blocks = self.repository.get_blocks(ordered_ids)
            return [
                SearchResult(block=blocks[block_id], score=float(score))
                for block_id, score in zip(ordered_ids, scores[0], strict=False)
                if block_id in blocks
            ]

    @staticmethod
    def format_context(results: Sequence[SearchResult]) -> str:
        sections = []
        for number, result in enumerate(results, start=1):
            sections.append(
                f"[来源{number}：{result.citation}]\n{result.block.text}"
            )
        return "\n\n".join(sections)

    def _ensure_index(self):
        ids = self.repository.load_embedding_ids()
        if self._index is not None and self._valid_index(self._index, ids):
            return self._index
        if self.index_path.exists():
            try:
                index = faiss.read_index(str(self.index_path))
                if self._valid_index(index, ids):
                    self._index = index
                    return index
            except RuntimeError:
                pass
        return self._rebuild_index()

    def _rebuild_index(self):
        ids, vectors = self.repository.load_embeddings()
        model_info = self.repository.get_model_info()
        dimension = model_info[1] if model_info else self.embedder.dimension
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        if len(ids):
            index.add_with_ids(vectors, ids)
        temporary_path = self.index_path.with_suffix(self.index_path.suffix + ".tmp")
        faiss.write_index(index, str(temporary_path))
        temporary_path.replace(self.index_path)
        self._index = index
        return index

    @staticmethod
    def _valid_index(index, expected_ids: np.ndarray) -> bool:
        if index.ntotal != len(expected_ids) or not isinstance(index, faiss.IndexIDMap2):
            return False
        actual_ids = faiss.vector_to_array(index.id_map)
        return np.array_equal(np.sort(actual_ids), np.sort(expected_ids))

    @staticmethod
    def _document_title(document: ParsedDocument) -> str:
        if document.pages:
            candidates = [
                block.text.strip().replace("\n", " ")
                for block in document.pages[0].blocks
                if block.kind == "title" and 8 <= len(block.text.strip()) <= 240
            ]
            if candidates:
                return candidates[0]
        return document.path.stem

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._index = None
            close_embedder = getattr(self.embedder, "close", None)
            if callable(close_embedder):
                close_embedder()
            self.repository.close()
            self._closed = True
