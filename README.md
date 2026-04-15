# PDF Editor (Plan-Based MVP)

This project follows the architecture in `plan.md` and provides a working end-to-end PDF editing flow:

- Upload PDF
- Classify pages and extract text blocks
- Render page backgrounds
- Edit text overlays in the browser
- Export reconstructed PDF

## Project Structure

- `backend/` - FastAPI API and PDF processing pipeline
- `frontend/` - React + Vite editor UI
- `Dockerfile` - single multi-stage image for frontend + backend
- `.dockerignore` - unified Docker ignore rules

## Run Locally (Development)

### 1) Start backend

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend URLs:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`

### 2) Start frontend (new terminal)

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

The Vite dev server proxies `/api` and `/static` requests to backend on port `8000`.

## Run With Docker (Single Container)

Build and run from repository root:

```powershell
docker build -t pdf-editor .
docker run --rm -p 8000:8000 pdf-editor
```

Container URL:

- `http://localhost:8000` (served frontend + API)

## API Endpoints (Current)

- `POST /api/upload`
- `GET /api/documents/{document_id}/status`
- `GET /api/documents/{document_id}`
- `GET /api/documents/{document_id}/pages/{page_number}`
- `POST /api/documents/{document_id}/export`
- `GET /api/documents/{document_id}/download`

## Implemented Roadmap Coverage

- Phase 1: upload endpoint, classifier, render pipeline, text extraction, JSON schema baseline
- Phase 5: visual editor with overlay text editing and page navigation
- Phase 6: redaction + text redraw + PDF export
- Phase 7: upload/status/document/page/export/download API endpoints

## Current Limitations

- OCR pipeline for scanned PDFs is not integrated yet
- Table extraction/editing is not integrated yet
- Background redaction uses white fill (advanced background sampling pending)
- Async queue (Celery/Redis) not integrated yet (current processing is background task in app process)
