"""Runtime tests for malformed JSON state and queue resilience."""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"

HELPER_NAMES = {
    "load_json", "save_json", "load_build_state", "load_build_history",
    "load_queue", "save_queue", "load_world_index", "save_build_state",
    "save_world_index", "load_world", "queue_item_is_safe",
}


def load_state_helpers(projects, worlds):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    helpers = [node for node in tree.body
               if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES]
    if {node.name for node in helpers} != HELPER_NAMES:
        raise AssertionError("Expected each JSON state helper exactly once")
    namespace = {
        "Path": Path, "json": json, "os": os, "tempfile": tempfile,
        "FACTORY_VERSION": "53.0",
        "BUILD_STATE_FILE": "build_state.json",
        "BUILD_HISTORY_FILENAME": "build_history.json",
        "PRODUCTION_QUEUE_FILENAME": "production_queue.json",
        "PROJECTS": projects,
        "WORLDS_DIR": worlds,
        "WORLD_INDEX_FILENAME": "world_index.json",
        "WORLD_SCHEMA_VERSION": 2,
        "WORLD_ENGINE_VERSION": "1.1",
        "world_path": lambda world_id: worlds / str(world_id),
    }
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class JsonStateResilienceTests(unittest.TestCase):
    def test_malformed_build_state_root_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_state.json"
            original = '[1, 2, 3]'
            path.write_text(original, encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            result = helpers["load_build_state"](project)
            self.assertEqual(result, {"version": "53.0", "images": {}, "last_build": None})
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_malformed_build_state_fields_fall_back_in_memory_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_state.json"
            original = {"version": "legacy", "images": ["not", "a", "map"],
                        "last_build": "bad", "custom": "preserve"}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            result = helpers["load_build_state"](project)
            self.assertEqual(result["images"], {})
            self.assertIsNone(result["last_build"])
            self.assertEqual(result["custom"], "preserve")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_malformed_build_history_list_is_reported_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_history.json"
            original = {"version": "old", "builds": "not-a-list", "custom": 7}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            result = helpers["load_build_history"](project)
            self.assertEqual(result["builds"], [])
            self.assertEqual(result["custom"], 7)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_malformed_queue_shapes_fail_closed_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = root / "projects"
            projects.mkdir()
            path = projects / "production_queue.json"
            for original in ({"items": "not-a-list"}, {"items": ["../outside", None]}):
                path.write_text(json.dumps(original), encoding="utf-8")
                helpers = load_state_helpers(projects, root / "worlds")
                self.assertEqual(helpers["load_queue"](), {"version": "53.0", "items": []})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_save_queue_rejects_bad_shapes_before_touching_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = root / "projects"
            projects.mkdir()
            path = projects / "production_queue.json"
            original = '{"version":"old","items":[{"keep":true}]}'
            path.write_text(original, encoding="utf-8")
            helpers = load_state_helpers(projects, root / "worlds")
            for invalid in (None, [], {"items": "bad"}, {"items": [None]}, {"items": [{"project": "Nightmare Cryptids"}]}, {"items": ["../outside"]}, {"items": [""]}):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        helpers["save_queue"](invalid)
                    self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_world_index_malformed_registry_falls_back_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worlds = root / "worlds"
            worlds.mkdir()
            path = worlds / "world_index.json"
            original = {"version": 2, "engine_version": "1.1", "worlds": "not-a-map"}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", worlds)
            result = helpers["load_world_index"]()
            self.assertEqual(result["worlds"], {})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_valid_queue_save_writes_versioned_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = root / "projects"
            projects.mkdir()
            helpers = load_state_helpers(projects, root / "worlds")
            project = projects / "Nightmare Cryptids"
            project.mkdir()
            queue = {"items": [str(project)], "custom": True}
            helpers["save_queue"](queue)
            saved = json.loads((projects / "production_queue.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], "53.0")
            self.assertEqual(saved["items"], queue["items"])
            self.assertTrue(saved["custom"])
            self.assertNotIn("version", queue)



    def test_build_state_filters_malformed_image_records_in_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_state.json"
            original = {"images": {"good.png": {"hash": "abc"}, "bad.png": "not-a-record", "bad-key": None}}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            result = helpers["load_build_state"](project)
            self.assertEqual(result["images"], {"good.png": {"hash": "abc"}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_save_build_state_rejects_bad_nested_shape_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_state.json"
            original = '{"images":{"keep":{"hash":"old"}}}'
            path.write_text(original, encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            invalid_values = (None, [], {"images": []}, {"images": {"bad": "not-a-record"}}, {"images": {}, "last_build": "bad"})
            for invalid in invalid_values:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        helpers["save_build_state"](project, invalid)
                    self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_build_history_filters_non_object_entries_in_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            path = project / "build_history.json"
            original = {"builds": [{"status": "PASS"}, None, "bad", {"status": "REVIEW"}]}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", root / "worlds")
            result = helpers["load_build_history"](project)
            self.assertEqual(result["builds"], [{"status": "PASS"}, {"status": "REVIEW"}])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_world_index_filters_invalid_entries_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worlds = root / "worlds"
            worlds.mkdir()
            path = worlds / "world_index.json"
            original = {"worlds": {"good": {"world_id": "good"}, "bad": None, "mismatch": {"world_id": "other"}}}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", worlds)
            result = helpers["load_world_index"]()
            self.assertEqual(result["worlds"], {"good": {"world_id": "good"}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_save_world_index_rejects_bad_registry_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worlds = root / "worlds"
            worlds.mkdir()
            path = worlds / "world_index.json"
            original = '{"worlds":{"keep":{"world_id":"keep"}}}'
            path.write_text(original, encoding="utf-8")
            helpers = load_state_helpers(root / "projects", worlds)
            invalid_values = (None, [], {"worlds": []}, {"worlds": {"bad": None}}, {"worlds": {"a": {"world_id": "b"}}})
            for invalid in invalid_values:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        helpers["save_world_index"](invalid)
                    self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_world_path_rejects_path_traversal_inputs(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "world_path")
        namespace = {"Path": Path, "WORLDS_DIR": Path("worlds")}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
        for value in ("../outside", "..", "/tmp/outside", r"..\\outside", "C:\\outside"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    namespace["world_path"](value)
        self.assertEqual(namespace["world_path"]("Nightmare World (2)"), Path("worlds") / "Nightmare World (2)")

    def test_world_loader_falls_back_for_bad_collections_and_rejects_id_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worlds = root / "worlds"
            folder = worlds / "Nightmare World"
            folder.mkdir(parents=True)
            path = folder / "world.json"
            original = {"world_id": "Nightmare World", "series": "bad", "books": [{"title": "kept"}], "relationships": None}
            path.write_text(json.dumps(original), encoding="utf-8")
            helpers = load_state_helpers(root / "projects", worlds)
            result = helpers["load_world"]("Nightmare World")
            self.assertEqual(result["series"], [])
            self.assertEqual(result["relationships"], [])
            self.assertEqual(result["books"], [{"title": "kept"}])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
            path.write_text(json.dumps({"world_id": "other", "books": []}), encoding="utf-8")
            self.assertIsNone(helpers["load_world"]("Nightmare World"))

    def test_save_world_rejects_malformed_collections_before_write(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        names = {"save_world", "load_world_index", "save_world_index", "world_path"}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = {"Path": Path, "WORLDS_DIR": Path("worlds"), "WORLD_INDEX_FILENAME": "world_index.json",
                     "WORLD_SCHEMA_VERSION": 2, "WORLD_ENGINE_VERSION": "1.1", "FACTORY_VERSION": "53.0",
                     "datetime": __import__("datetime").datetime, "load_world_index": lambda: {"worlds": {}},
                     "save_json": lambda path, payload: Path(path).write_text(json.dumps(payload), encoding="utf-8")}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            namespace["WORLDS_DIR"] = root / "worlds"
            namespace["world_path"] = lambda world_id: root / "worlds" / str(world_id)
            for invalid in (None, {"world_id": "world", "books": "bad"}, {"world_id": "world", "relationships": None}):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        namespace["save_world"](invalid)
            self.assertFalse((root / "worlds" / "world" / "world.json").exists())



    def test_queue_accepts_project_paths_and_rejects_outside_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = root / "projects"
            projects.mkdir()
            project = projects / "Nightmare Cryptids"
            project.mkdir()
            path = projects / "production_queue.json"
            valid = {"version": "legacy", "items": [str(project)]}
            path.write_text(json.dumps(valid), encoding="utf-8")
            helpers = load_state_helpers(projects, root / "worlds")
            self.assertEqual(helpers["load_queue"]()["items"], [str(project)])
            invalid = {"version": "legacy", "items": [str(root / "outside")]}
            path.write_text(json.dumps(invalid), encoding="utf-8")
            self.assertEqual(helpers["load_queue"](), {"version": "53.0", "items": []})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
