from __future__ import annotations

import uuid
from pathlib import Path

import fitz

from .schemas import BBox, Block, DocumentMeta, DocumentPayload, FontInfo, Page, PageType
from .storage import Paths, sanitize_filename


def classify_page(page: fitz.Page) -> tuple[PageType, int, int]:
    text = page.get_text("text").strip()
    image_count = len(page.get_images(full=True))
    char_count = len(text)
    if char_count > 50:
        page_type: PageType = "text"
    elif image_count > 0 and char_count < 10:
        page_type = "scanned"
    elif image_count > 0 and char_count >= 10:
        page_type = "hybrid"
    else:
        page_type = "text"
    return page_type, char_count, image_count


def _font_family_from_name(name: str) -> str:
    n = name.lower()
    if "mono" in n or "courier" in n:
        return "monospace"
    if "serif" in n or "times" in n:
        return "serif"
    return "sans_serif"


def _extract_blocks(
    page: fitz.Page,
    dpi: int,
    page_width_pts: float,
    page_height_pts: float,
) -> list[Block]:
    scale = dpi / 72.0
    page_width_px = page_width_pts * scale
    page_height_px = page_height_pts * scale
    output: list[Block] = []
    words = page.get_text("words")
    for idx, item in enumerate(words):
        x0, y0, x1, y1, text, *_ = item
        if not text.strip():
            continue
        # Transform bottom-left origin (PDF points) to top-left pixel coordinates.
        px0 = x0 * scale
        py0 = (page_height_pts - y1) * scale
        px1 = x1 * scale
        py1 = (page_height_pts - y0) * scale
        # Some PDFs produce tiny out-of-bounds floats (for example -0.2).
        # Clamp to image-space bounds to keep schema validation stable.
        px0 = min(max(px0, 0.0), page_width_px)
        py0 = min(max(py0, 0.0), page_height_px)
        px1 = min(max(px1, 0.0), page_width_px)
        py1 = min(max(py1, 0.0), page_height_px)
        if px1 < px0:
            px0, px1 = px1, px0
        if py1 < py0:
            py0, py1 = py1, py0
        font = FontInfo(
            original_name="Unknown",
            normalized_name="Arial",
            family="sans_serif",
            matched_font="Arial",
            match_confidence=0.5,
            size_pts=max((y1 - y0), 6),
        )
        output.append(
            Block(
                id=f"block_{idx + 1}",
                content=text,
                bbox=BBox(x0=px0, y0=py0, x1=px1, y1=py1),
                font=font,
                confidence=1.0,
            )
        )
    return output


def process_pdf(pdf_path: Path, original_filename: str, paths: Paths, dpi: int = 150) -> DocumentPayload:
    safe_name = sanitize_filename(original_filename)
    doc_id = uuid.uuid4().hex
    doc = fitz.open(str(pdf_path))
    pages: list[Page] = []

    for page_index, page in enumerate(doc):
        page_no = page_index + 1
        page_type, _, _ = classify_page(page)
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        image_filename = f"{doc_id}_page_{page_no}_bg_{dpi}.png"
        image_path = paths.pages / image_filename
        pix.save(str(image_path))

        blocks = _extract_blocks(
            page,
            dpi=dpi,
            page_width_pts=page.rect.width,
            page_height_pts=page.rect.height,
        )
        pages.append(
            Page(
                page_number=page_no,
                width_pts=page.rect.width,
                height_pts=page.rect.height,
                width_px=pix.width,
                height_px=pix.height,
                dpi=dpi,
                source=page_type,
                background_image_path=image_filename,
                blocks=blocks,
            )
        )

    payload = DocumentPayload(
        document=DocumentMeta(
            id=doc_id,
            original_filename=safe_name,
            page_count=len(pages),
            pages=pages,
        )
    )
    return payload
