"""Optional, conservative OCR helpers for lore-intake review.

OCR is opt-in and produces text candidates only. It never edits source files,
approves intake records, or writes to a Series Bible. Requires Tesseract OCR;
PDF support additionally requires pypdfium2. All dependencies are optional.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_SUFFIXES = SUPPORTED_IMAGE_SUFFIXES | {".pdf"}
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 25
DEFAULT_DPI = 150
MAX_DPI = 220
DEFAULT_TIMEOUT_SECONDS = 45


def lore_ocr_capabilities() -> dict[str, Any]:
    """Report optional OCR components without installing or changing anything."""
    return {
        "tesseract": shutil.which("tesseract"),
        "pdfium_available": _module_available("pypdfium2"),
        "pillow_available": _module_available("PIL"),
    }


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def lore_ocr_extract_text(
    source_path: str | Path,
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    dpi: int = DEFAULT_DPI,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """OCR a PDF or image and return review-only text with explicit warnings.

    The caller should pass the returned text to the existing conservative
    entity extractor. A page limit prevents unbounded work on large PDFs.
    """
    path = Path(source_path)
    result: dict[str, Any] = {
        "source": str(path),
        "status": "REVIEW",
        "text": "",
        "pages_processed": 0,
        "warnings": [],
        "method": "tesseract_ocr",
    }

    if not path.is_file():
        result["status"] = "ERROR"
        result["warnings"].append("Source file does not exist or is not a file.")
        return result
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        result["status"] = "ERROR"
        result["warnings"].append("Unsupported file type; use PDF or a supported image.")
        return result
    if not isinstance(page_limit, int) or isinstance(page_limit, bool) or not 1 <= page_limit <= MAX_PAGE_LIMIT:
        result["status"] = "ERROR"
        result["warnings"].append(f"page_limit must be an integer from 1 to {MAX_PAGE_LIMIT}.")
        return result
    if not isinstance(dpi, int) or isinstance(dpi, bool) or not 72 <= dpi <= MAX_DPI:
        result["status"] = "ERROR"
        result["warnings"].append(f"dpi must be an integer from 72 to {MAX_DPI}.")
        return result
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 180:
        result["status"] = "ERROR"
        result["warnings"].append("timeout_seconds must be an integer from 1 to 180.")
        return result

    tesseract = shutil.which("tesseract")
    if not tesseract:
        result["status"] = "UNAVAILABLE"
        result["warnings"].append(
            "Tesseract OCR was not found. Install Tesseract and ensure its executable is on PATH."
        )
        return result

    try:
        if path.suffix.lower() == ".pdf":
            page_images = _render_pdf_pages(path, page_limit=page_limit, dpi=dpi)
        else:
            page_images = _load_image_pages(path)
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        result["status"] = "UNAVAILABLE" if isinstance(exc, ImportError) else "ERROR"
        result["warnings"].append(str(exc))
        return result

    texts: list[str] = []
    for page_number, image in enumerate(page_images, start=1):
        try:
            with tempfile.TemporaryDirectory(prefix="cbf_lore_ocr_") as tmp:
                image_path = Path(tmp) / "page.png"
                image.save(image_path, format="PNG")
                completed = subprocess.run(
                    [tesseract, str(image_path), "stdout", "--psm", "6"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    shell=False,
                )
            if completed.returncode != 0:
                result["warnings"].append(
                    f"OCR failed on page {page_number}: "
                    + (completed.stderr.strip()[:300] or f"exit code {completed.returncode}")
                )
                continue
            text = completed.stdout.strip()
            if text:
                texts.append(f"[OCR PAGE {page_number}]\n{text}")
            result["pages_processed"] += 1
        except subprocess.TimeoutExpired:
            result["warnings"].append(f"OCR timed out on page {page_number}.")
        except OSError as exc:
            result["warnings"].append(f"OCR could not process page {page_number}: {exc}")

    result["text"] = "\n\n".join(texts)
    if path.suffix.lower() == ".pdf":
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path))
            total_pages = len(pdf)
            pdf.close()
            if total_pages > len(page_images):
                result["warnings"].append(
                    f"Page limit reached: processed {len(page_images)} of {total_pages} PDF pages."
                )
        except Exception:
            pass
    if not result["text"]:
        result["warnings"].append(
            "No readable text was recognized. Check scan quality, language, and page orientation."
        )
    result["status"] = "REVIEW"
    result["confidence"] = "LOW"
    result["canon_write"] = False
    result["auto_approval"] = False
    return result


def _load_image_pages(path: Path) -> list[Any]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ImportError("Pillow is required for OCR image preparation.") from exc
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((5000, 5000))
        return [image.copy()]


def _render_pdf_pages(path: Path, *, page_limit: int, dpi: int) -> list[Any]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ImportError(
            "PDF OCR needs optional package pypdfium2. Install it with: python -m pip install pypdfium2"
        ) from exc
    pages: list[Any] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        scale = dpi / 72.0
        for index in range(min(len(pdf), page_limit)):
            page = pdf[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert("RGB")
            image.thumbnail((5000, 5000))
            pages.append(image.copy())
            bitmap.close()
            page.close()
    finally:
        pdf.close()
    if not pages:
        raise ValueError("The PDF contains no pages to OCR.")
    return pages


def main(argv: list[str] | None = None) -> int:
    """Small standalone entry point for testing OCR before factory integration."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Extract low-confidence OCR text for lore review.")
    parser.add_argument("source", help="PDF or image file to OCR")
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGE_LIMIT, help="Maximum PDF pages (1-25)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="PDF render DPI (72-220)")
    parser.add_argument("--output", help="Optional text output path; defaults to stdout JSON")
    args = parser.parse_args(argv)
    result = lore_ocr_extract_text(args.source, page_limit=args.pages, dpi=args.dpi)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(result["text"], encoding="utf-8")
        summary = {key: value for key, value in result.items() if key != "text"}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
