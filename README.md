# PDF Editor (Plan-Based MVP)

This implementation follows the architecture in `plan.md` and delivers a working end-to-end editor:

- Upload PDF
- Classify and extract text blocks
- Render page backgrounds
- Edit text overlays in a browser UI
- Export reconstructed PDF

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Implemented Roadmap Coverage

- Phase 1: upload endpoint, classifier, render pipeline, text extraction, JSON schema baseline
- Phase 5: React visual editor with overlay text editing and page navigation
- Phase 6: background redaction + text redraw + PDF export
- Phase 7: upload/status/document/page/export/download API endpoints

## Notes

- OCR, table extraction, and celery queue integration are designed but not yet implemented.
- Output redaction currently fills with white; advanced background color sampling can be added next.
