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
        figure_region = self._figure_region(page)
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
            if self._is_inside_figure(bbox, figure_region, page.rect.height):
                continue
            fonts = self._spans_fonts(raw)
            if self._is_subfigure_label(text, fonts):
                continue
            raw_blocks.append((bbox, text, fonts))

        sorted_blocks = self._sort_blocks(raw_blocks, page.rect.width)
        blocks = []
        for order, (bbox, text, fonts) in enumerate(sorted_blocks):
            blocks.append(
                Block(
                    page=page_number,
                    bbox=bbox,
                    text=text,
                    kind=self._classify(text, fonts),
                    order=order,
                )
            )
        return PageData(page_number, float(page.rect.width), float(page.rect.height), blocks)

    @staticmethod
    def _figure_region(page: pymupdf.Page) -> tuple[float, float, float, float] | None:
        """矢量绘图的并集区域。U-Net 这类"图 = 矢量画"的 PDF 用它过滤图内文字标签。

        纯光栅图（type==1 的图块）没有矢量 path，会在 _is_inside_figure 里按图片块处理，
        这里只负责纯矢量图的区域。
        """
        union = None
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is None or rect.is_empty:
                continue
            union = rect if union is None else (union | rect)
        if union is None:
            return None
        return (union.x0, union.y0, union.x1, union.y1)

    @staticmethod
    def _is_inside_figure(
        bbox: tuple[float, float, float, float],
        figure_region: tuple[float, float, float, float] | None,
        page_height: float,
    ) -> bool:
        """判断文本块是否属于图内标签（应过滤）。

        U-Net 第 1 页的架构图把 43 个文字标签画在矢量图区内，这些不该进正文/翻译。
        纯光栅图页（矢量区不可靠）由字体/短文本兜底；这里只针对矢量图。
        判定条件：块中心落在图区内，且块本身不高（标签通常是一两行）。
        """
        if figure_region is None:
            return False
        fx0, fy0, fx1, fy1 = figure_region
        if not (fx0 <= (bbox[0] + bbox[2]) / 2 <= fx1 and fy0 <= (bbox[1] + bbox[3]) / 2 <= fy1):
            return False
        # 图区内的正文（如有）通常跨页宽；窄而矮的几乎都是标签/尺寸标注
        return (bbox[3] - bbox[1]) < page_height * 0.2

    @staticmethod
    def _spans_fonts(raw_block: dict) -> set[str]:
        fonts: set[str] = set()
        for line in raw_block.get("lines", []):
            for span in line.get("spans", []):
                fonts.add(str(span.get("font", "")))
        return fonts

    @staticmethod
    def _is_subfigure_label(text: str, fonts: set[str]) -> bool:
        """过滤纯光栅图页上的 sub-figure 标签（如 'a'、'b'、表头）。

        这类标签字体为 CMSS（sans-serif）、通常只有 1~3 个字符，落在图区外，
        但属于图表的一部分，不该进正文/翻译。
        """
        if not any("CMSS" in font.upper() for font in fonts):
            return False
        stripped = "".join(text.splitlines()).strip()
        return len(stripped) <= 4

    @staticmethod
    def _sort_blocks(
        blocks: list[tuple[tuple[float, float, float, float], str, set[str]]],
        page_width: float,
    ) -> list[tuple[tuple[float, float, float, float], str, set[str]]]:
        if len(blocks) < 2:
            return blocks
        centers = sorted((bbox[0] + bbox[2]) / 2 for bbox, _, _ in blocks)
        gaps = [(centers[i + 1] - centers[i], i) for i in range(len(centers) - 1)]
        largest_gap, gap_index = max(gaps)
        split_gap = max(72.0, page_width * 0.12)
        if largest_gap <= split_gap:
            return sorted(blocks, key=lambda item: (item[0][1], item[0][0]))
        split_at = (centers[gap_index] + centers[gap_index + 1]) / 2
        left = [b for b in blocks if (b[0][0] + b[0][2]) / 2 < split_at]
        right = [b for b in blocks if (b[0][0] + b[0][2]) / 2 >= split_at]
        # 单栏页面被大标题/图表撑出的大 gap 不该触发双栏排序（见技术文档 §7 风险对策）
        if len(left) < 2 or len(right) < 2:
            return sorted(blocks, key=lambda item: (item[0][1], item[0][0]))
        return sorted(left, key=lambda item: (item[0][1], item[0][0])) + sorted(
            right, key=lambda item: (item[0][1], item[0][0])
        )

    @staticmethod
    def _classify(text: str, fonts: set[str]) -> str:
        if PDFParser._looks_like_formula(text, fonts):
            return "formula"
        if len(text) <= 120 and len(text.splitlines()) <= 2:
            return "title"
        return "text"

    @staticmethod
    def _looks_like_formula(text: str, fonts: set[str]) -> bool:
        """判断文本块是否含公式。

        核心信号是**结构**而非字符密度：显示公式通常由短行（≤40 字符）构成，
        且使用数学字体（CMMI/CMSY/CMEX/Symbol 等）。正文段落即使嵌了数学符号
        （如 "where wc : Ω→R is the weight map..."）也以长句为主，不会误判。
        纯光栅页的 sub-figure 标签（CMSS sans-serif）在 has_math_font 中排除。
        """
        has_math_font = any(
            font
            and "CMSS" not in font.upper()
            and any(
                token in font.upper()
                for token in ("CMMI", "CMSY", "CMEX", "SYMBOL", "STIX", "MTEXTRA", "MATHTIME")
            )
            for font in fonts
        )
        if not has_math_font:
            return False

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        short = sum(1 for line in lines if len(line) <= 40)
        # 块内短行占多数 → 显示公式；正文段落是长句为主 → 非公式
        return short / len(lines) >= 0.5
