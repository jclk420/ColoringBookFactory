# Optional Lore OCR (v27.3)

This helper is an opt-in OCR utility for scanned/image-only PDFs and common image files. It is deliberately **review-only**: output is low-confidence text, not approved lore. It does not change the input file, approve intake items, or write to a World Bible or Series Bible.

## Requirements

- Python and Pillow, already used by Coloring Book Factory.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on Windows and available as `tesseract.exe` on `PATH`.
- For PDFs only: `python -m pip install pypdfium2`.

The helper does not install software or download language data. If Tesseract is missing, it reports `UNAVAILABLE` rather than failing silently.

## Try it

From the repository folder:

```powershell
python lore_ocr.py "C:\path\to\scanned.pdf" --pages 10 --dpi 150
```

The default prints a JSON report including recognized text and warnings. To save only recognized text to a file:

```powershell
python lore_ocr.py "C:\path\to\scanned.pdf" --output "$env:TEMP\lore-ocr-review.txt"
```

Supported inputs: PDF, PNG, JPG/JPEG, TIFF, BMP, and WebP. Defaults process at most 10 PDF pages at 150 DPI. The page limit is capped at 25 and DPI at 220 to keep work bounded. Recognition failures and skipped pages are reported.

## Safety / current scope

- OCR text is not automatically attached to the intake dashboard in this release; this PR provides a tested extraction utility as groundwork for that integration.
- Pass recognized text to the existing labeled-entity extractor only after reviewing the source and OCR quality.
- OCR output remains low-confidence and must not be treated as canon.
- OCR may confuse similar characters, miss text, or misread rotated/low-resolution pages.
- Scanned PDFs can be large; test with a small page limit first.
