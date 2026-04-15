import axios from "axios";
import type { DocumentPayload, StatusPayload } from "./types";

const api = axios.create({
  baseURL: "/"
});

export async function uploadPdf(file: File): Promise<{ document_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/api/upload", form);
  return data;
}

export async function getStatus(documentId: string): Promise<StatusPayload> {
  const { data } = await api.get(`/api/documents/${documentId}/status`);
  return data;
}

export async function getDocument(documentId: string): Promise<DocumentPayload> {
  const { data } = await api.get(`/api/documents/${documentId}`);
  return data;
}

export async function exportDocument(
  documentId: string,
  edits: Array<{ block_id: string; page_number: number; new_content: string }>
): Promise<{ download_url: string }> {
  const { data } = await api.post(`/api/documents/${documentId}/export`, { edits });
  return data;
}
