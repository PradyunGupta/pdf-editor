from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .schemas import DocumentPayload, EditItem
from .storage import Paths


def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", max(size_px, 8))
    except OSError:
        return ImageFont.load_default()


def apply_edits_and_export(
    payload: DocumentPayload,
    edits: list[EditItem],
    paths: Paths,
) -> Path:
    edits_by_page_block = {(item.page_number, item.block_id): item.new_content for item in edits}
    output_images: list[Image.Image] = []

    first_page_dpi = 150
    for page in payload.document.pages:
        first_page_dpi = page.dpi
        bg = Image.open(paths.pages / page.background_image_path).convert("RGB")
        draw = ImageDraw.Draw(bg)

        for block in page.blocks:
            key = (page.page_number, block.id)
            if key not in edits_by_page_block:
                continue

            content = edits_by_page_block[key]
            x0 = int(block.bbox.x0)
            y0 = int(block.bbox.y0)
            x1 = int(block.bbox.x1)
            y1 = int(block.bbox.y1)

            # Redact original region and paint replacement text.
            draw.rectangle([x0, y0, x1, y1], fill="white")
            font_size = max(int(block.font.size_pts * (page.dpi / 72.0)), 8)
            font = _load_font(font_size)
            draw.text((x0, y0), content, fill="black", font=font)

        output_images.append(bg)

    output_pdf = paths.outputs / f"{payload.document.id}_edited.pdf"
    if not output_images:
        raise ValueError("No pages available for export.")

    first, rest = output_images[0], output_images[1:]
    first.save(output_pdf, save_all=True, append_images=rest, format="PDF", resolution=first_page_dpi)
    return output_pdf
