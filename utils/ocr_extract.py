"""
Extracts text from a PDF. Tries native text extraction first (fast, accurate
for born-digital PDFs). If a page yields little/no text, falls back to
rasterizing the page and running Tesseract OCR on it (for scanned mocks).
"""
import re
import fitz  # PyMuPDF
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image, ImageOps
import io

MIN_CHARS_FOR_NATIVE = 40  # below this, assume the page is a scanned image
OCR_DPI = 400  # higher DPI meaningfully improves Tesseract accuracy on scanned exam pages

# --psm 6 = "assume a single uniform block of text", which suits a typical
# single-column exam page much better than Tesseract's default mode (which
# tries to detect complex multi-column layouts and can scramble line order).
# This is the fast/default path since most exam pages really are single-column.
PRIMARY_TESSERACT_CONFIG = "--psm 6"

# Fallback used only when the primary pass looks broken (see _looks_garbled
# below). --psm 3 lets Tesseract auto-detect the page layout instead of
# forcing it into one block, which fixes pages where a stray margin/column
# bled into the middle of a question under psm 6 -- at the cost of
# occasionally scrambling line order on genuinely single-column pages. Only
# retrying on pages that already look broken gets the benefit without paying
# that cost on every page.
FALLBACK_TESSERACT_CONFIG = "--psm 3"

# A real exam page almost always contains at least a couple of "A. ...",
# "B. ...", "C. ..." option lines. Seeing fewer than this on a page that
# needed OCR is a strong signal something (usually column bleed-through)
# went wrong with the primary pass.
MIN_CLEAN_OPTION_LINES = 2
_CLEAN_OPTION_LINE = re.compile(r"^[ \t]*[ABCabc][\.\)]\s+\S", re.MULTILINE)


def _option_line_count(text: str) -> int:
    return len(_CLEAN_OPTION_LINE.findall(text))


def _preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Light preprocessing that reliably improves OCR accuracy on scans:
    convert to grayscale and boost contrast so faint/uneven scans read cleaner."""
    gray = image.convert("L")
    return ImageOps.autocontrast(gray)


def _ocr_image(image: Image.Image) -> str:
    text = pytesseract.image_to_string(image, config=PRIMARY_TESSERACT_CONFIG)
    if _option_line_count(text) >= MIN_CLEAN_OPTION_LINES:
        return text
    alt_text = pytesseract.image_to_string(image, config=FALLBACK_TESSERACT_CONFIG)
    return alt_text if _option_line_count(alt_text) > _option_line_count(text) else text


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
        # Convert only the pages that need it, at a higher DPI for OCR accuracy
        images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI)
        for i in pages_needing_ocr:
            ocr_images[i] = images[i]

    total = len(doc)
    for i in range(total):
        if i in ocr_images:
            processed = _preprocess_for_ocr(ocr_images[i])
            text = _ocr_image(processed)
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

