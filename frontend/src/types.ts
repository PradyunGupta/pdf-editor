export type BBox = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type Block = {
  id: string;
  type: "text";
  content: string;
  bbox: BBox;
  font: {
    size_pts: number;
  };
  confidence: number;
};

export type Page = {
  page_number: number;
  width_px: number;
  height_px: number;
  dpi: number;
  background_image_path: string;
  blocks: Block[];
};

export type DocumentPayload = {
  document: {
    id: string;
    page_count: number;
    pages: Page[];
  };
};

export type StatusPayload = {
  document_id: string;
  status: "processing" | "ready" | "error";
  progress: number;
  error_message: string | null;
};
