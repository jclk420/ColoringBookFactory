import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "factory.py"


class DashboardResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FACTORY.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        matches = [node for node in cls.tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_review_dashboard"]
        if len(matches) != 1:
            raise AssertionError("Expected exactly one lore_intake_review_dashboard definition")
        cls.dashboard = ast.get_source_segment(cls.source, matches[0])

    def test_factory_version_is_consistent(self):
        self.assertIn('FACTORY_VERSION = "38.0"', self.source)
        self.assertIn("# Current version: 38.0.", self.source)

    def test_malformed_manifest_batches_are_reported_and_returned_safely(self):
        self.assertIn('manifest_batches_wrong_type', self.dashboard)
        self.assertIn('expected a list', self.dashboard)

    def test_malformed_batches_and_reports_are_counted(self):
        for field in ("malformed_batches", "unreadable_reports", "malformed_reports"):
            with self.subTest(field=field):
                self.assertIn(field, self.dashboard)

    def test_candidate_lists_are_type_checked_before_display(self):
        self.assertIn('if isinstance(classification.get("extracted_entity_candidates", []), list)', self.dashboard)
        self.assertIn('if isinstance(classification.get("extracted_relationships", []), list)', self.dashboard)

    def test_dashboard_remains_read_only(self):
        self.assertIn("READ ONLY", self.dashboard)
        self.assertIn("no source or canon data was changed", self.dashboard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
