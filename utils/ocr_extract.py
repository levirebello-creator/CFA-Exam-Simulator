"""
Extracts text from a PDF. Tries native text extraction first (fast, accurate
for born-digital PDFs). If a page yields little/no text, falls back to
rasterizing the page and running Tesseract OCR on it (for scanned mocks).
"""
import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import io

MIN_CHARS_FOR_NATIVE = 40  # below this, assume the page is a scanned image


def extract_pages_text(pdf_bytes: bytes, progress_callback=None):
    """
    Returns a list of strings, one per page, and a bool list indicating
    whether OCR was used for that page (useful for showing the user
    which pages might need extra scrutiny).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts = []
    ocr_used = []

    # First pass: try native extraction on every page
    native_texts = []
    pages_needing_ocr = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        native_texts.append(text)
        if len(text.strip()) < MIN_CHARS_FOR_NATIVE:
            pages_needing_ocr.append(i)

    ocr_images = {}
    if pages_needing_ocr:
        # Convert only the pages that need it, at a decent DPI for OCR accuracy
        images = convert_from_bytes(pdf_bytes, dpi=300)
        for i in pages_needing_ocr:
            ocr_images[i] = images[i]

    total = len(doc)
    for i in range(total):
        if i in ocr_images:
            text = pytesseract.image_to_string(ocr_images[i])
            page_texts.append(text)
            ocr_used.append(True)
        else:
            page_texts.append(native_texts[i])
            ocr_used.append(False)
        if progress_callback:
            progress_callback((i + 1) / total)

    doc.close()
    return page_texts, ocr_used


def full_text(pdf_bytes: bytes, progress_callback=None):
    pages, ocr_flags = extract_pages_text(pdf_bytes, progress_callback)
    return "\n\n".join(pages), any(ocr_flags)
