"""Regression test for restoring a missing MASTER from its recorded original PDF."""
import ast
import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


class MissingMasterRecoveryTests(unittest.TestCase):
    def test_missing_master_recovers_only_recorded_source_and_preserves_64_pages(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "ensure_master_book"]
        self.assertEqual(len(matches), 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "Project"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            original = root / "NightmareUnicornsFinished.pdf"
            original.write_bytes(b"%PDF-1.7\noriginal 64-page PDF fixture\n%%EOF")
            (master_dir / "master_metadata.json").write_text(json.dumps({
                "page_count": 64, "source_pdf": str(original),
                "source_sha256": "fixture-hash"
            }), encoding="utf-8")
            namespace = {
                "Path": pathlib.Path,
                "load_project_settings_safe": lambda _p: {
                    "title": "Nightmare Unicorns", "author": "JAC",
                    "trim_width": 8.5, "trim_height": 11, "dpi": 300
                },
                "platform_master_dir": lambda _p: master_dir,
                "find_master_pdf": lambda _p: None,
                "find_existing_book_pdf": lambda _p: None,
                "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")),
                "kdp_safe_filename": lambda value: value.replace(" ", ""),
                "inspect_pdf": lambda _p: {"exists": True, "page_count": 64, "file_size_mb": 40.77},
                "pdf_page_count": lambda _p: 64,
                "file_hash": lambda _p: "fixture-hash",
                "save_json": lambda p, value: pathlib.Path(p).write_text(
                    json.dumps(value), encoding="utf-8"
                ),
                "shutil": shutil,
                "datetime": datetime,
                "FACTORY_VERSION": "137.0",
                "PLATFORM_ENGINE_VERSION": "4.3",
            }
            function = matches[0]
            exec(compile(ast.Module(body=[function], type_ignores=[]),
                         str(FACTORY_PATH), "exec"), namespace)
            recovered, errors, warnings = namespace["ensure_master_book"](project)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])
            self.assertIsNotNone(recovered)
            self.assertTrue(recovered.is_file())
            self.assertEqual(recovered.read_bytes(), original.read_bytes())
            metadata = json.loads((master_dir / "master_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["page_count"], 64)
            self.assertEqual(metadata["source_pdf"], str(original))

    def test_missing_recorded_source_does_not_choose_an_arbitrary_pdf(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "ensure_master_book")
        with tempfile.TemporaryDirectory() as temporary:
            project = pathlib.Path(temporary) / "Project"
            master_dir = project / "MASTER"
            master_dir.mkdir(parents=True)
            (master_dir / "master_metadata.json").write_text(json.dumps({
                "page_count": 64, "source_pdf": str(project / "missing-original.pdf")
            }), encoding="utf-8")
            namespace = {
                "Path": pathlib.Path,
                "load_project_settings_safe": lambda _p: {"title": "Book"},
                "platform_master_dir": lambda _p: master_dir,
                "find_master_pdf": lambda _p: None,
                "find_existing_book_pdf": lambda _p: None,
                "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")),
                "kdp_safe_filename": lambda value: value,
                "inspect_pdf": lambda _p: {"exists": True, "page_count": 64},
                "pdf_page_count": lambda _p: 64,
                "shutil": shutil,
                "datetime": datetime,
                "FACTORY_VERSION": "137.0",
                "PLATFORM_ENGINE_VERSION": "4.3",
            }
            exec(compile(ast.Module(body=[function], type_ignores=[]),
                         str(FACTORY_PATH), "exec"), namespace)
            recovered, errors, _warnings = namespace["ensure_master_book"](project)
            self.assertIsNone(recovered)
            self.assertTrue(errors)
            self.assertFalse(list(master_dir.glob("*_MASTER.pdf")))


if __name__ == "__main__":
    unittest.main()
