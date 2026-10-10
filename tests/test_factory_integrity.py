"""Fast, dependency-free integrity tests for the Coloring Book Factory source."""
import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


class FactoryIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FACTORY_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(FACTORY_PATH))
        cls.functions = {}
        for node in ast.walk(cls.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cls.functions.setdefault(node.name, []).append(node)

    def test_factory_compiles_and_has_version(self):
        compile(self.source, str(FACTORY_PATH), "exec")
        match = re.search(r'^FACTORY_VERSION\s*=\s*["\']([^"\']+)["\']', self.source, re.M)
        self.assertIsNotNone(match, "FACTORY_VERSION must be declared")
        self.assertRegex(match.group(1), r"^\d+\.\d+$")

    def test_critical_functions_are_defined_exactly_once(self):
        critical = (
            "lore_analyze_series",
            "lore_repair_series",
            "lore_manual_select_projects",
            "lore_sync_explicit_series_attachments",
            "lore_register_book",
        )
        for name in critical:
            with self.subTest(function=name):
                self.assertEqual(
                    len(self.functions.get(name, [])), 1,
                    f"{name} must have exactly one definition",
                )

    def test_analysis_does_not_trigger_metadata_sync(self):
        node = self.functions["lore_analyze_series"][0]
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertNotIn(
            "lore_sync_explicit_series_attachments", calls,
            "Analysis must not silently modify project or Series Bible metadata",
        )

    def test_repair_has_explicit_metadata_sync(self):
        node = self.functions["lore_repair_series"][0]
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertIn(
            "lore_sync_explicit_series_attachments", calls,
            "Repair/Reconcile must synchronize registered Nightmare book metadata",
        )

    def test_continuity_audit_covers_key_conflicts(self):
        node = self.functions.get("lore_validate_series_continuity", [None])[0]
        self.assertIsNotNone(node, "Continuity audit function must exist")
        segment = ast.get_source_segment(self.source, node) or ""
        for code in (
            "DUPLICATE_PROJECT",
            "DUPLICATE_BOOK_NUMBER",
            "MISSING_PROJECT_FOLDER",
            "SERIES_NAME_MISMATCH",
            "SERIES_ID_MISMATCH",
            "BOOK_NUMBER_MISMATCH",
            "WORLD_NAME_MISMATCH",
        ):
            with self.subTest(code=code):
                self.assertIn(code, segment)
        self.assertNotIn("save_json(", segment)
        self.assertNotIn("save_series_bible(", segment)

    def test_analysis_runs_continuity_audit(self):
        node = self.functions["lore_analyze_series"][0]
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertIn("lore_validate_series_continuity", calls)

    def test_selector_preserves_selection_by_project_identity(self):
        node = self.functions["lore_manual_select_projects"][0]
        source_segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("selected_projects", source_segment)
        self.assertIn("difference_update(visible_projects)", source_segment)
        self.assertIn("filter_var.trace_add", source_segment)
        self.assertIn("Add Selected Books", source_segment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
