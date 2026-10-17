"""MASTER PDF discovery must not follow symbolic links."""
import ast
from pathlib import Path
import tempfile
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_functions(names, namespace):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in set(names)
    ]
    found = {node.name for node in selected}
    if found != set(names):
        raise AssertionError(f"Expected functions {set(names)}, found {found}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class MasterPdfSymlinkSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "Book"
        self.project.mkdir()
        self.master_dir = self.project / "MASTER"
        self.master_dir.mkdir()

    def make_symlink(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=False)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic links are unavailable in this environment: {error}")

    def test_master_symlink_blocks_fallback_to_another_pdf(self):
        outside = self.base / "outside.pdf"
        outside.write_bytes(b"outside PDF bytes")
        link = self.master_dir / "Book_MASTER.pdf"
        self.make_symlink(outside, link)
        pdf_dir = self.project / "PDF"
        pdf_dir.mkdir()
        (pdf_dir / "Book.pdf").write_bytes(b"fallback PDF bytes")

        namespace = load_functions(
            {"_unsafe_master_pdf_symlink", "find_master_pdf"},
            {
                "Path": Path,
                "load_project_settings_safe": lambda _project: {"title": "Book"},
                "kdp_safe_filename": lambda value: str(value),
            },
        )
        self.assertEqual(namespace["_unsafe_master_pdf_symlink"](self.project), link)
        self.assertIsNone(namespace["find_master_pdf"](self.project))

    def test_existing_book_search_ignores_symlinked_pdf(self):
        outside = self.base / "outside.pdf"
        outside.write_bytes(b"outside PDF bytes")
        pdf_dir = self.project / "PDF"
        pdf_dir.mkdir()
        self.make_symlink(outside, pdf_dir / "linked.pdf")

        namespace = load_functions(
            {"find_existing_book_pdf"},
            {"Path": Path, "PLATFORM_DIRNAME": "PLATFORMS"},
        )
        self.assertIsNone(namespace["find_existing_book_pdf"](self.project))

    def test_symlinked_master_directory_is_rejected(self):
        outside_dir = self.base / "outside_master"
        outside_dir.mkdir()
        (outside_dir / "Book_MASTER.pdf").write_bytes(b"outside MASTER bytes")
        self.master_dir.rmdir()
        try:
            self.master_dir.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Directory symbolic links are unavailable: {error}")

        namespace = load_functions(
            {"_unsafe_master_pdf_symlink", "find_master_pdf"},
            {
                "Path": Path,
                "load_project_settings_safe": lambda _project: {"title": "Book"},
                "kdp_safe_filename": lambda value: str(value),
            },
        )
        self.assertEqual(namespace["_unsafe_master_pdf_symlink"](self.project), self.master_dir)
        self.assertIsNone(namespace["find_master_pdf"](self.project))

    def test_master_repair_checks_symlink_before_creating_or_copying_master(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        ensure = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "ensure_master_book"
        )
        body = ast.get_source_segment(source, ensure)
        self.assertIsNotNone(body)
        self.assertLess(
            body.index("_unsafe_master_pdf_symlink(project)"),
            body.index("platform_master_dir(project)"),
        )
        self.assertIn("MASTER PDF is a symbolic link", body)


if __name__ == "__main__":
    unittest.main()
