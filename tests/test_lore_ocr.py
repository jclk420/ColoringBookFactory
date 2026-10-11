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
