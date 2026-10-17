"""Finished-PDF platform packaging must not silently omit its required KDP wrap cover."""
import ast
from pathlib import Path
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class KdpAutoCoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
        cls.functions = {
            node.name: node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def test_cover_builder_supports_staging_and_explicit_artwork(self):
        function = self.functions["create_kdp_cover"]
        args = [arg.arg for arg in function.args.args]
        self.assertIn("output_folder", args)
        self.assertIn("artwork_override", args)
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), function)
        self.assertIn("Path(output_folder)", source)
        self.assertIn("images = [override_path]", source)

    def test_platform_generator_builds_missing_kdp_cover_only_in_staging(self):
        function = self.functions["generate_platform_package_v112"]
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "create_kdp_cover"
        ]
        self.assertTrue(calls, "KDP platform packaging must be able to create the required cover PDF")
        call = calls[0]
        keywords = {item.arg: item.value for item in call.keywords}
        self.assertIn("output_folder", keywords)
        self.assertIsInstance(keywords["output_folder"], ast.Name)
        self.assertEqual(keywords["output_folder"].id, "staging")
        self.assertIn("artwork_override", keywords)

    def test_auto_cover_requires_author_and_warns_visual_review(self):
        function = self.functions["generate_platform_package_v112"]
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), function)
        self.assertIn("until an author/pen name is set", source)
        self.assertIn("Visually review the cover PDF before uploading", source)

    def test_kdp_cover_preflight_checks_supplied_and_generated_cover_pdfs(self):
        function = self.functions["generate_platform_package_v112"]
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "kdp_cover_preflight"
        ]
        self.assertTrue(calls, "KDP wrap cover geometry must be checked before publication")
        source = ast.get_source_segment(FACTORY_PATH.read_text(encoding="utf-8"), function)
        self.assertIn("KDP cover PDF failed print-geometry preflight", source)


if __name__ == "__main__":
    unittest.main()
