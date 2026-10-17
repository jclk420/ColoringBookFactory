"""Finished-PDF imports must generate preview sheets from actual book pages."""
import ast
from pathlib import Path
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class PreviewSheetFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
        cls.function = next(
            node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_preview_sheet"
        )

    def test_preview_sheet_renders_master_pages_when_artwork_is_missing(self):
        calls = [
            node.func.id for node in ast.walk(self.function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("_render_pdf_pages_universal", calls)
        self.assertIn("_choose_gumroad_candidates", calls)

    def test_preview_render_staging_is_cleaned_up(self):
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), self.function)
        self.assertIn(".__preview_render", source)
        self.assertIn("shutil.rmtree(render_dir, ignore_errors=True)", source)

    def test_no_title_only_placeholder_can_be_published_as_preview(self):
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), self.function)
        self.assertNotIn("Digital Preview", source)
        self.assertIn("Could not create a meaningful preview sheet", source)


if __name__ == "__main__":
    unittest.main()
