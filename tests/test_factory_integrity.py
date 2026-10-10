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

    def test_manual_attachment_prevents_duplicate_book_numbers(self):
        node = self.functions["lore_manual_select_projects"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("reserved_numbers", segment)
        self.assertIn("already assigned in this Series Bible", segment)
        self.assertIn("reserved_numbers.add(parsed)", segment)

    def test_legacy_repair_does_not_force_overwrite_metadata(self):
        node = self.functions["lore_repair_series"][0]
        forced_keys = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "settings"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value in {"series_name", "series_id", "book_number", "universe_name"}
                ):
                    forced_keys.add(target.slice.value)
        self.assertFalse(
            forced_keys,
            f"Repair must not directly overwrite conflicting metadata: {sorted(forced_keys)}",
        )
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("lore_sync_explicit_series_attachments", segment)
        self.assertIn("conflict", segment.casefold())

    def test_sync_preserves_existing_canon_conflicts(self):
        helper = self.functions.get("lore_safe_metadata_updates", [None])[0]
        self.assertIsNotNone(helper, "Safe metadata merge policy must be isolated")
        helper_segment = ast.get_source_segment(self.source, helper) or ""
        for token in ("current_missing", "elif current != expected", "conflicts.append"):
            with self.subTest(token=token):
                self.assertIn(token, helper_segment)
        sync = self.functions["lore_sync_explicit_series_attachments"][0]
        sync_segment = ast.get_source_segment(self.source, sync) or ""
        self.assertIn('"universe_name"', sync_segment)
        self.assertIn('"book_number"', sync_segment)
        self.assertIn("lore_safe_metadata_updates", sync_segment)

    def test_safe_metadata_merge_runtime_preserves_conflicts(self):
        helper = self.functions["lore_safe_metadata_updates"][0]
        module = ast.Module(body=[helper], type_ignores=[])
        namespace = {}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        settings = {
            "series_name": "AREA 420",
            "series_id": "area-420",
            "book_number": 8,
            "universe_name": "AREA 420",
            "custom_setting": "preserve me",
        }
        conflicts = namespace["lore_safe_metadata_updates"](
            settings,
            (
                ("series_name", "Nightmare Series"),
                ("series_id", "nightmare-series"),
                ("book_number", 2),
                ("universe_name", "Nightmare World"),
            ),
        )
        self.assertEqual(len(conflicts), 4)
        self.assertEqual(settings["series_name"], "AREA 420")
        self.assertEqual(settings["series_id"], "area-420")
        self.assertEqual(settings["book_number"], 8)
        self.assertEqual(settings["universe_name"], "AREA 420")
        self.assertEqual(settings["custom_setting"], "preserve me")

    def test_safe_metadata_merge_fills_missing_values(self):
        helper = self.functions["lore_safe_metadata_updates"][0]
        module = ast.Module(body=[helper], type_ignores=[])
        namespace = {}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        settings = {"series_name": "", "book_number": None}
        conflicts = namespace["lore_safe_metadata_updates"](
            settings,
            (("series_name", "Nightmare Series"), ("book_number", 1), ("universe_name", "Nightmare World")),
        )
        self.assertEqual(conflicts, [])
        self.assertEqual(settings["series_name"], "Nightmare Series")
        self.assertEqual(settings["book_number"], 1)
        self.assertEqual(settings["universe_name"], "Nightmare World")

    def test_repair_persists_continuity_findings(self):
        node = self.functions["lore_repair_series"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn('"possible_conflicts": findings', segment)
        self.assertIn('"error_count"', segment)
        self.assertIn('"warning_count"', segment)
        self.assertIn('"LORE_REPAIR_REPORT.json"', segment)
        self.assertIn("lore_validate_series_continuity(bible)", segment)
        self.assertIn('FACTORY_VERSION = "17.3"', self.source)

    def test_continuity_audit_checks_world_to_series_hierarchy(self):
        node = self.functions["lore_validate_series_continuity"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        for code in (
            "SERIES_WORLD_UNASSIGNED",
            "WORLD_INDEX_MISSING",
            "WORLD_NOT_REGISTERED",
            "WORLD_RECORD_MISSING",
            "SERIES_NOT_LINKED_TO_WORLD",
            "UNREADABLE_WORLD_INDEX",
            "UNREADABLE_WORLD_RECORD",
        ):
            with self.subTest(code=code):
                self.assertIn(code, segment)
        self.assertIn("WORLDS_DIR / WORLD_INDEX_FILENAME", segment)
        self.assertNotIn("load_world_index(", segment)
        self.assertNotIn("save_world(", segment)
        self.assertNotIn("save_world_index(", segment)

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
