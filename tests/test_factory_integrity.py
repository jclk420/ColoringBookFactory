"""Fast, dependency-free integrity tests for the Coloring Book Factory source."""
import ast
import datetime
import json
import pathlib
import re
import tempfile
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
        self.assertIn('FACTORY_VERSION = "19.0"', self.source)

    def test_critical_functions_are_defined_exactly_once(self):
        critical = (
            "lore_analyze_series",
            "lore_repair_series",
            "lore_manual_select_projects",
            "lore_sync_explicit_series_attachments",
            "lore_register_book",
            "lore_repair_world_book_links",
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
            "WORLD_ID_MISMATCH",
            "PROJECT_WORLD_ID_MISSING",
            "PROJECT_NOT_LINKED_TO_WORLD",
            "WORLD_BOOKS_LIST_INVALID",
            "WORLD_BOOK_REGISTRY_UNREADABLE",
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

    def test_manual_attachment_uses_conflict_safe_sync(self):
        node = self.functions["lore_manual_select_projects"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("lore_sync_explicit_series_attachments(bible)", segment)
        self.assertNotIn('settings["series_name"] =', segment)
        self.assertNotIn('settings["series_id"] =', segment)
        self.assertNotIn('settings["book_number"] =', segment)

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
        self.assertIn('"world_id"', sync_segment)
        self.assertIn('"book_number"', sync_segment)
        self.assertIn("world_index_path", sync_segment)
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
        self.assertIn('FACTORY_VERSION = "19.0"', self.source)

    def test_world_series_link_repair_is_explicit_and_non_creating(self):
        node = self.functions["lore_ensure_series_world_link"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        for token in (
            "world_index_missing",
            "world_not_registered",
            "ambiguous_world_name",
            "world_record_missing",
            "series_world_id_mismatch",
            'bible["world_id"] = world_id',
            "already_linked",
            'world["series"].append(series_name)',
            "save_json(world_file, world)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, segment)
        self.assertNotIn("mkdir(", segment)
        self.assertNotIn("new_world_record(", segment)

    def test_repair_links_series_to_world_and_reports_status(self):
        node = self.functions["lore_repair_series"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertGreaterEqual(segment.count("lore_ensure_series_world_link(bible)"), 2)
        self.assertIn('"world_link_status": world_link_status', segment)
        self.assertIn("World-to-series link:", segment)
        self.assertIn('"error_count"', segment)
        self.assertIn('"warning_count"', segment)

    def test_continuity_audit_checks_world_to_series_hierarchy(self):
        node = self.functions["lore_validate_series_continuity"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        for code in (
            "SERIES_WORLD_UNASSIGNED",
            "WORLD_INDEX_MISSING",
            "WORLD_NOT_REGISTERED",
            "WORLD_RECORD_MISSING",
            "SERIES_NOT_LINKED_TO_WORLD",
            "SERIES_WORLD_ID_MISSING",
            "SERIES_WORLD_ID_MISMATCH",
            "UNREADABLE_WORLD_INDEX",
            "UNREADABLE_WORLD_RECORD",
        ):
            with self.subTest(code=code):
                self.assertIn(code, segment)
        self.assertIn("WORLDS_DIR / WORLD_INDEX_FILENAME", segment)
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        self.assertNotIn("load_world_index", calls)
        self.assertNotIn("save_world", calls)
        self.assertNotIn("save_world_index", calls)

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

    def test_world_book_repair_is_explicit_conflict_safe_and_non_creating(self):
        node = self.functions["lore_repair_world_book_links"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        for token in (
            "world_index_missing", "world_not_registered", "ambiguous_world_name",
            "world_record_missing", "world_books_list_invalid",
            "PROJECT_WORLD_ID_CONFLICT", "PROJECT_WORLD_NAME_CONFLICT",
            'settings["world_id"] = world_id',
            'settings["universe_name"] = world_name',
            '"world_relationship"', '"world_canon"',
            'world["books"] = world_books', '"linked"', '"metadata_filled"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, segment)
        self.assertNotIn("mkdir(", segment)
        self.assertNotIn("new_world_record(", segment)
        self.assertNotIn('settings["world_relationship"] =', segment)
        self.assertNotIn('settings["world_canon"] =', segment)

    def test_repair_report_includes_world_book_repair(self):
        node = self.functions["lore_repair_series"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertGreaterEqual(segment.count("lore_repair_world_book_links(bible)"), 2)
        self.assertGreaterEqual(segment.count('"world_book_repair": world_book_repair'), 2)

    def _run_world_book_repair_fixture(self, project_settings):
        node = self.functions["lore_repair_world_book_links"][0]
        module = ast.Module(body=[node], type_ignores=[])
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            projects = root / "Projects"
            worlds = root / "Worlds"
            project = projects / "Fixture Book"
            world_dir = worlds / "Nightmare World"
            project.mkdir(parents=True)
            world_dir.mkdir(parents=True)
            (worlds / "world_index.json").write_text(json.dumps({
                "worlds": {"Nightmare World": {"name": "Nightmare World"}}
            }), encoding="utf-8")
            (world_dir / "world.json").write_text(json.dumps({
                "world_id": "Nightmare World", "name": "Nightmare World",
                "books": [], "series": ["Nightmare Series"]
            }), encoding="utf-8")
            (project / "project.json").write_text(json.dumps(project_settings), encoding="utf-8")

            def load_json(path):
                return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

            def save_json(path, data):
                pathlib.Path(path).write_text(json.dumps(data), encoding="utf-8")

            namespace = {
                "Path": pathlib.Path, "datetime": datetime.datetime,
                "PROJECTS": projects, "WORLDS_DIR": worlds,
                "WORLD_INDEX_FILENAME": "world_index.json",
                "load_json": load_json, "save_json": save_json,
            }
            exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
            bible = {
                "name": "Nightmare Series", "world_name": "Nightmare World",
                "world_id": "Nightmare World",
                "books": [{"project": "Fixture Book", "title": "Fixture Book"}],
            }
            result = namespace["lore_repair_world_book_links"](bible)
            return result, load_json(project / "project.json"), load_json(world_dir / "world.json")

    def test_world_book_repair_fills_only_missing_identity_and_preserves_flags(self):
        result, settings, world = self._run_world_book_repair_fixture({
            "title": "Fixture Book", "world_relationship": "non_canon",
            "world_canon": False, "custom_setting": "keep",
        })
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(result["linked"], ["Fixture Book"])
        self.assertEqual(settings["world_id"], "Nightmare World")
        self.assertEqual(settings["universe_name"], "Nightmare World")
        self.assertEqual(settings["world_relationship"], "non_canon")
        self.assertIs(settings["world_canon"], False)
        self.assertEqual(settings["custom_setting"], "keep")
        self.assertEqual(world["books"][0]["relationship"], "non_canon")
        self.assertIs(world["books"][0]["canon"], False)

    def test_world_book_repair_preserves_conflicting_world_identity(self):
        result, settings, world = self._run_world_book_repair_fixture({
            "title": "Fixture Book", "world_id": "AREA 420",
            "universe_name": "AREA 420", "world_relationship": "canon",
            "world_canon": True,
        })
        self.assertEqual(settings["world_id"], "AREA 420")
        self.assertEqual(settings["universe_name"], "AREA 420")
        self.assertEqual(result["conflicts"][0]["code"], "PROJECT_WORLD_ID_CONFLICT")
        self.assertEqual(world["books"], [])

    def test_save_json_uses_atomic_same_directory_replacement(self):
        node = self.functions["save_json"][0]
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {
            "Path": pathlib.Path, "tempfile": tempfile, "json": json,
            "os": __import__("os"),
        }
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp) / "record.json"
            target.write_text('{"old": true}', encoding="utf-8")
            exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
            namespace["save_json"](target, {"new": "valid", "count": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": "valid", "count": 2})
            self.assertEqual(list(pathlib.Path(temp).glob("*.tmp")), [])
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("os.fsync(stream.fileno())", segment)
        self.assertIn("os.replace(str(temp_path), str(path))", segment)


    def test_lore_intake_helpers_match_registered_creature_and_safe_path(self):
        names = ("lore_intake_normalize", "lore_intake_safe_folder", "lore_intake_classify", "lore_intake_destination")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [{"kind": "creature", "name": "Stitched Deer", "world": "Nightmare World",
                    "location": "Intake Wing", "bible": "Nightmare Series"}]
        match = namespace["lore_intake_classify"](pathlib.Path("Stitched_Deer.png"), records)
        self.assertEqual(match["kind"], "creature")
        self.assertEqual(match["world"], "Nightmare World")
        self.assertEqual(match["location"], "Intake Wing")
        destination = namespace["lore_intake_destination"](
            pathlib.Path("review"), pathlib.Path("Stitched_Deer.png"), match)
        self.assertEqual(destination.parts[-4:], ("Nightmare World", "Intake Wing", "Stitched Deer", "Stitched_Deer.png"))
        self.assertNotIn("Worlds", destination.parts)

    def test_lore_intake_does_not_guess_ambiguous_names(self):
        names = ("lore_intake_normalize", "lore_intake_classify")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "creature", "name": "Nightmare Crow", "world": "World A", "location": "Tower"},
            {"kind": "creature", "name": "Nightmare Crow", "world": "World B", "location": "Forest"},
        ]
        match = namespace["lore_intake_classify"](pathlib.Path("Nightmare_Crow.jpg"), records)
        self.assertEqual(match["kind"], "ambiguous")
        self.assertEqual(match["confidence"], "LOW")

    def test_lore_intake_uses_review_staging_and_is_menu_connected(self):
        for token in ('INTAKE_DIR = FACTORY / "INTAKE"', "INTAKE_MANIFEST_FILENAME",
                      "STAGED_FOR_REVIEW", "lore_intake_collect_records",
                      "No source files or canon records were changed"):
            self.assertIn(token, self.source)
        menu = self.functions["factory_main_menu"][0]
        segment = ast.get_source_segment(self.source, menu) or ""
        self.assertIn('c=="18"', segment)
        self.assertIn("lore_intake_menu()", segment)


    def test_lore_intake_inspects_image_metadata_and_pdf_extraction_fallback(self):
        names = ("lore_intake_inspect_file",)
        namespace = {"Path": pathlib.Path, "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".webp"},
                     "Image": __import__("PIL.Image", fromlist=["Image"])}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            image_path = pathlib.Path(temp) / "sample.png"
            namespace["Image"].new("RGB", (23, 17)).save(image_path)
            info = namespace["lore_intake_inspect_file"](image_path)
            self.assertEqual((info["width"], info["height"]), (23, 17))
            pdf_info = namespace["lore_intake_inspect_file"](pathlib.Path(temp) / "missing.pdf")
            self.assertEqual(pdf_info["media_type"], "pdf")

    def test_lore_intake_detects_hashes_in_previous_batches(self):
        names = ("lore_intake_existing_hashes",)
        namespace = {"Path": pathlib.Path, "json": json}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp) / "INTAKE"
            batch = root / "Batches" / "old" / "INTAKE_BATCH.json"
            batch.parent.mkdir(parents=True)
            batch.write_text(json.dumps({"batch": "old", "items": [
                {"sha256": "abc", "source": "old.png", "staged_path": "review/old.png"}
            ]}), encoding="utf-8")
            manifest = root / "INTAKE_MANIFEST.json"
            manifest.write_text(json.dumps({"batches": [{"record": str(batch)}]}), encoding="utf-8")
            found = namespace["lore_intake_existing_hashes"](manifest)
            self.assertIn("abc", found)
            self.assertEqual(found["abc"]["batch"], "old")

    def test_approved_registry_deduplicates_without_touching_series_bible(self):
        names = ("lore_intake_normalize", "lore_intake_approved_registry_add")
        namespace = {"Path": pathlib.Path, "json": json, "datetime": datetime.datetime,
                     "lore_intake_normalize": lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip(),
                     "save_json": lambda path, data: pathlib.Path(path).write_text(json.dumps(data), encoding="utf-8")}
        module = ast.Module(body=[self.functions["lore_intake_approved_registry_add"][0]], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        item = {"classification": {"kind": "creature", "name": "Stitched Deer",
                 "world": "Nightmare World", "location": "Intake Wing"}, "sha256": "abc", "staged_path": "x.png"}
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "APPROVED_LORE.json"
            first = namespace["lore_intake_approved_registry_add"](path, item)
            second = namespace["lore_intake_approved_registry_add"](path, item)
            registry = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(first["added"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(len(registry["entities"]), 1)
            self.assertIn("not yet written into a Series Bible", registry["entities"][0]["note"])

    def test_lore_intake_review_and_metadata_are_wired_into_menu(self):
        for token in ("lore_intake_inspect_file(source)", "lore_intake_existing_hashes(manifest_path)",
                      "lore_intake_review_pending()", "APPROVED_LORE.json", "APPROVED_FOR_LORE_REGISTRY",
                      "DUPLICATE_PRIOR_INTAKE", "No selectable text found"):
            self.assertIn(token, self.source)
        menu = self.functions["lore_intake_menu"][0]
        segment = ast.get_source_segment(self.source, menu) or ""
        self.assertIn("Review / correct / approve staged files", segment)
        self.assertIn("Show approved intake registry", segment)

    def test_atomic_json_writer_has_tempfile_import(self):
        self.assertIn("import tempfile", self.source.splitlines())
        self.assertIn("os.replace(str(temp_path), str(path))", self.source)

    def test_save_json_replace_failure_preserves_original(self):
        node = self.functions["save_json"][0]
        module = ast.Module(body=[node], type_ignores=[])
        import os as os_module
        class FailingReplace:
            fsync = staticmethod(os_module.fsync)
            @staticmethod
            def replace(source, destination):
                raise OSError("simulated replace failure")
        namespace = {"Path": pathlib.Path, "tempfile": tempfile, "json": json, "os": FailingReplace}
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp) / "record.json"
            target.write_text('{"old": true}', encoding="utf-8")
            exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
            with self.assertRaises(OSError):
                namespace["save_json"](target, {"new": True})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(pathlib.Path(temp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
