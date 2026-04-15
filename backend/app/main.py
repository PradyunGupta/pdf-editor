from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pdf_pipeline import process_pdf
from .reconstruct import apply_edits_and_export
from .schemas import DocumentPayload, ExportRequest, StatusPayload, UploadResponse
from .storage import StatusStore, ensure_storage, read_document_json, sanitize_filename, write_document_json


ROOT = Path(__file__).resolve().parents[2]
STORAGE = ensure_storage(ROOT / "storage")
STATUS = StatusStore()
FRONTEND_DIST = ROOT / "frontend_dist"

app = FastAPI(title="PDF Editor API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static/pages", StaticFiles(directory=str(STORAGE.pages)), name="pages")
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend_assets")


@app.get("/", include_in_schema=False)
async def root() -> FileResponse | dict:
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"name": "PDF Editor API", "status": "ok", "docs_url": "/docs"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith(("api/", "docs", "openapi.json", "redoc", "static/")):
        raise HTTPException(status_code=404, detail="Not found.")
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found.")
    return FileResponse(index)


def _run_processing(document_id: str, uploaded_path: Path, original_name: str) -> None:
    try:
        STATUS.set(StatusPayload(document_id=document_id, status="processing", progress=0.2))
        payload = process_pdf(uploaded_path, original_name, STORAGE, dpi=150)
        payload.document.id = document_id
        write_document_json(STORAGE, payload)
        STATUS.set(StatusPayload(document_id=document_id, status="ready", progress=1.0))
    except Exception as exc:
        STATUS.set(
            StatusPayload(
                document_id=document_id,
                status="error",
                progress=1.0,
                error_message=str(exc)[:500],
            )
        )


@app.post("/api/upload", response_model=UploadResponse)
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> UploadResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are allowed.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    safe_name = sanitize_filename(file.filename)
    base = "".join(ch for ch in Path(safe_name).stem if ch.isalnum() or ch in ("_", "-"))[:24] or "doc"
    document_id = f"{base}_{uuid.uuid4().hex[:16]}"

    upload_path = STORAGE.uploads / f"{document_id}.pdf"
    with upload_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    STATUS.set(StatusPayload(document_id=document_id, status="processing", progress=0.0))
    background_tasks.add_task(_run_processing, document_id, upload_path, safe_name)
    return UploadResponse(document_id=document_id, status="processing", page_count=0, estimated_seconds=2)


@app.get("/api/documents/{document_id}/status", response_model=StatusPayload)
async def document_status(document_id: str) -> StatusPayload:
    status = STATUS.get(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found.")
    return status


@app.get("/api/documents/{document_id}/pages/{page_number}")
async def page_data(document_id: str, page_number: int) -> dict:
    payload = _read_doc_or_404(document_id)
    pages = [page for page in payload.document.pages if page.page_number == page_number]
    if not pages:
        raise HTTPException(status_code=404, detail="Page not found.")
    page = pages[0]
    return {
        "page": page.model_dump(),
        "background_image_url": f"/static/pages/{page.background_image_path}",
    }


@app.get("/api/documents/{document_id}")
async def get_document(document_id: str) -> dict:
    payload = _read_doc_or_404(document_id)
    return payload.model_dump()


@app.post("/api/documents/{document_id}/export")
async def export_document(document_id: str, request: ExportRequest) -> dict:
    payload = _read_doc_or_404(document_id)
    output = apply_edits_and_export(payload, request.edits, STORAGE)
    return {
        "download_url": f"/api/documents/{document_id}/download",
        "output_filename": output.name,
    }


@app.get("/api/documents/{document_id}/download")
async def download(document_id: str) -> FileResponse:
    output_path = STORAGE.outputs / f"{document_id}_edited.pdf"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Export not found.")
    return FileResponse(output_path, filename=output_path.name, media_type="application/pdf")


def _read_doc_or_404(document_id: str) -> DocumentPayload:
    try:
        return read_document_json(STORAGE, document_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found.") from exc
