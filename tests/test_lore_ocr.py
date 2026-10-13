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

    def test_all_embedded_pdf_pages_are_processed_beyond_ocr_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "long-selectable.pdf"
            source.write_bytes(b"PDF placeholder")
            pages = [
                f"CREATURE PAGE {number}\n" + ("Selectable archive text. " * 8)
                for number in range(1, 41)
            ]
            with mock.patch.object(
                lore_ocr, "_extract_native_pdf_pages",
                return_value=(pages, 40, None),
            ), mock.patch.object(
                lore_ocr.shutil, "which", return_value=None
            ), mock.patch.object(lore_ocr, "_render_pdf_pages_by_index") as render:
                result = lore_ocr.lore_ocr_extract_text(source, page_limit=10)
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["pages_processed"], 40)
        self.assertIn("[PDF TEXT PAGE 40]", result["text"])
        self.assertFalse(render.called)
        self.assertFalse(any("page limit reached" in warning.lower() for warning in result["warnings"]))

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

    def test_ocr_start_page_selects_a_later_batch_without_limiting_native_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "long-mixed.pdf"
            source.write_bytes(b"PDF placeholder")
            pages = [
                f"CREATURE PAGE {number} " + ("Selectable archive text. " * 8)
                for number in range(1, 61)
            ]
            pages[29] = "short page 30"
            pages[54] = "short page 55"
            rendered_page = mock.Mock()
            completed = __import__("subprocess").CompletedProcess(
                args=["tesseract"], returncode=0, stdout="OCR fallback page 30", stderr=""
            )
            with mock.patch.object(
                lore_ocr, "_extract_native_pdf_pages",
                return_value=(pages, 60, None),
            ), mock.patch.object(
                lore_ocr.shutil, "which", return_value="tesseract"
            ), mock.patch.object(
                lore_ocr, "_render_pdf_pages_by_index",
                return_value=({29: rendered_page}, 60),
            ) as render, mock.patch.object(
                lore_ocr.subprocess, "run", return_value=completed
            ) as run:
                result = lore_ocr.lore_ocr_extract_text(
                    source, page_limit=25, ocr_start_page=26
                )
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["pages_processed"], 59)
        self.assertIn("[PDF TEXT PAGE 60]", result["text"])
        self.assertIn("[OCR PAGE 30]", result["text"])
        self.assertNotIn("[PDF TEXT PAGE 55]", result["text"])
        self.assertEqual(render.call_args.args[1], [29])
        self.assertEqual(run.call_count, 1)
        self.assertTrue(any("outside this batch" in warning for warning in result["warnings"]))
        self.assertFalse(result["canon_write"])
        self.assertFalse(result["auto_approval"])

    def test_ocr_start_page_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "input.pdf"
            source.write_bytes(b"PDF placeholder")
            result = lore_ocr.lore_ocr_extract_text(source, ocr_start_page=0)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("ocr_start_page", result["warnings"][0])

    def test_page_range_selects_only_requested_labeled_pages(self):
        text = (
            "[PDF TEXT PAGE 1]\nfirst page\n\n"
            "[OCR PAGE 2]\nsecond page\n\n"
            "[PDF TEXT PAGE 3]\nthird page\n\n"
            "[OCR PAGE 4]\nfourth page"
        )
        self.assertEqual(
            lore_ocr.lore_ocr_select_page_range(text, 2, 2),
            "[OCR PAGE 2]\nsecond page\n\n[PDF TEXT PAGE 3]\nthird page",
        )

    def test_page_range_returns_empty_when_range_has_no_blocks(self):
        text = "[PDF TEXT PAGE 1]\nfirst page\n\n[PDF TEXT PAGE 2]\nsecond page"
        self.assertEqual(lore_ocr.lore_ocr_select_page_range(text, 3, 2), "")

    def test_page_range_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            lore_ocr.lore_ocr_select_page_range("[OCR PAGE 1]\ntext", 0, 10)
        with self.assertRaises(ValueError):
            lore_ocr.lore_ocr_select_page_range("[OCR PAGE 1]\ntext", 1, 26)

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
