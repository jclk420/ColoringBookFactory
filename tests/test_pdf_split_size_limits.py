"""Regression tests for platform PDF size splitting."""
import ast
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class FakeReader:
    page_sizes = []

    def __init__(self, _path, strict=False):
        self.pages = list(type(self).page_sizes)


class FakeWriter:
    def __init__(self):
        self.pages = []

    def add_page(self, page):
        self.pages.append(page)

    def write(self, handle):
        handle.write(b"x" * sum(self.pages))


def load_splitter(page_sizes):
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_pdf_split_by_size"
    ]
    if len(matches) != 1:
        raise AssertionError("_pdf_split_by_size must have exactly one definition")
    FakeReader.page_sizes = list(page_sizes)
    namespace = {
        "Path": Path,
        "_pdf_reader_class": lambda: FakeReader,
        "_platform_sanitized_filename": lambda name, max_chars=70: str(name)[:max_chars],
    }
    exec(compile(ast.Module(body=matches, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["_pdf_split_by_size"]


class PdfSplitSizeLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source.pdf"
        self.source.write_bytes(b"test source")
        self.output = self.base / "parts"
        self.output.mkdir()
        module = types.ModuleType("pypdf")
        module.PdfWriter = FakeWriter
        self.modules = patch.dict(sys.modules, {"pypdf": module})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_oversized_single_page_is_rejected(self):
        split = load_splitter([100])
        parts, errors = split(self.source, self.output, "Book", 0.00001, 5)
        self.assertEqual(parts, [])
        self.assertTrue(any("A single page exceeds" in error for error in errors))
        self.assertEqual(list(self.output.glob("*.pdf")), [])

    def test_pages_that_fit_are_written_as_compliant_parts(self):
        split = load_splitter([6, 6])
        parts, errors = split(self.source, self.output, "Book", 0.00001, 5)
        self.assertEqual(errors, [])
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(part.stat().st_size <= 10 for part in parts))


if __name__ == "__main__":
    unittest.main()
