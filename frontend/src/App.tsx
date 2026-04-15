import { useEffect, useMemo, useState } from "react";
import { exportDocument, getDocument, getStatus, uploadPdf } from "./api";
import type { DocumentPayload } from "./types";

type EditMap = Record<string, string>;

function key(pageNumber: number, blockId: string): string {
  return `${pageNumber}:${blockId}`;
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [documentId, setDocumentId] = useState<string>("");
  const [status, setStatus] = useState<string>("idle");
  const [documentData, setDocumentData] = useState<DocumentPayload | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [edits, setEdits] = useState<EditMap>({});
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!documentId || status !== "processing") {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const data = await getStatus(documentId);
        setStatus(data.status);
        if (data.status === "ready") {
          const doc = await getDocument(documentId);
          setDocumentData(doc);
          window.clearInterval(timer);
        }
        if (data.status === "error") {
          setError(data.error_message ?? "Processing failed.");
          window.clearInterval(timer);
        }
      } catch {
        setError("Failed to poll processing status.");
        window.clearInterval(timer);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [documentId, status]);

  const currentPage = useMemo(
    () => documentData?.document.pages[pageIndex] ?? null,
    [documentData, pageIndex]
  );

  async function onUpload(): Promise<void> {
    if (!file) {
      return;
    }
    setStatus("uploading");
    setError("");
    try {
      const data = await uploadPdf(file);
      setDocumentId(data.document_id);
      setStatus("processing");
      setDocumentData(null);
      setPageIndex(0);
      setEdits({});
    } catch {
      setStatus("idle");
      setError("Upload failed. Check backend logs.");
    }
  }

  function updateEdit(pageNumber: number, blockId: string, value: string): void {
    setEdits((prev) => ({ ...prev, [key(pageNumber, blockId)]: value }));
  }

  async function onExport(): Promise<void> {
    if (!documentData) {
      return;
    }
    const payload = Object.entries(edits).map(([k, newContent]) => {
      const [pageNumber, blockId] = k.split(":");
      return {
        page_number: Number(pageNumber),
        block_id: blockId,
        new_content: newContent
      };
    });
    try {
      const result = await exportDocument(documentData.document.id, payload);
      window.open(result.download_url, "_blank");
    } catch {
      setError("Export failed.");
    }
  }

  return (
    <div className="app">
      <h1>PDF Editor</h1>
      <div className="toolbar">
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button onClick={onUpload} disabled={!file || status === "processing"}>
          Upload
        </button>
        <button onClick={onExport} disabled={!documentData}>
          Export PDF
        </button>
        <span className="status">Status: {status}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {currentPage ? (
        <>
          <div className="page-controls">
            <button onClick={() => setPageIndex((p) => Math.max(0, p - 1))} disabled={pageIndex === 0}>
              Previous
            </button>
            <span>
              Page {currentPage.page_number} / {documentData?.document.page_count ?? 0}
            </span>
            <button
              onClick={() =>
                setPageIndex((p) =>
                  Math.min((documentData?.document.pages.length ?? 1) - 1, p + 1)
                )
              }
              disabled={pageIndex >= (documentData?.document.pages.length ?? 1) - 1}
            >
              Next
            </button>
          </div>

          <div
            className="canvas"
            style={{
              width: currentPage.width_px,
              height: currentPage.height_px,
              backgroundImage: `url(/static/pages/${currentPage.background_image_path})`
            }}
          >
            {currentPage.blocks.map((block) => {
              const blockKey = key(currentPage.page_number, block.id);
              return (
                <textarea
                  key={block.id}
                  className={`block ${block.confidence < 0.6 ? "low-confidence" : ""}`}
                  style={{
                    left: block.bbox.x0,
                    top: block.bbox.y0,
                    width: Math.max(10, block.bbox.x1 - block.bbox.x0),
                    height: Math.max(10, block.bbox.y1 - block.bbox.y0),
                    fontSize: block.font.size_pts * (currentPage.dpi / 72)
                  }}
                  value={edits[blockKey] ?? block.content}
                  onChange={(e) => updateEdit(currentPage.page_number, block.id, e.target.value)}
                />
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}
