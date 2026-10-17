"""Digital packages must generate a real cover preview for finished-PDF imports."""
import ast
from pathlib import Path
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class DigitalCoverPreviewFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
        cls.generator = next(
            node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "generate_platform_package_v112"
        )

    def test_generator_renders_cover_preview_from_master_when_profile_requires_it(self):
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), self.generator)
        self.assertIn('"cover_preview" in profile.get("files", [])', source)
        self.assertIn("_render_pdf_front_page(master, cover_render_dir)", source)
        self.assertIn("_extract_gumroad_front_cover_panel(rgb_image)", source)

    def test_rendered_preview_is_saved_as_package_asset_and_temp_files_are_removed(self):
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), self.generator)
        self.assertIn("COVER_PREVIEW.png", source)
        self.assertIn("generated.append(cover_preview_path)", source)
        self.assertIn("shutil.rmtree(cover_render_dir, ignore_errors=True)", source)

    def test_render_failure_blocks_instead_of_falsely_marking_preview_ready(self):
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), self.generator)
        self.assertIn("A required cover preview could not be rendered from MASTER page 1", source)
        self.assertIn("visually review it before uploading", source)


if __name__ == "__main__":
    unittest.main()
