"""Regression tests for the v68-v72 creation and artwork quality bundle."""
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
    "v68_creation_readiness_audit",
    "v69_artwork_integrity_audit",
    "v70_prompt_handoff_audit",
    "v71_creation_action_plan",
    "v72_run_creation_quality_workflow",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing creation quality helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class CreationQualityBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "72.0",
            "BOOK_BLUEPRINT_FILENAME": "BOOK_BLUEPRINT.json",
            "PROMPT_MANIFEST_FILENAME": "PROMPT_MANIFEST.json",
            "ARTWORK_QUEUE_FILENAME": "ARTWORK_QUEUE.json",
            "ARTWORK_QUEUE_DIRNAME": "ARTWORK_QUEUE",
            "ARTWORK_SOURCE_DIRNAME": "SOURCE",
            "ARTWORK_APPROVED_DIRNAME": "APPROVED",
            "ARTWORK_REVIEW_DIRNAME": "REVIEW",
            "ARTWORK_FAILED_DIRNAME": "FAILED",
            "ARTWORK_PROMPTS_DIRNAME": "PROMPTS",
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

    def write_creation_files(self, *, image_count=1, prompts=None, jobs=None, world=None, series=None):
        prompts = prompts if prompts is not None else [{
            "image_id": "IMG-001", "title": "Mutant Fish", "prompt": "A detailed mutant fish",
            "negative_prompt": "color, shading"
        }]
        jobs = jobs if jobs is not None else [{"image_id": "IMG-001", "status": "READY", "approved_file": ""}]
        blueprint = {
            "title": "Mutant Fish Apocalypse", "image_count": image_count,
            "world": world if world is not None else {"attached": False, "world_id": ""},
            "series": series if series is not None else {"attached": False, "series_id": ""},
        }
        (self.project / "BOOK_BLUEPRINT.json").write_text(json.dumps(blueprint), encoding="utf-8")
        (self.project / "PROMPT_MANIFEST.json").write_text(json.dumps({"images": prompts}), encoding="utf-8")
        (self.project / "ARTWORK_QUEUE.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")

    def test_creation_readiness_passes_matching_blueprint_manifest_and_queue(self):
        self.write_creation_files()
        result = self.ns["v68_creation_readiness_audit"](self.project)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["expected_image_count"], 1)
        self.assertEqual(result["prompt_count"], 1)
        self.assertEqual(result["queue_job_count"], 1)
        self.assertTrue(result["read_only"])
        self.assertTrue((self.project / "REPORTS" / "CREATION_READINESS.json").is_file())

    def test_creation_readiness_blocks_duplicate_ids_and_count_mismatch(self):
        prompts = [
            {"image_id": "IMG-001", "prompt": "one", "negative_prompt": "none"},
            {"image_id": "IMG-001", "prompt": "two", "negative_prompt": "none"},
        ]
        self.write_creation_files(image_count=3, prompts=prompts, jobs=[])
        result = self.ns["v68_creation_readiness_audit"](self.project)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("duplicate image_id" in error for error in result["errors"]))
        self.assertTrue(any("expects 3 images" in error for error in result["errors"]))

    def test_artwork_audit_ignores_lifecycle_copies_but_flags_duplicate_artwork_ids(self):
        root = self.project / "ARTWORK_QUEUE"
        source = root / "SOURCE"
        approved = root / "APPROVED"
        source.mkdir(parents=True)
        approved.mkdir(parents=True)
        (root / "REVIEW").mkdir()
        (root / "FAILED").mkdir()
        (source / "IMG-001.png").write_bytes(b"same image bytes")
        (approved / "IMG-001.png").write_bytes(b"same image bytes")
        (source / "IMG-002.png").write_bytes(b"same image bytes")
        self.write_creation_files(jobs=[
            {"image_id": "IMG-001", "status": "PASS", "approved_file": str(self.project / "missing.png")}
        ])
        result = self.ns["v69_artwork_integrity_audit"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(len(result["duplicate_hashes"]), 1)
        self.assertTrue(any("missing approved file" in warning for warning in result["warnings"]))
        self.assertTrue(result["read_only"])

    def test_prompt_handoff_audit_detects_missing_and_stale_exports_without_rewriting(self):
        self.write_creation_files()
        prompt_dir = self.project / "ARTWORK_QUEUE" / "PROMPTS"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "IMG-001.txt").write_text(
            "TITLE: Mutant Fish\nIMAGE ID: IMG-001\n\nPROMPT:\nold prompt\n\nNEGATIVE PROMPT:\ncolor, shading\n",
            encoding="utf-8"
        )
        before = (prompt_dir / "IMG-001.txt").read_bytes()
        result = self.ns["v70_prompt_handoff_audit"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["stale_count"], 1)
        self.assertEqual((prompt_dir / "IMG-001.txt").read_bytes(), before)
        self.assertFalse(result["missing_prompt_files"])

    def test_prompt_handoff_flags_unsafe_ids_as_malformed(self):
        self.write_creation_files(prompts=[{
            "image_id": "../outside", "prompt": "prompt", "negative_prompt": "none"
        }], jobs=[])
        result = self.ns["v70_prompt_handoff_audit"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["malformed_records"], ["../outside"])

    def test_action_plan_prioritizes_blockers_and_stale_prompt_exports(self):
        plan = self.ns["v71_creation_action_plan"](self.project,
            {"status": "BLOCKED", "errors": ["Blueprint mismatch"]},
            {"status": "NEEDS_REVIEW", "warnings": ["Duplicate image bytes"]},
            {"status": "NEEDS_REVIEW", "stale_prompt_files": [{"image_id": "IMG-001"}]})
        self.assertGreaterEqual(plan["priority_counts"]["P0"], 2)
        self.assertGreaterEqual(plan["priority_counts"]["P1"], 2)
        self.assertEqual(plan["tasks"][0]["priority"], "P0")

    def test_one_click_creation_quality_workflow_chains_reports_without_mutation_claims(self):
        calls = []
        self.ns.update({
            "v68_creation_readiness_audit": lambda project: calls.append("readiness") or {"status": "READY", "errors": [], "warnings": []},
            "v69_artwork_integrity_audit": lambda project: calls.append("artwork") or {"status": "NEEDS_REVIEW", "errors": [], "warnings": ["visual review"]},
            "v70_prompt_handoff_audit": lambda project: calls.append("prompts") or {"status": "READY", "errors": [], "warnings": []},
            "v71_creation_action_plan": lambda *args: calls.append("plan") or {"task_count": 1},
        })
        result = self.ns["v72_run_creation_quality_workflow"](self.project)
        self.assertEqual(calls, ["readiness", "artwork", "prompts", "plan"])
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["canon_modified"])
        self.assertFalse(result["prompt_files_modified"])
        self.assertFalse(result["artwork_files_modified"])
        self.assertTrue((self.project / "REPORTS" / "CREATION_QUALITY_SUMMARY.json").is_file())

    def test_version_menu_wiring_and_unique_definitions(self):
        self.assertIn('FACTORY_VERSION = "72.0"', self.source)
        self.assertIn('25. Creation & Artwork Quality Center', self.source)
        self.assertIn('elif c=="25": v72_creation_quality_menu()', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
