"""Regression checks for the factory's publishing handoff menu wiring."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "factory.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


class PublishingHandoffMenuIntegrationTests(unittest.TestCase):
    def test_factory_version_reflects_integrated_handoff(self):
        self.assertIn('FACTORY_VERSION = "112.0"', SOURCE)

    def test_main_menu_exposes_handoff_inventory(self):
        self.assertIn('print(" 32. Publishing Handoff Inventory', SOURCE)
        self.assertIn('elif c=="32": v112_publishing_handoff_menu()', SOURCE)

    def test_menu_uses_manifest_builder_and_no_clobber_writer(self):
        function = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                        and node.name == "v112_publishing_handoff_menu")
        calls = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
        self.assertIn("build_handoff_manifest", calls)
        self.assertIn("write_handoff_manifest_no_clobber", calls)

    def test_menu_reports_blockers_and_never_claims_upload(self):
        function = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                        and node.name == "v112_publishing_handoff_menu")
        source = ast.get_source_segment(SOURCE, function)
        self.assertIn('ACTION REQUIRED', source)
        self.assertIn('Read-only inventory', source)
        self.assertIn('uploaded', source.lower())

    def test_existing_completion_center_remains_available(self):
        self.assertIn('elif c=="31": v102_publishing_completion_menu()', SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
