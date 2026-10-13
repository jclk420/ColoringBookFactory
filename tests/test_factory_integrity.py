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
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)

    def test_listing_quality_gate_is_registered_once(self):
        self.assertEqual(
            len(self.functions.get("v29_listing_quality_gate", [])), 1,
            "Listing quality gate must have exactly one definition",
        )
        segment = ast.get_source_segment(
            self.source, self.functions["v29_listing_quality_gate"][0]
        ) or ""
        for token in ("missing_required", "user_actions", "published", "READY_FOR_REVIEW"):
            with self.subTest(token=token):
                self.assertIn(token, segment)

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
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)

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


    def test_v25_lore_intake_uses_pdf_metadata_only_when_filename_has_no_match(self):
        names = ("lore_intake_normalize", "lore_intake_classify")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "creature", "name": "Hollow Stag", "world": "Nightmare World",
             "location": "Hollow Stitch Nursery", "bible": "Nightmare Series"}
        ]
        match = namespace["lore_intake_classify"](
            pathlib.Path("scan_004.pdf"), records,
            {"pdf_title": "Field Notes", "text_preview": "Recovered record: Hollow Stag was found."})
        self.assertEqual(match["kind"], "creature")
        self.assertEqual(match["name"], "Hollow Stag")
        self.assertEqual(match["confidence"], "MEDIUM")
        self.assertEqual(match["matched_in"], ["pdf_text"])
        self.assertIn("readable PDF", match["reason"])

    def test_v25_lore_intake_keeps_metadata_ambiguity_unresolved(self):
        names = ("lore_intake_normalize", "lore_intake_classify")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "creature", "name": "Hollow Stag", "world": "World A", "location": "Nursery"},
            {"kind": "creature", "name": "Hollow Stag", "world": "World B", "location": "Forest"},
        ]
        match = namespace["lore_intake_classify"](
            pathlib.Path("scan_004.pdf"), records,
            {"pdf_title": "Hollow Stag", "text_preview": ""})
        self.assertEqual(match["kind"], "ambiguous")
        self.assertEqual(match["confidence"], "LOW")
        self.assertEqual(match["matched_in"], ["pdf_title"])

    def test_pending_lore_intake_refresh_is_menu_connected_and_review_safe(self):
        node = self.functions.get("lore_intake_refresh_pending", [None])[0]
        self.assertIsNotNone(node, "Pending intake refresh function must exist")
        segment = ast.get_source_segment(self.source, node) or ""
        for token in ("STAGED_FOR_REVIEW", "classification_refresh_history",
                      "lore_intake_collect_records", "lore_intake_classify",
                      "lore_intake_destination", "shutil.move", "save_json"):
            with self.subTest(token=token):
                self.assertIn(token, segment)
        self.assertIn('print("5. Refresh pending classifications against current lore")', self.source)
        menu = self.functions["lore_intake_menu"][0]
        menu_segment = ast.get_source_segment(self.source, menu) or ""
        self.assertIn('elif choice == "5":', menu_segment)
        self.assertIn("lore_intake_refresh_pending()", menu_segment)
        self.assertIn('item.get("status", "")).upper() != "STAGED_FOR_REVIEW"', segment)
        self.assertNotIn("lore_intake_approved_registry_add", segment)
        self.assertNotIn("save_series_bible", segment)

    def test_registered_location_in_pdf_title_is_classified_as_location_context(self):
        normalize = self.functions["lore_intake_normalize"][0]
        classify = self.functions["lore_intake_classify"][0]
        module = ast.Module(body=[normalize, classify], type_ignores=[])
        namespace = {"Path": pathlib.Path, "re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "book", "name": "Nightmare Cryptids", "world": "Nightmare World",
             "location": "Unassigned Location", "bible": "Nightmare Series"},
            {"kind": "location", "name": "Hollow Stitch Nursery", "world": "Nightmare World",
             "location": "Hollow Stitch Nursery", "bible": "Nightmare Series"},
        ]
        result = namespace["lore_intake_classify"](
            pathlib.Path("cOPYCryptidsInterior.pdf"), records,
            {"pdf_title": "Nightmare Cryptids: A Horror Coloring Adventure - Hollow Stitch Nursery Archive",
             "text_preview": ""},
        )
        self.assertEqual(result["kind"], "book")
        self.assertEqual(result["name"], "Nightmare Cryptids")
        self.assertEqual(result["world"], "Nightmare World")
        self.assertEqual(result["location"], "Hollow Stitch Nursery")
        self.assertEqual(result["location_evidence"], ["pdf_title"])

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
        import contextlib
        import types
        fake_image = types.SimpleNamespace(width=23, height=17, format="PNG")
        image_api = types.SimpleNamespace(open=staticmethod(lambda path: contextlib.nullcontext(fake_image)))
        namespace = {"Path": pathlib.Path, "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".webp"},
                     "Image": image_api}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            image_path = pathlib.Path(temp) / "sample.png"
            image_path.write_bytes(b"fake-image")
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


    def test_v20_release_safety_and_lore_diagnostics_are_wired(self):
        required = ("v20_release_preflight", "v20_release_change_summary",
                    "v20_verified_restore_drill", "v20_machine_diagnostics",
                    "v20_lore_consistency_matrix", "v20_release_lore_diagnostics_menu")
        for name in required:
            with self.subTest(function=name):
                self.assertEqual(len(self.functions.get(name, [])), 1)
        self.assertIn('elif c=="19": v20_release_lore_diagnostics_menu()', self.source)
        self.assertIn('"READ_ONLY_PREFLIGHT"', self.source)
        self.assertIn('"restore_performed": False', self.source)
        self.assertIn('"FACTORY_DIAGNOSTICS.json"', self.source)

    def test_v21_canon_tools_are_unique_and_wired(self):
        required = (
            "v21_series_bibles", "v21_choose_bible", "v21_load_approved_registry",
            "v21_entity_rows", "v21_entity_key", "v21_entity_conflicts",
            "v21_import_preview", "v21_append_canon_changelog",
            "v21_import_approved_lore", "v21_conflict_resolution_queue",
            "v21_entity_reuse_report", "v21_book_series_coverage_report",
            "v21_canon_tools_menu",
        )
        for name in required:
            with self.subTest(function=name):
                self.assertEqual(len(self.functions.get(name, [])), 1)
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)
        self.assertIn('elif c=="20": v21_canon_tools_menu()', self.source)

    def test_v21_import_preview_is_read_only_and_blocks_unsupported_shapes(self):
        node = self.functions["v21_import_preview"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertNotIn("save_json(", segment)
        self.assertNotIn("shutil.copy", segment)
        self.assertIn('"world"', segment)
        self.assertIn("unsupported schema", segment.casefold())
        self.assertIn('"blocked"', segment)

    def test_v21_canon_import_requires_explicit_confirmation_and_backup(self):
        node = self.functions["v21_import_approved_lore"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        for token in ('Type IMPORT', 'confirm != "IMPORT"', "shutil.copy2", "v21_append_canon_changelog"):
            with self.subTest(token=token):
                self.assertIn(token, segment)

    def test_v21_diagnostics_do_not_mutate_series_bible(self):
        for name in ("v21_entity_reuse_report", "v21_book_series_coverage_report"):
            node = self.functions[name][0]
            segment = ast.get_source_segment(self.source, node) or ""
            with self.subTest(function=name):
                self.assertNotIn("save_json(bible_path", segment)
                self.assertNotIn("bible[", segment)


    def test_v22_platform_listing_builder_is_unique_and_wired(self):
        required = (
            "v22_listing_text", "v22_build_platform_listing",
            "v22_build_all_platform_listings", "v22_platform_listing_menu",
        )
        for name in required:
            with self.subTest(function=name):
                self.assertEqual(len(self.functions.get(name, [])), 1)
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)
        self.assertIn('elif c=="21": v22_platform_listing_menu()', self.source)
        self.assertIn('"LISTING_READINESS.json"', self.source)
        self.assertIn('"published": False', self.source)

    def test_v22_listing_builder_does_not_invent_price_or_claim_upload(self):
        node = self.functions["v22_build_platform_listing"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn('"price": ""', segment)
        self.assertIn('"list_price": ""', segment)
        self.assertIn('"published": False', segment)


    def test_v23_reliability_toolkit_functions_are_unique_and_wired(self):
        required = (
            "v23_capability_report", "v23_verify_package_root",
            "v23_package_manifest_verify", "v23_build_fingerprint",
            "v23_project_migration_plan", "v23_apply_project_migration",
            "v23_run_e2e_fixture", "v23_reliability_toolkit_menu",
        )
        for name in required:
            with self.subTest(function=name):
                self.assertEqual(len(self.functions.get(name, [])), 1)
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)
        self.assertIn('elif c=="22": v23_reliability_toolkit_menu()', self.source)
        self.assertIn('"master_rebuilt": False', self.source)
        self.assertIn('"production_projects_modified": False', self.source)

    def test_v23_manifest_verifier_detects_tampering_without_mutating_package(self):
        node = self.functions["v23_verify_package_root"][0]
        namespace = {"Path": pathlib.Path, "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")), "file_hash": lambda p: __import__("hashlib").sha256(pathlib.Path(p).read_bytes()).hexdigest()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<v23-manifest-test>", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp) / "KDP"
            root.mkdir()
            artifact = root / "sample.txt"
            artifact.write_text("original", encoding="utf-8")
            digest = namespace["file_hash"](artifact)
            (root / "PACKAGE_MANIFEST.json").write_text(json.dumps({"schema_version": 1, "files": ["sample.txt"], "file_hashes": {"sample.txt": digest}}), encoding="utf-8")
            self.assertEqual(namespace["v23_verify_package_root"](root)["status"], "READY")
            artifact.write_text("changed", encoding="utf-8")
            result = namespace["v23_verify_package_root"](root)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("SHA-256 mismatch" in item for item in result["errors"]))

    def test_v23_migration_preview_only_adds_missing_known_fields(self):
        node = self.functions["v23_project_migration_plan"][0]
        namespace = {"Path": pathlib.Path, "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")), "WORLD_ENGINE_VERSION": "1.1", "FACTORY_VERSION": "24.0"}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<v23-migration-test>", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            project = pathlib.Path(temp) / "Book"
            project.mkdir()
            config = project / "project.json"
            original = {"title": "Book", "world_engine_version": "legacy-custom"}
            config.write_text(json.dumps(original), encoding="utf-8")
            plan = namespace["v23_project_migration_plan"](project)
            self.assertEqual(plan["status"], "READY_TO_MIGRATE")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), original)
            self.assertNotIn("world_engine_version", plan["changes"])
            self.assertIn("book_spec_version", plan["changes"])

    def test_v24_repair_preview_is_read_only_and_preserves_conflicts(self):
        node = self.functions.get("lore_build_repair_preview", [None])[0]
        self.assertIsNotNone(node, "v24 repair preview helper must exist")
        namespace = {
            "Path": pathlib.Path, "PROJECTS": pathlib.Path("."),
            "WORLDS_DIR": pathlib.Path("."), "WORLD_INDEX_FILENAME": "world_index.json",
            "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<v24-preview-test>", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            projects, worlds = root / "Projects", root / "Worlds"
            project = projects / "Sample Nightmare Book"
            project.mkdir(parents=True)
            worlds.mkdir()
            (worlds / "world_index.json").write_text(json.dumps({
                "worlds": {"nightmare-world": {"name": "Nightmare World"}}
            }), encoding="utf-8")
            metadata = {"title": "Sample Nightmare Book", "series_name": "AREA 420", "book_number": 9}
            config = project / "project.json"
            config.write_text(json.dumps(metadata), encoding="utf-8")
            namespace["PROJECTS"], namespace["WORLDS_DIR"] = projects, worlds
            bible = {
                "name": "Nightmare Series", "series_id": "nightmare-series",
                "world_name": "Nightmare World",
                "books": [{"title": "Sample Nightmare Book", "project": "Sample Nightmare Book", "book_number": 1}],
            }
            plan = namespace["lore_build_repair_preview"](bible)
            self.assertEqual(plan["status"], "REVIEW")
            self.assertEqual(plan["fill_count"], 3)
            self.assertEqual(plan["conflict_count"], 2)
            item = plan["items"][0]
            self.assertEqual({x["field"] for x in item["fills"]}, {"series_id", "universe_name", "world_id"})
            self.assertEqual({x["field"] for x in item["conflicts"]}, {"series_name", "book_number"})
            self.assertTrue(all(x["action"] == "PRESERVE_EXISTING_VALUE" for x in item["conflicts"]))
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), metadata)

    def test_v24_repair_previews_and_requires_confirmation_without_forced_picker(self):
        node = self.functions["lore_repair_series"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("lore_build_repair_preview(bible)", segment)
        self.assertIn('!= "REPAIR"', segment)
        self.assertNotIn("lore_manual_select_projects(bible)", segment)
        self.assertLess(segment.index("lore_build_repair_preview(bible)"), segment.index("lore_sync_explicit_series_attachments(bible)"))
        self.assertIn("No books are registered in this Nightmare Series Bible yet.", segment)

    def test_v26_lore_intake_dashboard_summarizes_without_writing(self):
        node = self.functions.get("lore_intake_review_dashboard", [None])[0]
        self.assertIsNotNone(node, "v26 read-only lore intake dashboard must exist")
        helper = self.functions["lore_intake_build_evidence_graph"][0]
        namespace = {"Path": pathlib.Path, "INTAKE_DIR": pathlib.Path("."),
                     "INTAKE_MANIFEST_FILENAME": "manifest.json", "re": re,
                     "lore_intake_build_evidence_graph": None,
                     "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8"))}
        helper_namespace = {"re": re}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "<v30-evidence-graph>", "exec"), helper_namespace)
        namespace["lore_intake_build_evidence_graph"] = helper_namespace["lore_intake_build_evidence_graph"]
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<v26-dashboard-test>", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            intake = root / "INTAKE"
            intake.mkdir()
            (intake / "manifest.json").write_text(json.dumps({"batches": [{"record": "batch.json"}]}), encoding="utf-8")
            report = {"items": [
                {"source": "Cryptid.pdf", "status": "STAGED_FOR_REVIEW",
                 "classification": {"kind": "creature", "name": "Cryptid", "world": "Nightmare World",
                                    "location": "Intake Wing", "confidence": "MEDIUM", "matched_in": ["pdf_title"]},
                 "metadata": {"pdf_title": "Cryptid"}},
                {"source": "unknown.png", "status": "STAGED_FOR_REVIEW",
                 "classification": {"kind": "ambiguous", "name": "", "world": "Unassigned World",
                                    "location": "Unassigned Location", "confidence": "LOW", "matched_in": []}},
                {"source": "copy.png", "status": "DUPLICATE_SKIPPED", "duplicate": True,
                 "classification": {"kind": "unmatched", "name": ""}}
            ]}
            (intake / "batch.json").write_text(json.dumps(report), encoding="utf-8")
            namespace["INTAKE_DIR"] = intake
            before_manifest = (intake / "manifest.json").read_bytes()
            before_report = (intake / "batch.json").read_bytes()
            result = namespace["lore_intake_review_dashboard"]()
            self.assertEqual(result["items"], 3)
            self.assertEqual(result["pending"], 2)
            self.assertEqual(result["duplicates"], 1)
            self.assertEqual(result["unresolved"], 2)
            self.assertEqual((intake / "manifest.json").read_bytes(), before_manifest)
            self.assertEqual((intake / "batch.json").read_bytes(), before_report)

    def test_v26_dashboard_is_unique_and_connected_to_lore_intake_menu(self):
        self.assertEqual(len(self.functions.get("lore_intake_review_dashboard", [])), 1)
        segment = ast.get_source_segment(self.source, self.functions["lore_intake_menu"][0]) or ""
        self.assertIn('choice == "4"', segment)
        self.assertIn("lore_intake_review_dashboard()", segment)
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)

    def test_v27_location_context_enriches_book_without_replacing_primary_match(self):
        names = ("lore_intake_normalize", "lore_intake_classify")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "book", "name": "Nightmare Cryptids", "world": "Nightmare World",
             "location": "Unassigned Location", "bible": "Nightmare Series"},
            {"kind": "location", "name": "Hollow Stitch Nursery", "world": "Nightmare World",
             "location": "Hollow Stitch Nursery", "bible": "Nightmare Series"},
        ]
        result = namespace["lore_intake_classify"](
            pathlib.Path("Nightmare Cryptids.pdf"), records,
            {"pdf_title": "Nightmare Cryptids: Hollow Stitch Nursery Archive", "text_preview": ""})
        self.assertEqual(result["kind"], "book")
        self.assertEqual(result["name"], "Nightmare Cryptids")
        self.assertEqual(result["world"], "Nightmare World")
        self.assertEqual(result["location"], "Hollow Stitch Nursery")
        self.assertEqual(result["location_evidence"], ["pdf_title"])
        self.assertEqual(result["location_confidence"], "MEDIUM")
        self.assertEqual(result["location_reason"], "Exact registered location phrase found in file evidence")

    def test_v27_ambiguous_location_context_stays_unassigned(self):
        names = ("lore_intake_normalize", "lore_intake_classify")
        namespace = {"re": re, "Path": pathlib.Path}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "book", "name": "Nightmare Cryptids", "world": "Nightmare World",
             "location": "Unassigned Location"},
            {"kind": "location", "name": "Hollow Stitch Nursery", "world": "Nightmare World",
             "location": "Hollow Stitch Nursery"},
            {"kind": "location", "name": "Intake Wing", "world": "Nightmare World",
             "location": "Intake Wing"},
        ]
        result = namespace["lore_intake_classify"](
            pathlib.Path("Nightmare Cryptids.pdf"), records,
            {"pdf_title": "Nightmare Cryptids — Hollow Stitch Nursery, Intake Wing", "text_preview": ""})
        self.assertEqual(result["kind"], "book")
        self.assertEqual(result["name"], "Nightmare Cryptids")
        self.assertEqual(result["location"], "Unassigned Location")
        self.assertEqual(result["location_confidence"], "LOW")
        self.assertCountEqual(result["location_candidates"], ["Hollow Stitch Nursery", "Intake Wing"])


    def test_lore_review_evidence_collects_exact_mentions_and_aliases(self):
        names = ["lore_intake_normalize", "lore_intake_extract_text_entities", "lore_intake_review_evidence"]
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        namespace = {"Path": pathlib.Path, "re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "book", "name": "Nightmare Cryptids", "world": "Nightmare World",
             "aliases": ["Cryptids Archive"]},
            {"kind": "location", "name": "Hollow Stitch Nursery", "world": "Nightmare World",
             "location": "Hollow Stitch Nursery"},
        ]
        result = namespace["lore_intake_review_evidence"](
            pathlib.Path("Cryptids.pdf"), records,
            {"pdf_title": "Nightmare Cryptids — Hollow Stitch Nursery Archive", "text_preview": ""})
        self.assertEqual({x["name"] for x in result["candidate_mentions"]},
                         {"Nightmare Cryptids", "Hollow Stitch Nursery"})
        self.assertEqual(result["duplicate_warnings"], [])
        self.assertEqual(result["hierarchy_warnings"], [])

    def test_lore_review_evidence_flags_duplicate_names_and_cross_world_mentions(self):
        names = ["lore_intake_normalize", "lore_intake_extract_text_entities", "lore_intake_review_evidence"]
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        namespace = {"Path": pathlib.Path, "re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {"kind": "creature", "name": "The Hollow", "world": "Nightmare World", "location": "Nursery"},
            {"kind": "location", "name": "The Hollow", "world": "AREA 420", "location": "The Hollow"},
        ]
        result = namespace["lore_intake_review_evidence"](
            pathlib.Path("The Hollow.pdf"), records, {"pdf_title": "", "text_preview": ""})
        self.assertEqual(len(result["duplicate_warnings"]), 1)
        self.assertEqual(len(result["hierarchy_warnings"]), 1)
        self.assertIn("AREA 420", result["hierarchy_warnings"][0]["worlds"])


    def test_v272_extracts_only_explicit_text_entity_labels_and_relationships(self):
        names = ["lore_intake_normalize", "lore_intake_extract_text_entities",
                 "lore_intake_review_evidence"]
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        namespace = {"Path": pathlib.Path, "re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        text = (
            "Creature: The Hollow Stitcher\n"
            "Location: Hollow Stitch Nursery\n"
            "Found at: Intake Wing\n"
            "An unrelated Title Case Heading\n"
            "World: Nightmare World\n"
        )
        extracted = namespace["lore_intake_extract_text_entities"](text)
        self.assertIn(("creature", "The Hollow Stitcher"),
                      {(x["kind"], x["name"]) for x in extracted["entity_candidates"]})
        self.assertIn(("location", "Hollow Stitch Nursery"),
                      {(x["kind"], x["name"]) for x in extracted["entity_candidates"]})
        self.assertTrue(any(x["subject"] == "The Hollow Stitcher"
                            and x["object"] == "Hollow Stitch Nursery"
                            and x["relation"] == "located_at"
                            for x in extracted["relationships"]))
        self.assertTrue(any(x["object"] == "Intake Wing"
                            for x in extracted["relationships"]))
        self.assertFalse(any(x["name"] == "An unrelated Title Case Heading"
                             for x in extracted["entity_candidates"]))
        self.assertTrue(all(x["confidence"] == "LOW"
                            for x in extracted["entity_candidates"] + extracted["relationships"]))
        result = namespace["lore_intake_review_evidence"](
            pathlib.Path("Cryptids.pdf"), [],
            {"pdf_title": "", "text_preview": text})
        self.assertEqual(result["extracted_entity_candidates"], extracted["entity_candidates"])
        self.assertEqual(result["extracted_relationships"], extracted["relationships"])

    def test_v30_archive_id_conflicts_are_preserved_for_review(self):
        names = ["lore_intake_extract_text_entities", "lore_intake_build_evidence_graph"]
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        namespace = {"re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        text = (
            "Ahool\nWinged cryptid\nH.S.N. FILE\nHSN-CR-008\n"
            "CLASSIFICATION: Aerial\nEND FILE HSN-CR-003\n"
            "Ahool\nWinged cryptid\nH.S.N. FILE\nHSN-CR-003\n"
            "CLASSIFICATION: Aerial\nEND FILE HSN-CR-003\n"
        )
        extracted = namespace["lore_intake_extract_text_entities"](text)
        ahool = next(row for row in extracted["entity_candidates"]
                     if row["kind"] == "creature" and row["name"] == "Ahool")
        self.assertEqual(ahool["archive_id"], "HSN-CR-008")
        self.assertIn("HSN-CR-003", {
            row["archive_id"] for row in ahool.get("archive_id_candidates", [])
        })
        self.assertTrue(any("Conflicting archive IDs" in warning
                            for warning in ahool.get("archive_warnings", [])))
        graph = namespace["lore_intake_build_evidence_graph"]([{
            "file": "cryptids.pdf", "kind": "book", "name": "Nightmare Cryptids",
            "world": "Nightmare World", "location": "Hollow Stitch Nursery",
            "extracted_entity_candidates": [ahool, {
                "kind": "creature", "name": "Dover Demon",
                "archive_id": "HSN-CR-008", "confidence": "LOW",
            }],
        }])
        self.assertTrue(graph["review_only"])
        self.assertFalse(graph["canon_written"])
        self.assertTrue(any(row["archive_id"] == "HSN-CR-008"
                            and set(row["candidate_names"]) == {"ahool", "dover demon"}
                            for row in graph["archive_id_conflicts"]))

    def test_v272_text_extraction_is_empty_safe_and_does_not_promote_canon(self):
        names = ["lore_intake_extract_text_entities"]
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        namespace = {"re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        self.assertEqual(namespace["lore_intake_extract_text_entities"](""), {
            "entity_candidates": [], "relationships": []})
        self.assertEqual(namespace["lore_intake_extract_text_entities"](None), {
            "entity_candidates": [], "relationships": []})
        node = self.functions["lore_intake_extract_text_entities"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertNotIn("save_json(", segment)
        self.assertNotIn("APPROVED_LORE", segment)

    def test_v275_path_match_resolves_relative_records_from_known_roots(self):
        node = self.functions.get("lore_intake_paths_match", [None])[0]
        self.assertIsNotNone(node, "relative-path matching helper must exist")
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"Path": pathlib.Path}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            intake = root / "INTAKE"
            intake.mkdir()
            staged = intake / "pending" / "cryptids.pdf"
            staged.parent.mkdir()
            staged.write_bytes(b"")
            match = namespace["lore_intake_paths_match"]
            self.assertTrue(match("pending/cryptids.pdf", staged, (intake,)))
            self.assertTrue(match(str(staged), staged, (intake,)))
            self.assertFalse(match("pending/other.pdf", staged, (intake,)))
            self.assertFalse(match(None, staged, (intake,)))

    def test_v27_4_ocr_review_is_menu_connected_and_review_only(self):
        node = self.functions.get("lore_intake_ocr_pending_file", [None])[0]
        self.assertIsNotNone(node, "OCR pending-file integration must exist")
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn("lore_ocr_extract_text", segment)
        self.assertIn("lore_intake_extract_text_entities", segment)
        self.assertIn('status", "")).upper() != "STAGED_FOR_REVIEW"', segment)
        self.assertIn("save_json(report_path, report)", segment)
        self.assertNotIn("write_world_bible(", segment)
        self.assertNotIn("APPROVED_LORE.json", segment)
        menu = ast.get_source_segment(self.source, self.functions["lore_intake_menu"][0]) or ""
        self.assertIn('print("6. OCR a staged pending PDF/image (low-confidence review only)")', menu)
        self.assertIn('choice == "6"', menu)
        self.assertIn("lore_intake_ocr_pending_file()", menu)
        self.assertIn('FACTORY_VERSION = "30.0"', self.source)


    def test_v276_extractor_recognizes_hsn_archive_creature_headings(self):
        names = ("lore_intake_extract_text_entities",)
        namespace = {"re": re}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        sample = """EL SILBÓN
The Whistling One
H.S.N. FILE
HSN-CR-001
CLASSIFICATION
Cursed Revenant / Death Herald
ORIGIN
The Llanos of Venezuela and Colombia
DOCUMENTED ABILITY
Acoustic disorientation
"""
        result = namespace["lore_intake_extract_text_entities"](sample)
        entities = result["entity_candidates"]
        self.assertTrue(any(row["kind"] == "creature" and row["name"] == "EL SILBÓN" for row in entities))
        creature = next(row for row in entities if row["name"] == "EL SILBÓN")
        self.assertIn("The Whistling One", creature.get("aliases", []))
        self.assertTrue(all(row["confidence"] == "LOW" for row in entities))
        self.assertTrue(any(row["subject"] == "EL SILBÓN" and
                            row["relation"] == "reported_origin" and
                            row["object"] == "The Llanos of Venezuela and Colombia"
                            for row in result["relationships"]))

    def test_v276_archive_extraction_deduplicates_and_stays_review_only(self):
        names = ("lore_intake_extract_text_entities",)
        namespace = {"re": re}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        sample = """EMELA-NTOUKA
The Killer of Elephants
H.S.N. FILE
HSN-CR-002
ORIGIN
Central African folklore
END FILE HSN-CR-002
"""
        result = namespace["lore_intake_extract_text_entities"](sample)
        names_found = [row["name"] for row in result["entity_candidates"]]
        self.assertEqual(names_found.count("EMELA-NTOUKA"), 1)
        self.assertTrue(result["entity_candidates"])
        self.assertTrue(all(row["confidence"] == "LOW" for row in result["entity_candidates"]))
        self.assertIn("verify before approval", result["entity_candidates"][0]["note"])

    def test_v280_archive_fields_and_id_are_retained_as_review_metadata(self):
        node = self.functions["lore_intake_extract_text_entities"][0]
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        sample = """EL SILBON
The Whistling One
H.S.N. FILE
HSN-CR-00O
CLASSIFICATION: Cursed Revenant
THREAT LEVEL
Severe
ORIGIN: Llanos region
DOCUMENTED ABILITY
Acoustic disorientation
OBSERVED WEAKNESS: Silence
"""
        result = namespace["lore_intake_extract_text_entities"](sample)
        creature = next(row for row in result["entity_candidates"] if row["name"] == "EL SILBON")
        self.assertEqual(creature["archive_id"], "HSN-CR-000")
        self.assertEqual(creature["archive_fields"]["classification"], "Cursed Revenant")
        self.assertEqual(creature["archive_fields"]["threat_level"], "Severe")
        self.assertEqual(creature["archive_fields"]["documented_ability"], "Acoustic disorientation")
        self.assertEqual(creature["archive_fields"]["observed_weakness"], "Silence")
        self.assertIn("HSN-CR-00O", creature["archive_evidence_lines"])
        self.assertEqual(creature["confidence"], "LOW")
        self.assertTrue(any(row["relation"] == "reported_origin" and row["object"] == "Llanos region"
                            for row in result["relationships"]))

    def test_v281_ocr_page_markers_are_not_creature_names(self):
        node = self.functions["lore_intake_extract_text_entities"][0]
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        sample = """[OCR PAGE 6]
EL SILBON
The Whistling One
HSN. FILE HSN-CR-001
CLASSIFICATION Cursed Revenant / Death Herald
END FILE HSN-CR-001
"""
        result = namespace["lore_intake_extract_text_entities"](sample)
        creature = next(row for row in result["entity_candidates"] if row["name"] == "EL SILBON")
        self.assertEqual(creature["aliases"], ["The Whistling One"])
        self.assertNotIn("[OCR PAGE 6]", [row["name"] for row in result["entity_candidates"]])
        self.assertEqual(creature["confidence"], "LOW")


    def test_v280_ocr_candidate_summary_reports_added_and_duplicate_counts(self):
        node = self.functions["lore_intake_ocr_pending_file"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn('"ocr_candidate_summary"', segment)
        self.assertIn('"new_entities_added": len(added_entities)', segment)
        self.assertIn('"duplicate_entities_skipped"', segment)
        self.assertIn('f"New entity candidates added: {len(added_entities)}"', segment)
        self.assertIn('"review_only": True', segment)
        self.assertNotIn("write_world_bible(", segment)
        self.assertNotIn("APPROVED_LORE.json", segment)

    def test_v280_archive_id_ocr_tolerance_is_narrow_and_explicit(self):
        node = self.functions["lore_intake_extract_text_entities"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertIn(r'HSN[- ]?CR[- ]?([0-9O]{3})', segment)
        self.assertIn('.replace("O", "0")', segment)
        self.assertIn('"archive_fields"', segment)



    def test_v281_ocr_inline_hsn_file_metadata_is_low_confidence_and_flags_mismatched_end_id(self):
        node = self.functions["lore_intake_extract_text_entities"][0]
        module = ast.Module(body=[node], type_ignores=[])
        namespace = {"re": re}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        sample = """EL SILBON
The Whistling One
HSN. FILE HSN-CR-001
CLASSIFICATION Cursed Revenant / Death Herald
THREAT LEVEL V EXTREME
ORIGIN The Llanos of Venezuela and Colombia
DOCUMENTED ABILITY Acoustic disorientation
OBSERVED WEAKNESS Silence
END FILE HSN-CR-003
"""
        result = namespace["lore_intake_extract_text_entities"](sample)
        creature = next(row for row in result["entity_candidates"] if row["name"] == "EL SILBON")
        self.assertEqual(creature["archive_id"], "HSN-CR-001")
        self.assertEqual(creature["aliases"], ["The Whistling One"])
        self.assertEqual(creature["archive_fields"]["classification"], "Cursed Revenant / Death Herald")
        self.assertEqual(creature["archive_fields"]["threat_level"], "V EXTREME")
        self.assertEqual(creature["archive_fields"]["origin"], "The Llanos of Venezuela and Colombia")
        self.assertEqual(creature["archive_fields"]["documented_ability"], "Acoustic disorientation")
        self.assertEqual(creature["archive_fields"]["observed_weakness"], "Silence")
        self.assertTrue(any("Mismatched closing archive ID: HSN-CR-003" in warning
                            for warning in creature.get("archive_warnings", [])))
        self.assertEqual(creature["confidence"], "LOW")
        self.assertIn("verify before approval", creature["note"])


    def test_v30_evidence_graph_aggregates_provenance_and_flags_conflicts_without_writes(self):
        names = ("lore_intake_build_evidence_graph",)
        namespace = {"re": re}
        module = ast.Module(body=[self.functions[name][0] for name in names], type_ignores=[])
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        records = [
            {
                "file": "cryptids-a.pdf", "kind": "book", "name": "Nightmare Cryptids",
                "world": "Nightmare World", "location": "Intake Wing", "confidence": "HIGH",
                "evidence": "filename",
                "extracted_entity_candidates": [
                    {"kind": "creature", "name": "The Hollow", "archive_id": "HSN-CR-001",
                     "aliases": ["The Stitcher"], "archive_fields": {"classification": "Entity"},
                     "confidence": "LOW", "evidence": "pdf_text"}
                ],
                "extracted_relationships": [
                    {"subject_kind": "creature", "subject": "The Hollow", "relation": "located_at",
                     "object_kind": "location", "object": "Intake Wing", "confidence": "LOW",
                     "evidence": "Found at: Intake Wing"}
                ],
            },
            {
                "file": "cryptids-b.pdf", "kind": "book", "name": "Nightmare Cryptids",
                "world": "Nightmare World", "location": "Intake Wing", "confidence": "MEDIUM",
                "evidence": "pdf_title",
                "extracted_entity_candidates": [
                    {"kind": "creature", "name": "The Hollow", "archive_id": "HSN-CR-002",
                     "aliases": ["The Stitcher"], "archive_fields": {"classification": "Entity"},
                     "confidence": "LOW", "evidence": "pdf_text"},
                    {"kind": "location", "name": "Intake Wing", "confidence": "LOW"},
                    {"kind": "creature", "name": "The Hollow", "world": "AREA 420",
                     "location": "Forbidden Grow Lab", "confidence": "LOW"}
                ],
                "extracted_relationships": [
                    {"subject_kind": "creature", "subject": "The Hollow", "relation": "located_at",
                     "object_kind": "location", "object": "Unregistered Annex", "confidence": "LOW"}
                ],
            },
        ]
        result = namespace["lore_intake_build_evidence_graph"](records)
        self.assertTrue(result["review_only"])
        self.assertFalse(result["canon_written"])
        self.assertEqual(result["source_record_count"], 2)
        hollow_rows = [row for row in result["entities"] if row["name"] == "The Hollow"]
        self.assertEqual(len(hollow_rows), 3)
        combined = next(row for row in hollow_rows if row["archive_id"] == "HSN-CR-001")
        self.assertEqual(combined["source_files"], ["cryptids-a.pdf"])
        self.assertEqual(combined["aliases"], ["The Stitcher"])
        self.assertTrue(result["duplicate_name_warnings"])
        self.assertEqual(result["archive_id_conflicts"], [])
        self.assertTrue(any(row["object"] == "Unregistered Annex"
                            for row in result["unresolved_relationships"]))
        self.assertEqual(namespace["lore_intake_build_evidence_graph"]([])["entity_count"], 0)

    def test_v30_evidence_graph_is_unique_and_dashboard_connected(self):
        self.assertEqual(len(self.functions.get("lore_intake_build_evidence_graph", [])), 1)
        dashboard = ast.get_source_segment(
            self.source, self.functions["lore_intake_review_dashboard"][0]
        ) or ""
        self.assertIn("lore_intake_build_evidence_graph(summary[\"records\"])", dashboard)
        self.assertIn("evidence_graph", dashboard)
        node = self.functions["lore_intake_build_evidence_graph"][0]
        segment = ast.get_source_segment(self.source, node) or ""
        self.assertNotIn("save_json(", segment)
        self.assertNotIn("save_series_bible(", segment)
        self.assertIn('"canon_written": False', segment)




if __name__ == "__main__":
    unittest.main(verbosity=2)
