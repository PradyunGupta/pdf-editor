from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


PageType = Literal["text", "scanned", "hybrid", "encrypted", "corrupted"]
DocumentStatus = Literal["processing", "ready", "error"]


class FontInfo(BaseModel):
    original_name: str = Field(default="Unknown", max_length=200)
    normalized_name: str = Field(default="Unknown", max_length=200)
    family: str = Field(default="sans_serif", max_length=80)
    matched_font: str = Field(default="Arial", max_length=200)
    match_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    size_pts: float = Field(default=12.0, gt=0)


class BBox(BaseModel):
    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    coordinate_space: Literal["image_pixels"] = "image_pixels"


class Block(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal["text"] = "text"
    content: str = Field(default="", max_length=10000)
    bbox: BBox
    font: FontInfo = Field(default_factory=FontInfo)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Page(BaseModel):
    page_number: int = Field(gt=0)
    width_pts: float = Field(gt=0)
    height_pts: float = Field(gt=0)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(default=150, gt=0, le=1200)
    source: PageType = "text"
    background_image_path: str = Field(min_length=1, max_length=400)
    rotation: int = 0
    skew_corrected: bool = False
    skew_angle: float = 0.0
    blocks: list[Block] = Field(default_factory=list)


class DocumentMeta(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    original_filename: str = Field(min_length=1, max_length=260)
    page_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    pages: list[Page] = Field(default_factory=list)


class DocumentPayload(BaseModel):
    document: DocumentMeta


class StatusPayload(BaseModel):
    document_id: str
    status: DocumentStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    error_message: str | None = None


class EditItem(BaseModel):
    block_id: str = Field(min_length=1, max_length=100)
    page_number: int = Field(gt=0)
    new_content: str = Field(max_length=10000)

    @field_validator("new_content")
    @classmethod
    def strip_nul(cls, value: str) -> str:
        return value.replace("\x00", "")


class ExportRequest(BaseModel):
    edits: list[EditItem] = Field(default_factory=list, max_length=10000)


class UploadResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    page_count: int
    estimated_seconds: int = 1
