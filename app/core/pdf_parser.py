from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class Block:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    translation: str | None = None
    kind: str = "text"
    order: int = 0


@dataclass
class PageData:
    number: int
    width: float
    height: float
    blocks: list[Block]


class ParsedDocument:
    def __init__(self, path: Path, document: pymupdf.Document, pages: list[PageData]) -> None:
        self.path = path
        self._document = document
        self.pages = pages

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def render_page(self, page_number: int, dpi: int = 150) -> pymupdf.Pixmap:
        page = self._document.load_page(page_number)
        return page.get_pixmap(dpi=dpi, alpha=False)

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None


class PDFParser:
    def parse(self, path: str | Path) -> ParsedDocument:
        pdf_path = Path(path).expanduser().resolve()
        document = pymupdf.open(pdf_path)
        pages: list[PageData] = []
        try:
            for page_number, page in enumerate(document):
                pages.append(self._parse_page(page, page_number))
        except Exception:
            document.close()
            raise
        return ParsedDocument(pdf_path, document, pages)

    def _parse_page(self, page: pymupdf.Page, page_number: int) -> PageData:
        raw_blocks = []
        for raw in page.get_text("dict").get("blocks", []):
            if raw.get("type") != 0:
                continue
            lines = []
            for line in raw.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    lines.append(line_text.strip())
            text = "\n".join(lines).strip()
            if not text:
                continue
            bbox = tuple(float(value) for value in raw["bbox"])
            raw_blocks.append((bbox, text))

        sorted_blocks = self._sort_blocks(raw_blocks, page.rect.width)
        blocks = []
        for order, (bbox, text) in enumerate(sorted_blocks):
            blocks.append(
                Block(
                    page=page_number,
                    bbox=bbox,
                    text=text,
                    kind=self._classify(text),
                    order=order,
                )
            )
        return PageData(page_number, float(page.rect.width), float(page.rect.height), blocks)

    @staticmethod
    def _sort_blocks(
        blocks: list[tuple[tuple[float, float, float, float], str]], page_width: float
    ) -> list[tuple[tuple[float, float, float, float], str]]:
        if len(blocks) < 2:
            return blocks
        centers = sorted((bbox[0] + bbox[2]) / 2 for bbox, _ in blocks)
        gaps = [(centers[i + 1] - centers[i], i) for i in range(len(centers) - 1)]
        largest_gap, gap_index = max(gaps)
        split_gap = max(72.0, page_width * 0.12)
        if largest_gap <= split_gap:
            return sorted(blocks, key=lambda item: (item[0][1], item[0][0]))
        split_at = (centers[gap_index] + centers[gap_index + 1]) / 2
        return sorted(
            blocks,
            key=lambda item: (
                0 if (item[0][0] + item[0][2]) / 2 < split_at else 1,
                item[0][1],
                item[0][0],
            ),
        )

    @staticmethod
    def _classify(text: str) -> str:
        if any(symbol in text for symbol in ("∑", "∫", "√", "≈", "≤", "≥")):
            return "formula"
        if len(text) <= 120 and len(text.splitlines()) <= 2:
            return "title"
        return "text"
