"""Regression tests for non-destructive lore registry write guards."""
import ast
import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"
HELPERS = {
    "load_json", "save_json", "lore_safe_registry_id", "world_path", "series_path",
    "load_world", "save_world", "load_world_index", "save_world_index",
    "load_series_bible", "save_series_bible",
}


def load_registry_helpers(root):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in HELPERS]
    names = [node.name for node in functions]
    if set(names) != HELPERS or len(names) != len(HELPERS):
        raise AssertionError("Each registry helper must be defined exactly once")
    namespace = {
        "Path": Path, "json": json, "os": os, "tempfile": tempfile,
        "datetime": datetime.datetime,
        "FACTORY_VERSION": "52.0",
        "WORLD_SCHEMA_VERSION": 2, "WORLD_ENGINE_VERSION": "1.1",
        "WORLD_INDEX_FILENAME": "world_index.json",
        "SERIES_ENGINE_VERSION": "1.0", "SERIES_BIBLE_FILENAME": "SERIES_BIBLE.json",
        "WORLDS_DIR": root / "Worlds", "SERIES_DIR": root / "Series",
        "lore_write_series_markdown": lambda bible: None,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class CanonWriteGuardTests(unittest.TestCase):
    def test_registry_paths_reject_traversal_and_absolute_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            helpers = load_registry_helpers(Path(temp))
            for bad in ("../outside", "..", "folder/name", r"folder\name", r"C:\outside"):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        helpers["world_path"](bad)
                    with self.assertRaises(ValueError):
                        helpers["series_path"](bad)

    def test_invalid_world_payloads_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            for world in ([], {"world_id": "../outside"}, {"world_id": "test-world", "books": "bad"}):
                with self.subTest(world=world):
                    with self.assertRaises(ValueError):
                        helpers["save_world"](world)
            self.assertFalse((root / "Worlds" / "test-world" / "world.json").exists())

    def test_invalid_series_bible_payloads_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            for bible in ([], {"series_id": "../outside"}, {"series_id": "nightmare", "books": "bad"}):
                with self.subTest(bible=bible):
                    with self.assertRaises(ValueError):
                        helpers["save_series_bible"](bible)
            self.assertFalse((root / "Series" / "nightmare" / "SERIES_BIBLE.json").exists())

    def test_world_index_save_rejects_bad_payloads_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            for index in ([], {"worlds": "bad"}, {"worlds": {"../escape": {"name": "bad"}}},
                          {"worlds": {"valid": None}}):
                with self.subTest(index=index):
                    with self.assertRaises(ValueError):
                        helpers["save_world_index"](index)
            self.assertFalse((root / "Worlds" / "world_index.json").exists())

    def test_malformed_world_collections_are_guarded_in_memory_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            folder = root / "Worlds" / "nightmare-world"
            folder.mkdir(parents=True)
            path = folder / "world.json"
            original = {"world_id": "nightmare-world", "series": "bad", "relationships": [], "books": []}
            path.write_text(json.dumps(original), encoding="utf-8")
            world = helpers["load_world"]("nightmare-world")
            self.assertEqual(world["series"], [])
            self.assertIn("series", world["_load_validation_errors"])
            with self.assertRaises(ValueError):
                helpers["save_world"](world)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_malformed_series_books_are_guarded_in_memory_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            folder = root / "Series" / "nightmare-series"
            folder.mkdir(parents=True)
            path = folder / "SERIES_BIBLE.json"
            original = {"series_id": "nightmare-series", "books": "bad", "custom": True}
            path.write_text(json.dumps(original), encoding="utf-8")
            bible = helpers["load_series_bible"]("nightmare-series")
            self.assertEqual(bible["books"], [])
            self.assertIn("books", bible["_load_validation_errors"])
            with self.assertRaises(ValueError):
                helpers["save_series_bible"](bible)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_malformed_world_index_blocks_world_save_before_partial_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            worlds = root / "Worlds"
            worlds.mkdir()
            path = worlds / "world_index.json"
            original = {"version": 2, "engine_version": "1.1", "worlds": "bad"}
            path.write_text(json.dumps(original), encoding="utf-8")
            index = helpers["load_world_index"]()
            self.assertTrue(index.get("_load_validation_errors"))
            with self.assertRaises(ValueError):
                helpers["save_world"]({"world_id": "new-world", "name": "New World", "books": []})
            self.assertFalse((worlds / "new-world" / "world.json").exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_valid_world_and_series_saves_still_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = load_registry_helpers(root)
            world = {"world_id": "nightmare-world", "name": "Nightmare World",
                     "series": [], "relationships": [], "books": []}
            helpers["save_world"](world)
            self.assertTrue((root / "Worlds" / "nightmare-world" / "world.json").exists())
            self.assertTrue((root / "Worlds" / "world_index.json").exists())
            bible = {"series_id": "nightmare-series", "series_name": "Nightmare Series", "books": []}
            helpers["save_series_bible"](bible)
            self.assertTrue((root / "Series" / "nightmare-series" / "SERIES_BIBLE.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
