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


def _extract_native_pdf_pages(path: Path) -> tuple[list[str], int | None, str | None]:
    """Return embedded text from all PDF pages, if available; OCR remains separately bounded."""
    Reader = None
    try:
        from pypdf import PdfReader as Reader
    except ImportError:
        try:
            from PyPDF2 import PdfReader as Reader
        except ImportError:
            return [], None, "Neither pypdf nor PyPDF2 is installed for embedded PDF text extraction."
    try:
        reader = Reader(str(path), strict=False)
        total_pages = len(reader.pages)
        texts = [
            str(page.extract_text() or "").strip()
            for page in reader.pages
        ]
        return texts, total_pages, None
    except Exception as exc:
        return [], None, f"Embedded PDF text extraction failed: {exc}"


def _render_pdf_pages_by_index(path: Path, page_indices: list[int], dpi: int) -> tuple[dict[int, Any], int]:
    """Render only PDF pages that need OCR; indices are zero-based."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ImportError(
            "PDF OCR needs optional package pypdfium2. Install it with: python -m pip install pypdfium2"
        ) from exc
    rendered: dict[int, Any] = {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        total_pages = len(pdf)
        scale = dpi / 72.0
        for index in page_indices:
            if index < 0 or index >= total_pages:
                continue
            page = pdf[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert("RGB")
            image.thumbnail((5000, 5000))
            rendered[index] = image.copy()
            bitmap.close()
            page.close()
    finally:
        pdf.close()
    return rendered, total_pages


def lore_ocr_extract_text(
    source_path: str | Path,
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    dpi: int = DEFAULT_DPI,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ocr_start_page: int = 1,
) -> dict[str, Any]:
    """Extract review-only text, preferring embedded PDF text and OCRing only gaps.

    Selectable PDF text does not require Tesseract or PDF rendering. OCR is used
    only for pages without substantial embedded text, keeping work bounded by
    page_limit and avoiding unnecessary OCR on text-based documents.
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
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        result["status"] = "ERROR"
        result["warnings"].append("Unsupported file type; use PDF or a supported image.")
        return result
    if not isinstance(page_limit, int) or isinstance(page_limit, bool) or not 1 <= page_limit <= MAX_PAGE_LIMIT:
        result["status"] = "ERROR"
        result["warnings"].append(f"page_limit must be an integer from 1 to {MAX_PAGE_LIMIT}.")
        return result
    if not isinstance(ocr_start_page, int) or isinstance(ocr_start_page, bool) or ocr_start_page < 1:
        result["status"] = "ERROR"
        result["warnings"].append("ocr_start_page must be a positive 1-based page number.")
        return result
    if suffix != ".pdf" and ocr_start_page != 1:
        result["status"] = "ERROR"
        result["warnings"].append("ocr_start_page can be changed only for PDF sources.")
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
    texts_by_page: dict[int, tuple[str, str]] = {}
    total_pages: int | None = None
    fallback_indices: list[int] = []

    if suffix == ".pdf":
        native_texts, total_pages, native_warning = _extract_native_pdf_pages(path)
        if native_warning:
            result["warnings"].append(native_warning)
        ocr_start_index = ocr_start_page - 1
        ocr_end_index = ocr_start_index + page_limit
        selected_count = (
            max(0, min(total_pages, ocr_end_index) - ocr_start_index)
            if total_pages is not None else page_limit
        )
        skipped_ocr_pages = 0
        for index, native_text in enumerate(native_texts):
            if len(native_text) >= 80:
                # Embedded text is cheap to extract, so keep it from every page;
                # only OCR fallback is restricted to the selected batch range.
                texts_by_page[index] = ("PDF TEXT", native_text)
            elif ocr_start_index <= index < ocr_end_index:
                fallback_indices.append(index)
            else:
                skipped_ocr_pages += 1
        if not native_texts:
            fallback_indices = list(range(ocr_start_index, ocr_start_index + selected_count))
        if fallback_indices and not tesseract:
            result["warnings"].append(
                f"Tesseract OCR was not found; {len(fallback_indices)} PDF page(s) without substantial embedded text could not be OCRed."
            )
        elif fallback_indices:
            try:
                rendered, rendered_total = _render_pdf_pages_by_index(path, fallback_indices, dpi)
                if total_pages is None:
                    total_pages = rendered_total
            except (ImportError, OSError, ValueError, RuntimeError) as exc:
                rendered = {}
                result["warnings"].append(str(exc))
            for index in fallback_indices:
                image = rendered.get(index)
                if image is None:
                    result["warnings"].append(f"Could not render PDF page {index + 1} for OCR.")
                    continue
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
                            f"OCR failed on page {index + 1}: "
                            + (completed.stderr.strip()[:300] or f"exit code {completed.returncode}")
                        )
                        continue
                    if completed.stdout.strip():
                        texts_by_page[index] = ("OCR", completed.stdout.strip())
                except subprocess.TimeoutExpired:
                    result["warnings"].append(f"OCR timed out on page {index + 1}.")
                except OSError as exc:
                    result["warnings"].append(f"OCR could not process page {index + 1}: {exc}")
        if any(label == "OCR" for label, _ in texts_by_page.values()):
            result["method"] = "pdf_text_with_tesseract_fallback" if any(label == "PDF TEXT" for label, _ in texts_by_page.values()) else "tesseract_ocr"
        elif any(label == "PDF TEXT" for label, _ in texts_by_page.values()):
            result["method"] = "pdf_text"
        if skipped_ocr_pages:
            batch_end_page = (
                min(total_pages, ocr_start_page + page_limit - 1)
                if total_pages is not None else ocr_start_page + page_limit - 1
            )
            result["warnings"].append(
                f"OCR batch pages {ocr_start_page}-{batch_end_page}: {skipped_ocr_pages} page(s) outside "
                "this batch had insufficient embedded text and were not OCRed. Run another batch to cover them."
            )
    else:
        if not tesseract:
            result["status"] = "UNAVAILABLE"
            result["warnings"].append(
                "Tesseract OCR was not found. Install Tesseract and ensure its executable is on PATH."
            )
            return result
        try:
            page_images = _load_image_pages(path)
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            result["status"] = "UNAVAILABLE" if isinstance(exc, ImportError) else "ERROR"
            result["warnings"].append(str(exc))
            return result
        for index, image in enumerate(page_images[:page_limit]):
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
                        f"OCR failed on page {index + 1}: "
                        + (completed.stderr.strip()[:300] or f"exit code {completed.returncode}")
                    )
                    continue
                if completed.stdout.strip():
                    texts_by_page[index] = ("OCR", completed.stdout.strip())
            except subprocess.TimeoutExpired:
                result["warnings"].append(f"OCR timed out on page {index + 1}.")
            except OSError as exc:
                result["warnings"].append(f"OCR could not process page {index + 1}: {exc}")
        result["method"] = "tesseract_ocr"

    result["text"] = "\n\n".join(
        f"[{label} PAGE {index + 1}]\n{text}"
        for index, (label, text) in sorted(texts_by_page.items())
    )
    result["pages_processed"] = len(texts_by_page)
    if not result["text"]:
        if not tesseract and suffix == ".pdf":
            result["status"] = "UNAVAILABLE"
        result["warnings"].append(
            "No readable text was recognized. Check scan quality, language, and page orientation."
        )
        if result["status"] == "UNAVAILABLE":
            return result
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
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGE_LIMIT, help="Maximum PDF pages eligible for OCR fallback per batch (1-25); embedded text is extracted from all pages")
    parser.add_argument("--ocr-start", type=int, default=1, help="First 1-based PDF page eligible for OCR fallback; use with --pages to process later batches")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="PDF render DPI (72-220)")
    parser.add_argument("--output", help="Optional text output path; defaults to stdout JSON")
    args = parser.parse_args(argv)
    result = lore_ocr_extract_text(
        args.source, page_limit=args.pages, dpi=args.dpi, ocr_start_page=args.ocr_start
    )
    if args.output:
        output_path = Path(args.output)
        import re
        output_path = Path(args.output)
        page_blocks = re.finditer(
            r"(?ms)^\[(?:PDF TEXT|OCR) PAGE (\d+)\]\n.*?(?=^\[(?:PDF TEXT|OCR) PAGE \d+\]\n|\Z)",
            result["text"],
        )
        batch_text = "\n\n".join(
            match.group(0).rstrip()
            for match in page_blocks
            if args.ocr_start <= int(match.group(1)) < args.ocr_start + args.pages
        )
        output_path.write_text(batch_text, encoding="utf-8")
        summary = {key: value for key, value in result.items() if key != "text"}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
