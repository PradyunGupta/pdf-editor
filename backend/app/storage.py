from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .schemas import DocumentPayload, StatusPayload


@dataclass(frozen=True)
class Paths:
    root: Path
    uploads: Path
    pages: Path
    outputs: Path
    json_docs: Path


def ensure_storage(root: Path) -> Paths:
    uploads = root / "uploads"
    pages = root / "pages"
    outputs = root / "outputs"
    json_docs = root / "json"
    for folder in (uploads, pages, outputs, json_docs):
        folder.mkdir(parents=True, exist_ok=True)
    return Paths(root=root, uploads=uploads, pages=pages, outputs=outputs, json_docs=json_docs)


def write_document_json(paths: Paths, payload: DocumentPayload) -> Path:
    target = paths.json_docs / f"{payload.document.id}.json"
    target.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return target


def read_document_json(paths: Paths, document_id: str) -> DocumentPayload:
    target = paths.json_docs / f"{document_id}.json"
    raw = json.loads(target.read_text(encoding="utf-8"))
    return DocumentPayload.model_validate(raw)


def sanitize_filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", ".", " ")).strip()
    return safe[:250] or "document.pdf"


class StatusStore:
    def __init__(self) -> None:
        self._data: dict[str, StatusPayload] = {}

    def set(self, value: StatusPayload) -> None:
        self._data[value.document_id] = value

    def get(self, document_id: str) -> StatusPayload | None:
        return self._data.get(document_id)
