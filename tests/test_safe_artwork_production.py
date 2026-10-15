"""Regression tests for the v83-v87 safe artwork import and production workflow."""
import ast
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v83_backup_assembly_input",
    "v84_import_previewed_artwork",
    "v85_assembly_input_preview",
    "v86_production_action_plan",
    "v87_guided_artwork_production_workflow",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing safe production helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class SafeArtworkProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "97.0",
            "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".webp"},
            "ARTWORK_QUEUE_DIRNAME": "ARTWORK_QUEUE",
            "ARTWORK_SOURCE_DIRNAME": "SOURCE",
            "ARTWORK_QUEUE_FILENAME": "ARTWORK_QUEUE.json",
            "ARTWORK_QA_FILENAME": "ARTWORK_QA.json",
            "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "cb13_validate_artwork_file": lambda path: ([], [], {"width": 2550, "height": 3300, "mode": "RGB"}),
        })

        def load_json(path):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.ns.update({"load_json": load_json, "save_json": save_json})

    def test_assembly_input_backup_verifies_existing_files_before_replacement(self):
        input_dir = self.project / "INPUT"
        input_dir.mkdir()
        original = input_dir / "old-art.png"
        original.write_bytes(b"important old art")
        result = self.ns["v83_backup_assembly_input"](self.project, input_dir)
        self.assertEqual(result["status"], "BACKUP_VERIFIED")
        self.assertTrue(result["deletion_authorized"])
        self.assertTrue(original.is_file())
        backup = Path(result["files"][0]["backup"])
        self.assertEqual(backup.read_bytes(), b"important old art")
        self.assertEqual(result["files"][0]["sha256"], hashlib.sha256(original.read_bytes()).hexdigest())

    def test_import_requires_confirmation_and_never_overwrites_existing_source(self):
        external = self.root / "generated"
        external.mkdir()
        source = external / "IMG-001.png"
        source.write_bytes(b"new generated art")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        preview = {"status": "READY_FOR_EXPLICIT_IMPORT", "source_folder": str(external),
                   "matches": [{"image_id": "IMG-001", "source_file": str(source), "sha256": digest}]}
        denied = self.ns["v84_import_previewed_artwork"](self.project, preview, confirm=False)
        self.assertEqual(denied["status"], "CONFIRMATION_REQUIRED")
        target = self.project / "ARTWORK_QUEUE" / "SOURCE" / "IMG-001.png"
        self.assertFalse(target.exists())
        imported = self.ns["v84_import_previewed_artwork"](self.project, preview, confirm=True)
        self.assertEqual(imported["status"], "IMPORTED")
        self.assertEqual(target.read_bytes(), b"new generated art")
        target.write_bytes(b"pre-existing source")
        blocked = self.ns["v84_import_previewed_artwork"](self.project, preview, confirm=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(target.read_bytes(), b"pre-existing source")

    def test_import_rejects_source_changed_after_preview(self):
        external = self.root / "generated"
        external.mkdir()
        source = external / "IMG-001.png"
        source.write_bytes(b"original")
        preview = {"status": "READY_FOR_EXPLICIT_IMPORT", "source_folder": str(external),
                   "matches": [{"image_id": "IMG-001", "source_file": str(source),
                                "sha256": hashlib.sha256(b"old hash").hexdigest()}]}
        result = self.ns["v84_import_previewed_artwork"](self.project, preview, confirm=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse((self.project / "ARTWORK_QUEUE" / "SOURCE" / "IMG-001.png").exists())

    def test_assembly_input_preview_reports_existing_input_replacement(self):
        approved = self.project / "ARTWORK_QUEUE" / "APPROVED" / "IMG-001.png"
        approved.parent.mkdir(parents=True)
        approved.write_bytes(b"approved")
        (self.project / "ARTWORK_QUEUE.json").write_text(json.dumps({
            "jobs": [{"image_id": "IMG-001", "status": "PASS", "approved_file": str(approved)}]
        }), encoding="utf-8")
        input_dir = self.project / "INPUT"
        input_dir.mkdir()
        (input_dir / "legacy.png").write_bytes(b"legacy")
        self.ns["v76_assembly_readiness_gate"] = lambda project: {"status": "READY_FOR_ASSEMBLY", "errors": [], "warnings": []}
        result = self.ns["v85_assembly_input_preview"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(len(result["existing_input_images"]), 1)
        self.assertTrue(any("backup" in warning for warning in result["warnings"]))
        self.assertTrue((input_dir / "legacy.png").is_file())

    def test_production_action_plan_prioritizes_blocked_assembly(self):
        plan = self.ns["v86_production_action_plan"](self.project,
            {"status": "IMPORTED", "errors": []},
            {"status": "PASS", "summary": {}},
            {"status": "BLOCKED", "errors": ["Approved art missing"]},
            {"status": "NEEDS_REVIEW", "warnings": ["Existing INPUT art"]})
        self.assertGreaterEqual(plan["priority_counts"]["P0"], 1)
        self.assertGreaterEqual(plan["priority_counts"]["P1"], 1)
        self.assertEqual(plan["tasks"][0]["priority"], "P0")

    def test_guided_workflow_imports_then_runs_qa_and_does_not_build_or_publish(self):
        calls = []
        self.ns.update({
            "v84_import_previewed_artwork": lambda project, preview=None, confirm=False: calls.append("import") or {"status": "IMPORTED", "copied": True},
            "cb13_scan_artwork_qa": lambda project: calls.append("qa") or {"summary": {"failed": 0, "review": 0, "waiting": 0}},
            "v76_assembly_readiness_gate": lambda project: calls.append("gate") or {"status": "READY_FOR_ASSEMBLY", "errors": [], "warnings": []},
            "v85_assembly_input_preview": lambda project: calls.append("input-preview") or {"status": "READY", "errors": [], "warnings": []},
            "v86_production_action_plan": lambda *args: calls.append("plan") or {"task_count": 0},
        })
        result = self.ns["v87_guided_artwork_production_workflow"](self.project, {"status": "READY_FOR_EXPLICIT_IMPORT"}, confirm_import=True)
        self.assertEqual(calls, ["import", "qa", "gate", "input-preview", "plan"])
        self.assertEqual(result["status"], "READY_FOR_MANUAL_ASSEMBLY")
        self.assertTrue(result["source_artwork_copied"])
        self.assertFalse(result["assembly_started"])
        self.assertFalse(result["published"])
        self.assertFalse(result["uploaded"])

    def test_build_path_backs_up_input_before_deleting_existing_images(self):
        start = self.source.index('input_backup = v83_backup_assembly_input(project, input_dir)')
        delete = self.source.index('if old.is_file() and old.suffix.lower() in IMAGE_EXTENSIONS:', start)
        self.assertLess(start, delete)
        self.assertIn('if input_backup.get("status") == "BLOCKED":', self.source)

    def test_version_and_menu_wiring(self):
        self.assertIn('FACTORY_VERSION = "107.0"', self.source)
        self.assertIn('28. Safe Artwork Import & Guided Production', self.source)
        self.assertIn('elif c=="28": v87_safe_artwork_production_menu()', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
