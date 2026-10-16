"""Regression tests for safe finished-PDF intake preflight."""
import ast
import tempfile
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_validator(inspect_pdf):
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"))
    node = next((item for item in tree.body
                 if isinstance(item, ast.FunctionDef) and item.name == "validate_finished_pdf_source"), None)
    if node is None:
        raise AssertionError("validate_finished_pdf_source is missing")
    namespace = {"Path": Path, "inspect_pdf": inspect_pdf}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["validate_finished_pdf_source"]


class FinishedPdfIntakeTests(unittest.TestCase):
    def test_rejects_missing_wrong_extension_empty_and_unreadable_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inspect = lambda path: {"page_count": 1, "error": None, "encrypted": False}
            validate = load_validator(inspect)
            self.assertEqual(validate(root / "missing.pdf")["status"], "BLOCKED")
            wrong = root / "book.txt"
            wrong.write_text("not a PDF", encoding="utf-8")
            self.assertTrue(any("extension" in error for error in validate(wrong)["errors"]))
            empty = root / "empty.pdf"
            empty.touch()
            self.assertTrue(any("empty" in error for error in validate(empty)["errors"]))
            unreadable = root / "broken.pdf"
            unreadable.write_bytes(b"%PDF-broken")
            validate_broken = load_validator(lambda path: {"page_count": 0, "error": "malformed PDF", "encrypted": False})
            result = validate_broken(unreadable)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("inspection failed" in error for error in result["errors"]))
            self.assertTrue(any("readable pages" in error for error in result["errors"]))

    def test_accepts_readable_pdf_and_reports_page_count(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.pdf"
            path.write_bytes(b"%PDF-1.4 test")
            validate = load_validator(lambda p: {"page_count": 64, "error": None, "encrypted": False})
            result = validate(path)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["page_count"], 64)
            self.assertEqual(result["file_size_bytes"], len(b"%PDF-1.4 test"))
            encrypted_validate = load_validator(
                lambda p: {"page_count": 64, "error": None, "encrypted": True}
            )
            encrypted_result = encrypted_validate(path)
            self.assertEqual(encrypted_result["status"], "BLOCKED")
            self.assertTrue(any("Encrypted PDFs" in error for error in encrypted_result["errors"]))

    def test_rejects_symlink_source_without_inspecting_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "original.pdf"
            target.write_bytes(b"%PDF-1.4 test")
            link = root / "linked.pdf"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable in this environment: {error}")
            calls = []
            validate = load_validator(lambda path: calls.append(path) or {"page_count": 1, "error": None, "encrypted": False})
            result = validate(link)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("symbolic-link" in error for error in result["errors"]))
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
