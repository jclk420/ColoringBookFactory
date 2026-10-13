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
    "load_queue", "save_queue", "load_world_index",
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
        "FACTORY_VERSION": "51.0",
        "BUILD_STATE_FILE": "build_state.json",
        "BUILD_HISTORY_FILENAME": "build_history.json",
        "PRODUCTION_QUEUE_FILENAME": "production_queue.json",
        "PROJECTS": projects,
        "WORLDS_DIR": worlds,
        "WORLD_INDEX_FILENAME": "world_index.json",
        "WORLD_SCHEMA_VERSION": 2,
        "WORLD_ENGINE_VERSION": "1.1",
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
            self.assertEqual(result, {"version": "51.0", "images": {}, "last_build": None})
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
            for original in ({"items": "not-a-list"}, {"items": [{"project": "ok"}, None]}):
                path.write_text(json.dumps(original), encoding="utf-8")
                helpers = load_state_helpers(projects, root / "worlds")
                self.assertEqual(helpers["load_queue"](), {"version": "51.0", "items": []})
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
            for invalid in (None, [], {"items": "bad"}, {"items": [None]}):
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
            queue = {"items": [{"project": "Nightmare Cryptids"}], "custom": True}
            helpers["save_queue"](queue)
            saved = json.loads((projects / "production_queue.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], "51.0")
            self.assertEqual(saved["items"], queue["items"])
            self.assertTrue(saved["custom"])
            self.assertNotIn("version", queue)


if __name__ == "__main__":
    unittest.main(verbosity=2)
