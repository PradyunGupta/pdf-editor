# PDF Editor — Comprehensive Technical Plan

---

## Table of Contents

1. [Project Overview & Philosophy](#1-project-overview--philosophy)
2. [System Architecture](#2-system-architecture)
3. [PDF Classification & Detection](#3-pdf-classification--detection)
4. [Intermediate JSON Representation](#4-intermediate-json-representation)
5. [Text-Based PDF Pipeline](#5-text-based-pdf-pipeline)
6. [Scanned / Image-Based PDF Pipeline](#6-scanned--image-based-pdf-pipeline)
7. [Table Extraction & Handling](#7-table-extraction--handling)
8. [Bounding Box Accuracy](#8-bounding-box-accuracy)
9. [Font Matching & Metric Compensation](#9-font-matching--metric-compensation)
10. [Frontend WYSIWYG Editor](#10-frontend-wysiwyg-editor)
11. [PDF Reconstruction](#11-pdf-reconstruction)
12. [Backend API Design](#12-backend-api-design)
13. [Tech Stack Summary](#13-tech-stack-summary)
14. [Testing & Validation Strategy](#14-testing--validation-strategy)
15. [Known Tradeoffs & Honest Limitations](#15-known-tradeoffs--honest-limitations)
16. [Implementation Roadmap](#16-implementation-roadmap)

---

## 1. Project Overview & Philosophy

### What We're Building

A general-purpose PDF editor that allows users to modify text content in any kind of PDF — whether it is a digitally generated document, a scanned image, a form, or a document with complex tables — and download a reconstructed PDF that is visually faithful to the original with only their changes applied.

### The Core Problem With PDF Editing

PDFs are not Word documents. They are closer to a printed page — a fixed layout format where:

- Text is stored as absolutely positioned character glyphs, not as flowing paragraphs
- There is no native concept of "tables", "headings", or "columns"
- Fonts are partially embedded (only the characters used in the document)
- Coordinate origin is bottom-left (opposite of screen coordinates)
- Scanned PDFs have no text at all — just pixel images

This means you cannot simply "open and edit" a PDF the way you would a .docx file. Every approach involves tradeoffs.

### Our Chosen Philosophy

> **Do not try to reverse-engineer the PDF's internal structure. Render it visually, let the user edit visually, and reconstruct minimally.**

We convert every PDF page to a high-resolution image, overlay editable text blocks at the correct positions, let the user make changes, and then reconstruct only the changed regions. Everything else — images, graphics, decorative elements, signatures — stays untouched as the background.

This is the same fundamental approach used by professional tools like Adobe Acrobat and Smallpdf. It is not perfect, but it is the most robust general-purpose approach available.

---

## 2. System Architecture

### High-Level Flow

```
User uploads PDF
        │
        ▼
┌─────────────────────────────────┐
│   PDF Classifier                │
│   Detects: text / scanned /     │
│   hybrid / encrypted            │
└──────────┬──────────────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
Text PDF      Scanned PDF
Pipeline      Pipeline
    │             │
    └──────┬──────┘
           │ Both converge to same JSON schema
           ▼
┌─────────────────────────────────┐
│   Intermediate JSON             │
│   Representation                │
│   (pages, blocks, fonts,        │
│    bboxes, tables, images)      │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│   Frontend WYSIWYG Editor       │
│   Canvas (background image) +   │
│   Editable text overlays        │
└──────────┬──────────────────────┘
           │ User makes edits
           ▼
┌─────────────────────────────────┐
│   JSON Patch (only changes)     │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│   PDF Reconstructor             │
│   Background image + new text   │
│   overlaid at correct positions │
└──────────┬──────────────────────┘
           │
           ▼
     Output PDF download
```

### The Canvas + Overlay Model

This is the central architectural decision of the entire system.

```
┌────────────────────────────────────┐
│  Layer 2: Editable text overlays   │  ← Only what the user sees and edits
│  (positioned absolutely over bg)   │
├────────────────────────────────────┤
│  Layer 1: Background page image    │  ← Original PDF rendered at 300 DPI
│  (PNG, never modified)             │     Never touched, always faithful
└────────────────────────────────────┘
```

The user sees their real PDF. Text blocks float on top as editable elements. When the user edits a block:

1. That region gets redacted from the background image (painted over with sampled background color)
2. New text is rendered on top using the matched font and size
3. Everything else on the page is completely untouched

### Why This Approach Beats Alternatives

| Approach | Why We Rejected It |
|---|---|
| Direct PDF overwrite (PyPDF2) | Font must be embedded; no reflow; silent failures |
| Extract → Rebuild from scratch | Loses all formatting, images, layout complexity |
| Convert to DOCX then back | Two lossy conversions; complex layouts shatter |
| Raw PDF syntax manipulation | One wrong byte corrupts entire file |

---

## 3. PDF Classification & Detection

Before any processing, every uploaded PDF must be classified. The classification determines which pipeline runs.

### Classification Types

| Type | Description | Pipeline |
|---|---|---|
| `text` | Digitally created, text is extractable | Text pipeline |
| `scanned` | Pages are raster images, no text layer | OCR pipeline |
| `hybrid` | Mix of real text and image pages | Both pipelines per page |
| `encrypted` | Password protected | Prompt user for password first |
| `corrupted` | Malformed or incomplete | Attempt repair or reject |

### Detection Algorithm

```python
import fitz  # PyMuPDF

def classify_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    results = []

    for page_num, page in enumerate(doc):
        text = page.get_text("text").strip()
        image_list = page.get_images(full=True)

        char_count = len(text)
        image_count = len(image_list)

        if char_count > 50:
            page_type = "text"
        elif image_count > 0 and char_count < 10:
            page_type = "scanned"
        elif image_count > 0 and char_count >= 10:
            page_type = "hybrid"
        else:
            page_type = "text"  # Empty or minimal page

        results.append({
            "page": page_num + 1,
            "type": page_type,
            "char_count": char_count,
            "image_count": image_count
        })

    return results
```

### Encryption Handling

```python
def check_encryption(pdf_path, password=None):
    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if password:
            success = doc.authenticate(password)
            if not success:
                raise ValueError("Incorrect password")
        else:
            raise ValueError("PDF is encrypted. Password required.")
    return doc
```

---

## 4. Intermediate JSON Representation

The JSON schema is the single source of truth. Every pipeline converges to this format. The frontend renders from it. The reconstructor builds from it. Getting this right is the foundation of everything.

### Top-Level Schema

```json
{
  "document": {
    "id": "uuid-string",
    "original_filename": "report.pdf",
    "page_count": 5,
    "created_at": "2024-01-15T10:30:00Z",
    "pages": [ /* array of page objects */ ]
  }
}
```

### Page Object

```json
{
  "page_number": 1,
  "width_pts": 612,
  "height_pts": 792,
  "width_px": 2550,
  "height_px": 3300,
  "dpi": 300,
  "source": "text",
  "background_image_path": "page_1_bg.png",
  "rotation": 0,
  "skew_corrected": false,
  "skew_angle": 0.0,
  "blocks": [ /* array of block objects */ ]
}
```

### Text Block Object

```json
{
  "id": "block_001",
  "type": "text",
  "content": "Annual Report 2024",
  "bbox": {
    "x0": 100,
    "y0": 200,
    "x1": 400,
    "y1": 220,
    "coordinate_space": "image_pixels"
  },
  "font": {
    "original_name": "ABCDEF+Helvetica-Bold",
    "normalized_name": "Helvetica",
    "family": "sans_serif",
    "matched_font": "Arial",
    "match_confidence": 0.92,
    "size_pts": 14.0,
    "bold": true,
    "italic": false,
    "color_hex": "#1a1a1a",
    "scale_compensation": 1.03
  },
  "source": "pymupdf",
  "ocr_confidence": null,
  "edited": false,
  "original_content": "Annual Report 2024"
}
```

### Table Block Object

```json
{
  "id": "block_002",
  "type": "table",
  "bbox": {
    "x0": 50,
    "y0": 400,
    "x1": 550,
    "y1": 600,
    "coordinate_space": "image_pixels"
  },
  "source": "camelot",
  "has_borders": true,
  "rows": [
    {
      "row_index": 0,
      "is_header": true,
      "cells": [
        {
          "cell_id": "r0c0",
          "content": "Name",
          "bbox": { "x0": 50, "y0": 400, "x1": 200, "y1": 420, "coordinate_space": "image_pixels" },
          "colspan": 1,
          "rowspan": 1,
          "font": { /* same font object */ },
          "alignment": "left"
        }
      ]
    }
  ]
}
```

### Image Region Block Object

```json
{
  "id": "block_003",
  "type": "image_region",
  "bbox": {
    "x0": 100,
    "y0": 50,
    "x1": 400,
    "y1": 200,
    "coordinate_space": "image_pixels"
  },
  "description": "company_logo",
  "raw_image_path": "page_1_img_003.png",
  "editable": false
}
```

### Edit Delta Object (what the frontend sends back)

```json
{
  "document_id": "uuid-string",
  "edits": [
    {
      "block_id": "block_001",
      "page_number": 1,
      "new_content": "Annual Report 2025",
      "font_override": null,
      "timestamp": "2024-01-15T11:00:00Z"
    }
  ]
}
```

---

## 5. Text-Based PDF Pipeline

### Step 1 — Render Pages to Images

```python
import fitz
from pathlib import Path

def render_pages(pdf_path, output_dir, dpi=300):
    doc = fitz.open(pdf_path)
    page_images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        image_path = Path(output_dir) / f"page_{page_num + 1}_bg.png"
        pix.save(str(image_path))
        page_images.append({
            "page": page_num + 1,
            "path": str(image_path),
            "width_px": pix.width,
            "height_px": pix.height,
            "width_pts": page.rect.width,
            "height_pts": page.rect.height
        })

    return page_images
```

Note: Always render at 300 DPI for the extraction/reconstruction pipeline. You may render a separate 150 DPI version purely for frontend preview display to reduce bandwidth.

### Step 2 — Extract Text Blocks

```python
def extract_text_blocks(pdf_path, dpi=300):
    scale = dpi / 72
    doc = fitz.open(pdf_path)
    all_blocks = []

    for page_num, page in enumerate(doc):
        page_height_pts = page.rect.height

        blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block["type"] != 0:  # 0 = text block
                continue

            for line in block["lines"]:
                for span in line["spans"]:
                    bbox_pts = span["bbox"]

                    # Convert to image pixel space with Y-flip
                    x0 = bbox_pts[0] * scale
                    y0 = (page_height_pts - bbox_pts[3]) * scale  # flip Y
                    x1 = bbox_pts[2] * scale
                    y1 = (page_height_pts - bbox_pts[1]) * scale  # flip Y

                    all_blocks.append({
                        "page": page_num + 1,
                        "content": span["text"],
                        "bbox": {
                            "x0": round(x0, 2),
                            "y0": round(y0, 2),
                            "x1": round(x1, 2),
                            "y1": round(y1, 2),
                            "coordinate_space": "image_pixels"
                        },
                        "font_raw": span["font"],
                        "font_size": round(span["size"], 2),
                        "font_color": span["color"],
                        "font_flags": span["flags"],  # bold/italic bitmask
                        "source": "pymupdf"
                    })

    return all_blocks
```

### Step 3 — Font Flag Decoding

PyMuPDF encodes font style as a bitmask in the `flags` field:

```python
def decode_font_flags(flags):
    return {
        "superscript": bool(flags & 1),
        "italic":      bool(flags & 2),
        "serif":       bool(flags & 4),
        "monospace":   bool(flags & 8),
        "bold":        bool(flags & 16)
    }
```

### Step 4 — Reading Order Correction

PDF blocks are not always stored in reading order. For multi-column layouts, a naive extraction reads all of column 1 and column 2 interleaved. You must sort blocks into correct reading order:

```python
def sort_blocks_reading_order(blocks):
    # Sort by Y first (top to bottom), then X (left to right)
    # Use a tolerance band for Y to handle text on the same "line"
    TOLERANCE = 5  # pixels

    def sort_key(block):
        y_band = round(block["bbox"]["y0"] / TOLERANCE)
        return (y_band, block["bbox"]["x0"])

    return sorted(blocks, key=sort_key)
```

---

## 6. Scanned / Image-Based PDF Pipeline

### Step 1 — Extract Page Images From PDF

Scanned PDFs already contain images. Extract them at native resolution first:

```python
def extract_page_images(pdf_path, output_dir, dpi=300):
    # For scanned PDFs, render at 300 DPI just like text PDFs
    # This normalizes both pipelines to the same image space
    return render_pages(pdf_path, output_dir, dpi=dpi)
```

### Step 2 — Image Preprocessing

This step is critical and often skipped. Raw scans are noisy, skewed, and low contrast. Running OCR on an unprocessed scan gives poor results.

```python
import cv2
import numpy as np

def preprocess_for_ocr(image_path):
    image = cv2.imread(image_path)

    # Step 2a: Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Step 2b: Deskew
    gray = deskew_image(gray)

    # Step 2c: Denoise
    gray = cv2.fastNlMeansDenoising(gray, h=10)

    # Step 2d: Binarize (Otsu's threshold)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return binary


def deskew_image(gray_image):
    edges = cv2.Canny(gray_image, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)

    if lines is None:
        return gray_image

    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        angle = (theta * 180 / np.pi) - 90
        angles.append(angle)

    if not angles:
        return gray_image

    median_angle = np.median(angles)

    # Only correct meaningful but non-intentional rotation
    if 0.5 < abs(median_angle) < 45:
        h, w = gray_image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        corrected = cv2.warpAffine(gray_image, M, (w, h),
                                    flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_REPLICATE)
        return corrected, median_angle

    return gray_image, 0.0
```

### Step 3 — OCR Engine Options

#### Option A: Tesseract (Open Source, Local)

```python
import pytesseract
from PIL import Image

def run_tesseract_ocr(image_path):
    image = Image.open(image_path)

    # Use detailed data output including bounding boxes
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config='--psm 3'  # PSM 3 = fully automatic page segmentation
    )

    blocks = []
    n = len(data['text'])

    for i in range(n):
        text = data['text'][i].strip()
        conf = int(data['conf'][i])

        if not text or conf < 30:  # Skip low confidence and empty
            continue

        x = data['left'][i]
        y = data['top'][i]
        w = data['width'][i]
        h = data['height'][i]

        blocks.append({
            "content": text,
            "bbox": {
                "x0": x, "y0": y,
                "x1": x + w, "y1": y + h,
                "coordinate_space": "image_pixels"
            },
            "ocr_confidence": conf / 100.0,
            "source": "tesseract"
        })

    return blocks
```

#### Option B: AWS Textract (Cloud, Higher Accuracy)

Best for production use when accuracy is critical, especially for tables in scanned documents. Returns structured table data directly.

```python
import boto3

def run_textract_ocr(image_bytes):
    client = boto3.client('textract', region_name='us-east-1')

    response = client.detect_document_text(
        Document={'Bytes': image_bytes}
    )

    blocks = []
    for block in response['Blocks']:
        if block['BlockType'] != 'WORD':
            continue

        bbox = block['Geometry']['BoundingBox']
        # Textract returns normalized 0-1 coordinates
        # Must be multiplied by image dimensions
        blocks.append({
            "content": block['Text'],
            "bbox_normalized": bbox,  # Convert to pixels using image dimensions
            "ocr_confidence": block['Confidence'] / 100.0,
            "source": "textract"
        })

    return blocks
```

### Step 4 — Post-OCR Text Grouping

Tesseract returns individual words. You need to group them into logical lines and paragraphs:

```python
def group_words_into_lines(word_blocks, line_gap_threshold=10):
    if not word_blocks:
        return []

    sorted_words = sorted(word_blocks, key=lambda b: (b['bbox']['y0'], b['bbox']['x0']))
    lines = []
    current_line = [sorted_words[0]]

    for word in sorted_words[1:]:
        prev = current_line[-1]
        y_diff = abs(word['bbox']['y0'] - prev['bbox']['y0'])

        if y_diff <= line_gap_threshold:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]

    lines.append(current_line)

    # Merge each line into a single block
    merged = []
    for line in lines:
        merged_text = ' '.join(w['content'] for w in line)
        min_conf = min(w['ocr_confidence'] for w in line)
        x0 = min(w['bbox']['x0'] for w in line)
        y0 = min(w['bbox']['y0'] for w in line)
        x1 = max(w['bbox']['x1'] for w in line)
        y1 = max(w['bbox']['y1'] for w in line)

        merged.append({
            "content": merged_text,
            "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                     "coordinate_space": "image_pixels"},
            "ocr_confidence": min_conf,
            "source": "tesseract"
        })

    return merged
```

### OCR Confidence Thresholds

| Confidence | Action |
|---|---|
| > 0.90 | Render normally |
| 0.70 – 0.90 | Render with subtle yellow highlight in UI |
| 0.50 – 0.70 | Render with orange highlight, user prompted to review |
| < 0.50 | Render with red highlight, warn user explicitly |

---

## 7. Table Extraction & Handling

### The Core Problem

PDFs have no native concept of a "table." What looks like a table is:

- Text blocks positioned at grid-like coordinates
- Separate vector line/rectangle paths drawn independently
- The visual grid is not linked to the text in any way

### Strategy by PDF Type

#### Text PDFs with Visible Borders → Camelot

```python
import camelot

def extract_tables_camelot(pdf_path, page_num):
    tables = camelot.read_pdf(
        pdf_path,
        pages=str(page_num),
        flavor='lattice'  # Use 'stream' for borderless tables
    )

    result = []
    for table in tables:
        df = table.df
        rows = []
        for r_idx, row in df.iterrows():
            cells = []
            for c_idx, cell_content in enumerate(row):
                cells.append({
                    "cell_id": f"r{r_idx}c{c_idx}",
                    "content": str(cell_content).strip(),
                    "colspan": 1,
                    "rowspan": 1
                })
            rows.append({
                "row_index": r_idx,
                "is_header": r_idx == 0,
                "cells": cells
            })
        result.append({
            "type": "table",
            "rows": rows,
            "source": "camelot",
            "accuracy": table.accuracy
        })

    return result
```

#### Borderless or Scanned Tables → AWS Textract AnalyzeDocument

For tables in scanned documents or tables without visible borders, Textract's AnalyzeDocument API returns explicit CELL and TABLE block types with parent-child relationships:

```python
def extract_tables_textract(image_bytes):
    client = boto3.client('textract')
    response = client.analyze_document(
        Document={'Bytes': image_bytes},
        FeatureTypes=['TABLES']
    )
    # Parse the block relationships to reconstruct the table grid
    # TABLE → ROW → CELL → WORD hierarchy
    return parse_textract_table_blocks(response['Blocks'])
```

### Table JSON Schema

```json
{
  "id": "table_001",
  "type": "table",
  "bbox": { "x0": 50, "y0": 400, "x1": 550, "y1": 600, "coordinate_space": "image_pixels" },
  "has_borders": true,
  "extraction_accuracy": 0.97,
  "source": "camelot",
  "rows": [
    {
      "row_index": 0,
      "is_header": true,
      "cells": [
        {
          "cell_id": "r0c0",
          "content": "Product Name",
          "bbox": { "x0": 50, "y0": 400, "x1": 200, "y1": 420 },
          "colspan": 1,
          "rowspan": 1,
          "font": { "matched_font": "Arial", "size_pts": 11, "bold": true },
          "alignment": "left",
          "background_color": "#f0f0f0"
        }
      ]
    }
  ]
}
```

### Critical Table Edge Cases

**Merged cells:** Camelot doesn't always detect colspan/rowspan. If a cell spans multiple columns, the extracted content appears in only the first cell with empty strings in the merged positions. Post-processing is needed:

```python
def detect_merged_cells(rows):
    for r_idx, row in enumerate(rows):
        for c_idx, cell in enumerate(row['cells']):
            if cell['content'] == '' and r_idx > 0:
                # Check if previous row's cell at same column is non-empty
                # and if vertical span is indicated by bbox height
                pass  # Implement spanning logic based on bbox comparison
```

**Multi-line cell content:** Text in a cell that wraps across multiple lines comes back as a single string with newlines. Preserve these newlines in your JSON so the frontend can render them correctly.

**Tables spanning multiple pages:** Camelot treats each page independently. If a table spans pages, you'll get two separate tables. Detect this by checking if the last row of page N and the first row of page N+1 have matching column structures.

---

## 8. Bounding Box Accuracy

This is one of the two load-bearing pillars of the system. Incorrect bounding boxes make the editor feel broken at a fundamental level.

### The Coordinate System Problem

There are three coordinate spaces to reconcile:

| Space | Origin | Y Direction | Units |
|---|---|---|---|
| PDF space | Bottom-left | Increases upward | Points (1/72 inch) |
| Image pixel space | Top-left | Increases downward | Pixels |
| CSS/screen space | Top-left | Increases downward | CSS pixels |

### The Canonical Transformation

```python
def pdf_pts_to_image_px(x_pts, y_pts, page_height_pts, dpi=300):
    scale = dpi / 72.0
    image_x = x_pts * scale
    image_y = (page_height_pts - y_pts) * scale  # Y-flip is critical
    return image_x, image_y

def image_px_to_css_px(image_x, image_y, image_width_px, display_width_css):
    css_scale = display_width_css / image_width_px
    return image_x * css_scale, image_y * css_scale
```

### DPI Strategy

| Use Case | DPI | Reason |
|---|---|---|
| Background image preview (frontend) | 150 | Fast load, acceptable quality |
| Extraction coordinate reference | 300 | High accuracy |
| PDF reconstruction | 300 | Output quality |
| Debug/validation images | 300 | Need to see details |

All coordinate values in your JSON must reference the **300 DPI image space**. The frontend scales them to the display size dynamically.

### Subpixel Padding

PDF parsers report tight bounding boxes that clip ascenders and descenders:

```python
def expand_bbox_for_rendering(bbox, font_size_pts):
    padding_x = font_size_pts * 0.05
    padding_y = font_size_pts * 0.15  # More vertical for ascenders/descenders

    return {
        "x0": bbox["x0"] - padding_x,
        "y0": bbox["y0"] - padding_y,
        "x1": bbox["x1"] + padding_x,
        "y1": bbox["y1"] + padding_y,
        "coordinate_space": bbox["coordinate_space"]
    }
```

### Deskewing Coordinate Correction

When you deskew a scanned image before OCR, all subsequent bounding boxes are in the corrected image space. You must save the skew angle and apply it if you ever need to map back to the original image:

```python
def rotate_bbox_back(bbox, skew_angle_degrees, image_width, image_height):
    # Apply inverse rotation to map corrected-space bbox back to original
    theta = -np.radians(skew_angle_degrees)
    cx, cy = image_width / 2, image_height / 2

    def rotate_point(x, y):
        x, y = x - cx, y - cy
        x_new = x * np.cos(theta) - y * np.sin(theta)
        y_new = x * np.sin(theta) + y * np.cos(theta)
        return x_new + cx, y_new + cy

    corners = [
        rotate_point(bbox["x0"], bbox["y0"]),
        rotate_point(bbox["x1"], bbox["y0"]),
        rotate_point(bbox["x0"], bbox["y1"]),
        rotate_point(bbox["x1"], bbox["y1"])
    ]

    return {
        "x0": min(c[0] for c in corners),
        "y0": min(c[1] for c in corners),
        "x1": max(c[0] for c in corners),
        "y1": max(c[1] for c in corners)
    }
```

### Validation Harness

Build this before building the editor UI. Run it on 20-30 diverse test PDFs:

```python
def visualize_bboxes_debug(page_image_path, blocks, output_path):
    image = cv2.imread(page_image_path)

    color_map = {
        "text": (0, 0, 255),        # Red for text blocks
        "table": (0, 255, 0),       # Green for tables
        "image_region": (255, 0, 0) # Blue for images
    }

    for block in blocks:
        bbox = block["bbox"]
        color = color_map.get(block["type"], (128, 128, 128))
        cv2.rectangle(image,
                      (int(bbox["x0"]), int(bbox["y0"])),
                      (int(bbox["x1"]), int(bbox["y1"])),
                      color, 1)
        # Optionally draw block ID label
        cv2.putText(image, block["id"][:8],
                    (int(bbox["x0"]), int(bbox["y0"]) - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

    cv2.imwrite(output_path, image)
```

Target: > 95% of bounding boxes aligned within 2px tolerance on your test set before building any frontend.

---

## 9. Font Matching & Metric Compensation

This is the second load-bearing pillar. A font substitution that is even slightly wider or narrower than the original shifts text outside its bounding box, destroying the visual alignment.

### Font Name Normalization

PDF font names are inconsistent and often include subset prefixes:

```python
import re

def normalize_font_name(raw_name):
    # Strip subset prefix like "ABCDEF+"
    name = re.sub(r'^[A-Z]{6}\+', '', raw_name)

    # Normalize separators
    name = name.replace('-', ' ').replace('_', ' ')

    # Extract style hints from name
    is_bold = bool(re.search(r'\b(bold|heavy|black|demi)\b', name, re.I))
    is_italic = bool(re.search(r'\b(italic|oblique|slanted|cursive)\b', name, re.I))

    # Strip style words from base name
    base = re.sub(
        r'\b(bold|italic|oblique|heavy|light|regular|medium|thin|black|demi|semibold|semilight)\b',
        '', name, flags=re.I
    ).strip()

    return base, {"bold": is_bold, "italic": is_italic}
```

### Font Family Classification

```python
FONT_FAMILY_MAP = {
    "serif": [
        "times", "georgia", "garamond", "palatino", "bookman",
        "cambria", "constantia", "minion", "caslon", "baskerville",
        "bodoni", "century", "charter", "didot", "goudy"
    ],
    "sans_serif": [
        "helvetica", "arial", "calibri", "verdana", "tahoma",
        "trebuchet", "futura", "gill", "franklin", "myriad",
        "frutiger", "univers", "optima", "open sans", "lato",
        "roboto", "source sans", "noto sans"
    ],
    "monospace": [
        "courier", "consolas", "monaco", "menlo", "inconsolata",
        "source code", "fira code", "jetbrains mono", "hack"
    ],
    "display": [
        "impact", "bebas", "oswald", "anton", "black han",
        "alfa slab", "ultra"
    ],
    "handwriting": [
        "pacifico", "dancing script", "caveat", "satisfy",
        "permanent marker", "kalam"
    ]
}

FAMILY_FALLBACKS = {
    "serif":       "Georgia",
    "sans_serif":  "Arial",
    "monospace":   "Courier New",
    "display":     "Impact",
    "handwriting": "Georgia"  # Best we can do without the actual font
}

def classify_font_family(normalized_name):
    name_lower = normalized_name.lower()
    for family, keywords in FONT_FAMILY_MAP.items():
        if any(kw in name_lower for kw in keywords):
            return family
    return "sans_serif"  # Default
```

### Match Confidence Scoring

```python
def compute_match_confidence(original_name, matched_font):
    original_lower = original_name.lower()
    matched_lower = matched_font.lower()

    # Exact match after normalization
    if original_lower == matched_lower:
        return 1.0

    # Family keyword present in both
    for family, keywords in FONT_FAMILY_MAP.items():
        orig_in_family = any(kw in original_lower for kw in keywords)
        match_in_family = any(kw in matched_lower for kw in keywords)
        if orig_in_family and match_in_family:
            return 0.85

    # Partial name match
    if any(word in matched_lower for word in original_lower.split() if len(word) > 3):
        return 0.70

    # Only family classification matched
    return 0.50
```

### Metric Compensation

Different fonts have different advance widths. "Hello" in Arial is a different pixel width than "Hello" in Helvetica, even at the same point size. Without compensation, edited text overflows its bounding box.

```python
from PIL import ImageFont, ImageDraw, Image

def measure_text_width_px(text, font_path, font_size_pts, dpi=300):
    font_size_px = int(font_size_pts * dpi / 72)
    font = ImageFont.truetype(font_path, font_size_px)
    img = Image.new('RGB', (10000, 200))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]  # width

def compute_scale_compensation(text, original_font_path, replacement_font_path, font_size_pts):
    orig_width = measure_text_width_px(text, original_font_path, font_size_pts)
    repl_width = measure_text_width_px(text, replacement_font_path, font_size_pts)

    if repl_width == 0:
        return 1.0

    return orig_width / repl_width
```

Apply this compensation as:
- `letter-spacing` CSS adjustment in the frontend editor
- Character spacing in ReportLab when reconstructing the PDF

### Font Size Overflow Handling

If the user types more text than fits in the original bounding box:

```python
def fit_text_to_bbox(text, font_path, bbox, starting_size_pts, min_size_pts=6):
    bbox_width = bbox["x1"] - bbox["x0"]
    current_size = starting_size_pts

    while current_size >= min_size_pts:
        width = measure_text_width_px(text, font_path, current_size)
        if width <= bbox_width:
            return current_size, False  # Fits, no size change
        current_size -= 0.5

    return min_size_pts, True  # Had to shrink, flag this to user
```

The frontend should show a visual warning indicator when font size was reduced to fit.

---

## 10. Frontend WYSIWYG Editor

### Technology Choice: Fabric.js or Konva.js

Both are canvas-based libraries well suited for this use case.

| | Fabric.js | Konva.js |
|---|---|---|
| Text editing | Built-in IText | Manual implementation |
| Performance | Good | Excellent (React integration) |
| Learning curve | Lower | Moderate |
| Community | Larger | Active |

**Recommendation: Fabric.js** for faster development of the text editing feature. Konva.js for higher performance on very large documents.

### Page Rendering

```javascript
const canvas = new fabric.Canvas('editor-canvas');

async function loadPage(pageData) {
    // Load background image
    fabric.Image.fromURL(pageData.backgroundImageUrl, (bgImage) => {
        bgImage.set({
            left: 0,
            top: 0,
            selectable: false,
            evented: false
        });
        canvas.setBackgroundImage(bgImage, canvas.renderAll.bind(canvas));
        canvas.setWidth(bgImage.width);
        canvas.setHeight(bgImage.height);
    });

    // Add text overlays
    pageData.blocks
        .filter(block => block.type === 'text')
        .forEach(block => addTextOverlay(block));
}
```

### Text Overlay Rendering

```javascript
function addTextOverlay(block) {
    const { bbox, font, content } = block;
    
    const textObj = new fabric.IText(content, {
        left: bbox.x0,
        top: bbox.y0,
        width: bbox.x1 - bbox.x0,
        fontSize: font.size_pts * (300 / 72),  // Convert pts to pixels at 300 DPI
        fontFamily: font.matched_font,
        fontWeight: font.bold ? 'bold' : 'normal',
        fontStyle: font.italic ? 'italic' : 'normal',
        fill: font.color_hex,
        backgroundColor: 'transparent',
        
        // Custom metadata
        data: {
            blockId: block.id,
            originalContent: block.original_content,
            ocrConfidence: block.ocr_confidence,
            matchConfidence: block.font.match_confidence
        },
        
        // Visual styling
        borderColor: getConfidenceColor(block.ocr_confidence),
        cornerColor: '#0066cc',
        hasRotatingPoint: false,
        lockRotation: true,
        lockScalingX: false,
        lockScalingY: false
    });

    // Event: track edit
    textObj.on('changed', () => {
        markBlockEdited(block.id, textObj.text);
    });

    canvas.add(textObj);
}

function getConfidenceColor(confidence) {
    if (confidence === null) return 'transparent';       // Text PDF, no OCR
    if (confidence >= 0.90) return 'transparent';
    if (confidence >= 0.70) return '#FFD700';  // Yellow
    if (confidence >= 0.50) return '#FF8C00';  // Orange
    return '#FF0000';                           // Red
}
```

### Table Cell Editing

Each table cell should be individually clickable and editable. Render the background image (which includes the table borders visually) and overlay each cell's text independently:

```javascript
function addTableOverlay(tableBlock) {
    tableBlock.rows.forEach(row => {
        row.cells.forEach(cell => {
            const cellText = new fabric.IText(cell.content, {
                left: cell.bbox.x0 + 4,  // Small inner padding
                top: cell.bbox.y0 + 4,
                width: (cell.bbox.x1 - cell.bbox.x0) - 8,
                fontSize: cell.font.size_pts * (300 / 72),
                fontFamily: cell.font.matched_font,
                fontWeight: cell.font.bold ? 'bold' : 'normal',
                data: {
                    blockId: tableBlock.id,
                    cellId: cell.cell_id,
                    type: 'table_cell'
                }
            });
            canvas.add(cellText);
        });
    });
}
```

### Edit Change Tracking

```javascript
const editDelta = {
    documentId: null,
    edits: []
};

function markBlockEdited(blockId, newContent) {
    const existingEdit = editDelta.edits.find(e => e.block_id === blockId);
    if (existingEdit) {
        existingEdit.new_content = newContent;
    } else {
        editDelta.edits.push({
            block_id: blockId,
            new_content: newContent,
            timestamp: new Date().toISOString()
        });
    }
}
```

### UI Features Required

- Page navigation (prev/next page)
- Zoom in/out
- Undo/redo stack
- Search and replace across all blocks
- OCR confidence indicators (colored borders)
- Font size warning indicator when text overflows
- Download button that sends the edit delta to the backend

---

## 11. PDF Reconstruction

### Strategy: Background Redact + Overlay

For each page that has edits:

1. Load the background PNG (300 DPI)
2. For each edited block, sample the background color around the text area
3. Paint a filled rectangle over the original text (redaction)
4. Draw the new text on top using the matched font

For pages with no edits, the background PNG is used as-is.

### Reconstruction with PyMuPDF

```python
import fitz
from PIL import Image, ImageDraw, ImageFont

def reconstruct_page(background_image_path, edited_blocks, output_pdf_page):
    image = Image.open(background_image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for block in edited_blocks:
        if not block.get("edited"):
            continue

        bbox = block["bbox"]
        new_content = block["new_content"]
        font_info = block["font"]

        # Step 1: Sample background color (use area around the block)
        sample_area = (
            max(0, int(bbox["x0"]) - 2),
            max(0, int(bbox["y0"]) - 2),
            min(image.width, int(bbox["x1"]) + 2),
            min(image.height, int(bbox["y1"]) + 2)
        )
        region = image.crop(sample_area)
        # Get most common color in the region (background)
        bg_color = get_dominant_color(region)

        # Step 2: Redact original text
        draw.rectangle(
            [int(bbox["x0"]), int(bbox["y0"]),
             int(bbox["x1"]), int(bbox["y1"])],
            fill=bg_color
        )

        # Step 3: Draw new text
        font_size_px = int(font_info["size_pts"] * 300 / 72)
        try:
            font = ImageFont.truetype(
                resolve_font_path(font_info["matched_font"],
                                  font_info["bold"],
                                  font_info["italic"]),
                font_size_px
            )
        except Exception:
            font = ImageFont.load_default()

        text_color = hex_to_rgb(font_info["color_hex"])
        draw.text(
            (int(bbox["x0"]), int(bbox["y0"])),
            new_content,
            fill=text_color,
            font=font
        )

    return image


def get_dominant_color(region_image):
    pixels = list(region_image.getdata())
    from collections import Counter
    color_counts = Counter(pixels)
    return color_counts.most_common(1)[0][0]


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
```

### Assembling the Final PDF

```python
def assemble_pdf(pages_data, edited_blocks_by_page, output_path, dpi=300):
    doc = fitz.open()

    for page_data in pages_data:
        page_num = page_data["page_number"]
        edited_blocks = edited_blocks_by_page.get(page_num, [])

        if edited_blocks:
            # Reconstruct this page with edits
            reconstructed_image = reconstruct_page(
                page_data["background_image_path"],
                edited_blocks
            )
            image_bytes = image_to_bytes(reconstructed_image)
        else:
            # Use original background image directly (no edits)
            with open(page_data["background_image_path"], "rb") as f:
                image_bytes = f.read()

        # Insert image as a PDF page at correct dimensions
        img_pdf = fitz.open("png", image_bytes)
        doc.insert_pdf(img_pdf)

    doc.save(output_path, deflate=True, garbage=4)
    return output_path
```

### Searchable Text Layer (Optional Enhancement)

If you want the output PDF to be searchable (text selectable in PDF readers), add an invisible text layer on top of the image:

```python
def add_searchable_text_layer(pdf_page, blocks, dpi=300):
    scale = 72 / dpi  # Convert from image pixels back to PDF points

    for block in blocks:
        if block["type"] != "text":
            continue

        bbox = block["bbox"]
        content = block.get("new_content") or block["content"]

        # Convert pixel coordinates back to PDF points
        rect = fitz.Rect(
            bbox["x0"] * scale,
            bbox["y0"] * scale,
            bbox["x1"] * scale,
            bbox["y1"] * scale
        )

        # Insert invisible text (render_mode=3 means invisible)
        pdf_page.insert_text(
            rect.tl,
            content,
            fontsize=block["font"]["size_pts"],
            render_mode=3  # Invisible but selectable/searchable
        )
```

---

## 12. Backend API Design

### Endpoints

#### POST /api/upload
Upload a PDF and trigger processing.

```
Request:  multipart/form-data { file: PDF }
Response: {
  "document_id": "uuid",
  "status": "processing",
  "page_count": 5,
  "estimated_seconds": 12
}
```

#### GET /api/documents/{document_id}/status
Poll for processing completion.

```
Response: {
  "document_id": "uuid",
  "status": "ready" | "processing" | "error",
  "progress": 0.75,
  "error_message": null
}
```

#### GET /api/documents/{document_id}/pages/{page_number}
Get the JSON representation and background image URL for a single page.

```
Response: {
  "page": { /* full page object from schema */ },
  "background_image_url": "/static/pages/uuid_page_1_150dpi.png"
}
```

#### POST /api/documents/{document_id}/export
Submit edits and get back a reconstructed PDF.

```
Request: {
  "edits": [
    { "block_id": "block_001", "page_number": 1, "new_content": "..." }
  ]
}
Response: {
  "download_url": "/api/documents/uuid/download",
  "expires_at": "2024-01-15T12:00:00Z"
}
```

#### GET /api/documents/{document_id}/download
Stream the reconstructed PDF file.

### Processing Queue

For large documents, processing should be async. Use a task queue (Celery + Redis):

```
Upload → Queue task → Return document_id
Frontend polls /status every 2 seconds
When status = "ready", frontend loads the editor
```

### File Storage

```
/storage/
  /uploads/
    {document_id}.pdf                # Original upload
  /pages/
    {document_id}_page_1_bg_300.png  # High-res background
    {document_id}_page_1_bg_150.png  # Preview background
  /outputs/
    {document_id}_edited.pdf         # Reconstructed PDF
  /json/
    {document_id}.json               # Full document JSON
```

---

## 13. Tech Stack Summary

### Backend

| Component | Technology | Purpose |
|---|---|---|
| Web framework | FastAPI (Python) | API endpoints, async support |
| PDF → Image | PyMuPDF (fitz) | Page rendering, text extraction |
| Image preprocessing | OpenCV | Deskewing, denoising, binarization |
| OCR (local) | Tesseract + pytesseract | Text extraction from scanned pages |
| OCR (cloud) | AWS Textract | High-accuracy OCR, table detection |
| Table extraction | Camelot | Bordered table structure parsing |
| Font tools | fonttools, Pillow | Font metrics, text width measurement |
| Task queue | Celery + Redis | Async processing of large PDFs |
| File storage | Local disk / S3 | Page images, JSON, outputs |
| PDF reconstruction | PyMuPDF + Pillow | Image compositing, PDF assembly |

### Frontend

| Component | Technology | Purpose |
|---|---|---|
| Framework | React | UI structure |
| Canvas editor | Fabric.js | WYSIWYG editing layer |
| State management | Zustand | Edit delta tracking |
| HTTP client | Axios | API calls |
| Polling | React Query | Status polling during processing |

---

## 14. Testing & Validation Strategy

### PDF Test Suite (Minimum 30 PDFs)

Assemble a diverse test set covering:

- Simple single-column text documents
- Multi-column academic papers
- Documents with bordered tables
- Documents with borderless/styled tables
- Scanned documents (clean scans)
- Scanned documents (noisy/skewed scans)
- PDFs with embedded images and mixed content
- RTL language documents (Arabic, Hebrew)
- CJK language documents (Chinese, Japanese, Korean)
- Password-protected PDFs
- PDFs with non-standard fonts
- PDFs exported from design tools (Figma, InDesign)
- Government/legal document PDFs
- Financial statement PDFs

### Bounding Box Accuracy Test

```python
def measure_bbox_accuracy(pdf_path, dpi=300):
    blocks = extract_text_blocks(pdf_path, dpi=dpi)
    page_image = render_pages(pdf_path, dpi=dpi)[0]
    
    misaligned = 0
    total = 0
    
    for block in blocks:
        bbox = block["bbox"]
        # Crop region from page image at bbox coordinates
        # Compare with what's visually there
        # For automated testing: check that the cropped region
        # is not predominantly background color (blank)
        region = crop_region(page_image, bbox)
        if is_blank_region(region):
            misaligned += 1
        total += 1
    
    accuracy = (total - misaligned) / total if total > 0 else 0
    return accuracy  # Target: > 0.95
```

### Font Matching Test

```python
def measure_font_match_quality(pdf_path):
    blocks = extract_text_blocks(pdf_path)
    confidences = [b["font"]["match_confidence"] for b in blocks]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    return avg_confidence  # Target: > 0.80
```

### End-to-End Reconstruction Test

For each test PDF, apply a simple edit (replace a known word) and verify:

1. The output PDF opens without errors
2. The edited text appears at the correct position
3. The surrounding content is not affected
4. The output is visually inspectable for quality

---

## 15. Known Tradeoffs & Honest Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Scanned PDFs lose original font entirely | Substituted font may look different | Let user pick font manually |
| Complex multi-column layouts may shift slightly | Minor visual difference | Acceptable; no tool avoids this |
| Proprietary/uncommon fonts cannot be matched | Text rendered in fallback font | Match confidence indicator in UI |
| Extraction errors on complex PDFs | Some text blocks may be mispositioned | Debug validation view in admin |
| OCR errors on low-quality scans | Wrong text pre-filled | Confidence highlighting prompts user review |
| Tables in scanned docs are hard | Cells may be misidentified | Flag with low confidence indicator |
| Text reflow across pages not automatic | Overflow requires manual resize | Visual overflow warning in editor |
| RTL text (Arabic/Hebrew) needs special handling | May render reversed | Plan as a separate feature phase |
| Handwriting is not supported | Will OCR poorly | Explicitly tell user we don't support this |
| Encrypted PDFs require user password | Adds friction | Password prompt dialog |
| Image-only pages cannot be edited | No text to overlay | Show as read-only page |

---

## 16. Implementation Roadmap

### Phase 1 — Foundation (Weeks 1–3)
- Set up FastAPI backend with upload endpoint
- Implement PDF classifier (text vs scanned vs hybrid vs encrypted)
- Build PDF → PNG renderer at 300 DPI and 150 DPI
- Build text block extractor (PyMuPDF) with correct coordinate transformation
- Build bounding box validation visualizer
- Define and finalize JSON schema
- Validate bboxes on 20 test PDFs. Target: > 95% accuracy

### Phase 2 — Font System (Weeks 4–5)
- Build font name normalizer and family classifier
- Build font matching with confidence scoring
- Build text width measurement and scale compensation
- Build font size overflow detection
- Test font matching on collected test PDFs. Target: > 80% avg confidence

### Phase 3 — OCR Pipeline (Weeks 6–7)
- Integrate Tesseract for scanned pages
- Build OpenCV preprocessing (deskew, denoise, binarize)
- Build word grouping into line blocks
- Implement OCR confidence thresholds and flagging
- Test on 10 scanned PDF samples

### Phase 4 — Table Extraction (Week 8)
- Integrate Camelot for text PDFs with bordered tables
- Build table JSON schema population
- Handle merged cells and multi-line cells
- Test on diverse table PDFs

### Phase 5 — Frontend Editor (Weeks 9–11)
- Build React + Fabric.js canvas editor
- Implement background image loading
- Implement text block overlays with correct positioning
- Implement edit delta tracking
- Implement OCR confidence visual indicators
- Implement table cell editing
- Implement page navigation

### Phase 6 — Reconstruction (Week 12)
- Build background color sampling and redaction
- Build text rendering onto image (Pillow)
- Build PDF assembly from reconstructed page images
- Build optional searchable text layer
- End-to-end test on all 30 test PDFs

### Phase 7 — API & Queue (Week 13)
- Wire up all backend endpoints
- Add Celery task queue for async processing
- Add status polling endpoint
- Build download endpoint

### Phase 8 — Hardening & Edge Cases (Weeks 14–15)
- Encrypted PDF handling
- RTL text detection (flag as unsupported for now)
- Large PDF performance testing
- Error handling and user-facing messages
- Final validation pass on full test suite

---

*This document represents the complete technical plan for the PDF editor. Every architectural decision has been made with the goal of maximum robustness across real-world PDF diversity while being honest about the inherent limitations of the format.*
