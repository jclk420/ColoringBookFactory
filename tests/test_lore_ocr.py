"""Dependency-free tests for conservative OCR preflight behavior."""
import pathlib
import tempfile
import unittest
from unittest import mock

import lore_ocr


class LoreOCRTests(unittest.TestCase):
    def test_missing_file_is_reported_without_crashing(self):
        result = lore_ocr.lore_ocr_extract_text("missing-file.pdf")
        self.assertEqual(result["status"], "ERROR")
        self.assertTrue(result["warnings"])

    def test_unsupported_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.docx"
            source.write_text("not an OCR source", encoding="utf-8")
            result = lore_ocr.lore_ocr_extract_text(source)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Unsupported file type", result["warnings"][0])

    def test_page_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.png"
            source.write_bytes(b"image placeholder")
            result = lore_ocr.lore_ocr_extract_text(source, page_limit=999)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("page_limit", result["warnings"][0])

    def test_dpi_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.png"
            source.write_bytes(b"image placeholder")
            result = lore_ocr.lore_ocr_extract_text(source, dpi=999)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("dpi", result["warnings"][0])

    def test_missing_tesseract_is_a_safe_unavailable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.png"
            source.write_bytes(b"image placeholder")
            with mock.patch.object(lore_ocr.shutil, "which", return_value=None):
                result = lore_ocr.lore_ocr_extract_text(source)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["text"], "")

    def test_embedded_pdf_text_works_without_tesseract(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "selectable.pdf"
            source.write_bytes(b"PDF placeholder")
            embedded = "EL SILBON\n" + ("The Whistling One and archive metadata. " * 8)
            with mock.patch.object(
                lore_ocr, "_extract_native_pdf_pages",
                return_value=([embedded], 1, None),
            ), mock.patch.object(lore_ocr.shutil, "which", return_value=None), mock.patch.object(
                lore_ocr, "_render_pdf_pages_by_index"
            ) as render:
                result = lore_ocr.lore_ocr_extract_text(source)
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["method"], "pdf_text")
        self.assertEqual(result["pages_processed"], 1)
        self.assertIn("EL SILBON", result["text"])
        self.assertFalse(render.called)
        self.assertFalse(any("Tesseract OCR was not found" in warning for warning in result["warnings"]))
        self.assertFalse(result["canon_write"])
        self.assertFalse(result["auto_approval"])

    def test_pdf_ocr_fallback_runs_only_for_pages_without_embedded_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "mixed.pdf"
            source.write_bytes(b"PDF placeholder")
            embedded = "EL SILBON\n" + ("Selectable archive text. " * 8)
            rendered_page = mock.Mock()
            completed = __import__("subprocess").CompletedProcess(
                args=["tesseract"], returncode=0, stdout="OCR fallback page", stderr=""
            )
            with mock.patch.object(
                lore_ocr, "_extract_native_pdf_pages",
                return_value=([embedded, "too short"], 2, None),
            ), mock.patch.object(
                lore_ocr.shutil, "which", return_value="tesseract"
            ), mock.patch.object(
                lore_ocr, "_render_pdf_pages_by_index",
                return_value=({1: rendered_page}, 2),
            ) as render, mock.patch.object(
                lore_ocr.subprocess, "run", return_value=completed
            ) as run:
                result = lore_ocr.lore_ocr_extract_text(source)
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["method"], "pdf_text_with_tesseract_fallback")
        self.assertIn("[PDF TEXT PAGE 1]", result["text"])
        self.assertIn("[OCR PAGE 2]", result["text"])
        self.assertEqual(render.call_args.args[1], [1])
        self.assertEqual(run.call_count, 1)

    def test_capabilities_are_read_only_and_well_shaped(self):
        result = lore_ocr.lore_ocr_capabilities()
        self.assertIn("tesseract", result)
        self.assertIn("pdfium_available", result)
        self.assertIn("pillow_available", result)

    def test_invalid_boolean_page_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.png"
            source.write_bytes(b"image placeholder")
            result = lore_ocr.lore_ocr_extract_text(source, page_limit=True)
        self.assertEqual(result["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
