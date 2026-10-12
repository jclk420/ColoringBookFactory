"""Runtime tests for the staged lore-intake copy-and-manifest workflow."""
import ast
import datetime as datetime_module
import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_intake_runner(namespace):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_run"
    ]
    if len(matches) != 1:
        raise AssertionError("lore_intake_run must have exactly one definition")
    module = ast.Module(body=[matches[0]], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace["lore_intake_run"]


class LoreIntakeRuntimeTests(unittest.TestCase):
    def test_intake_copies_supported_files_records_duplicates_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            intake_root = root / "INTAKE"
            source_a = root / "cryptid.png"
            source_b = root / "cryptid-copy.png"
            unsupported = root / "notes.txt"
            payload = b"same-image-content"
            source_a.write_bytes(payload)
            source_b.write_bytes(payload)
            unsupported.write_text("not supported", encoding="utf-8")
            original_a = source_a.read_bytes()
            original_b = source_b.read_bytes()

            class FixedDateTime:
                @staticmethod
                def now():
                    return datetime_module.datetime(2026, 10, 12, 12, 0, 1)

            def save_json(path, value):
                path = pathlib.Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, indent=2), encoding="utf-8")

            def load_json(path):
                return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

            namespace = {
                "Path": pathlib.Path,
                "datetime": FixedDateTime,
                "shutil": shutil,
                "json": json,
                "INTAKE_SUPPORTED_EXTENSIONS": {".pdf", ".png", ".jpg", ".jpeg", ".webp"},
                "INTAKE_DIR": intake_root,
                "INTAKE_MANIFEST_FILENAME": "manifest.json",
                "lore_intake_select_files": lambda: [],
                "lore_intake_collect_records": lambda: [],
                "lore_intake_sha256": lambda path: hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),
                "lore_intake_existing_hashes": lambda path: {},
                "lore_intake_inspect_file": lambda path: {"kind": "image", "text_preview": ""},
                "lore_intake_classify": lambda path, records, metadata: {
                    "kind": "creature", "name": "Unassigned Creature",
                    "world": "Unassigned World", "location": "Unassigned Location",
                    "confidence": "LOW", "matched_in": [],
                },
                "lore_intake_review_evidence": lambda path, records, metadata: {
                    "extracted_entity_candidates": [], "extracted_relationships": [],
                },
                "lore_intake_destination": lambda review_root, source, classification: pathlib.Path(review_root) / pathlib.Path(source).name,
                "save_json": save_json,
                "load_json": load_json,
                "FACTORY_VERSION": "30.0",
            }
            runner = load_intake_runner(namespace)
            result = runner([source_a, source_b, unsupported])

            self.assertEqual([item["status"] for item in result["items"]],
                             ["STAGED_FOR_REVIEW", "DUPLICATE_IN_BATCH"])
            self.assertEqual(result["rejected"][0]["reason"], "Unsupported file type")
            self.assertEqual(source_a.read_bytes(), original_a)
            self.assertEqual(source_b.read_bytes(), original_b)
            staged = pathlib.Path(result["items"][0]["staged_path"])
            self.assertTrue(staged.is_file())
            self.assertEqual(staged.read_bytes(), payload)
            batch_report = pathlib.Path(result["batch_report"])
            self.assertTrue(batch_report.is_file())
            report = json.loads(batch_report.read_text(encoding="utf-8"))
            self.assertEqual(report["items"][0]["status"], "STAGED_FOR_REVIEW")
            manifest = json.loads((intake_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["batches"]), 1)
            self.assertFalse(report.get("canon_written", False))


if __name__ == "__main__":
    unittest.main()
