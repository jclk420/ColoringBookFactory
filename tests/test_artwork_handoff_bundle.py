"""Regression tests for the v73-v77 artwork handoff and assembly gate."""
import ast
import hashlib
import json
import re
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v73_prompt_lore_continuity_audit",
    "v74_export_prompt_generation_batch",
    "v75_artwork_intake_preview",
    "v76_assembly_readiness_gate",
    "v77_run_artwork_handoff_workflow",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing artwork handoff helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "zipfile": zipfile, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class ArtworkHandoffBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "82.0",
            "BOOK_BLUEPRINT_FILENAME": "BOOK_BLUEPRINT.json",
            "PROMPT_MANIFEST_FILENAME": "PROMPT_MANIFEST.json",
            "ARTWORK_QUEUE_FILENAME": "ARTWORK_QUEUE.json",
            "ARTWORK_QUEUE_DIRNAME": "ARTWORK_QUEUE",
            "ARTWORK_PROMPTS_DIRNAME": "PROMPTS",
            "ARTWORK_SOURCE_DIRNAME": "SOURCE",
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

    def write_context(self, *, world_id="WORLD-1", image_id="IMG-001", queue_status="READY", approved_file=""):
        blueprint = {
            "title": "Mutant Fish Apocalypse", "image_count": 1,
            "world": {"attached": True, "world_id": world_id, "name": "Flooded World"},
            "primary_location": {"attached": True, "id": "LOC-1", "name": "Sunken City"},
            "series": {"attached": True, "series_id": "SERIES-1", "name": "Abyssal Files"},
        }
        record = {
            "image_id": image_id, "title": "Mutant Fish", "world_id": world_id,
            "world_name": "Flooded World", "location_id": "LOC-1",
            "location_name": "Sunken City", "series_id": "SERIES-1",
            "series_name": "Abyssal Files", "prompt": "A mutant fish in black line art",
            "negative_prompt": "no color, no shading",
        }
        (self.project / "BOOK_BLUEPRINT.json").write_text(json.dumps(blueprint), encoding="utf-8")
        (self.project / "PROMPT_MANIFEST.json").write_text(json.dumps({
            "book_title": blueprint["title"], "world_id": world_id,
            "primary_location_id": "LOC-1", "images": [record]
        }), encoding="utf-8")
        (self.project / "ARTWORK_QUEUE.json").write_text(json.dumps({
            "jobs": [{"image_id": image_id, "status": queue_status, "approved_file": approved_file}]
        }), encoding="utf-8")
        prompt_dir = self.project / "ARTWORK_QUEUE" / "PROMPTS"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / f"{image_id}.txt").write_text(
            f"TITLE: Mutant Fish\nIMAGE ID: {image_id}\n\nPROMPT:\n{record['prompt']}\n"
            f"\nNEGATIVE PROMPT:\n{record['negative_prompt']}\n",
            encoding="utf-8"
        )

    def test_prompt_lore_continuity_passes_and_blocks_conflicting_world_id(self):
        self.write_context()
        result = self.ns["v73_prompt_lore_continuity_audit"](self.project)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checked_prompts"], 1)
        manifest = json.loads((self.project / "PROMPT_MANIFEST.json").read_text(encoding="utf-8"))
        manifest["images"][0]["world_id"] = "WRONG-WORLD"
        (self.project / "PROMPT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = self.ns["v73_prompt_lore_continuity_audit"](self.project)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("world_id differs" in error for error in result["errors"]))

    def test_prompt_batch_export_contains_prompts_and_manifest_not_artwork(self):
        self.write_context()
        continuity = {"status": "PASS"}
        handoff = {"status": "READY"}
        result = self.ns["v74_export_prompt_generation_batch"](self.project, continuity, handoff)
        self.assertEqual(result["status"], "EXPORTED_FOR_GENERATION")
        self.assertFalse(result["uploaded"])
        self.assertEqual(result["prompt_count"], 1)
        with zipfile.ZipFile(result["path"], "r") as archive:
            self.assertIn("PROMPTS/IMG-001.txt", archive.namelist())
            self.assertIn("PROMPT_HANDOFF_MANIFEST.json", archive.namelist())
            self.assertNotIn("IMG-001.png", archive.namelist())
        result2 = self.ns["v74_export_prompt_generation_batch"](self.project, continuity, handoff)
        self.assertNotEqual(result["path"], result2["path"])

    def test_prompt_batch_export_is_withheld_when_continuity_fails(self):
        self.write_context()
        result = self.ns["v74_export_prompt_generation_batch"](
            self.project, {"status": "BLOCKED"}, {"status": "READY"}
        )
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["exported"])
        self.assertFalse(list((self.project / "ARTWORK_QUEUE").glob("EXPORTS/*.zip")))

    def test_artwork_intake_preview_matches_stable_ids_without_copying(self):
        self.write_context()
        external = self.root / "generated"
        external.mkdir()
        (external / "IMG-001.png").write_bytes(b"generated-art")
        result = self.ns["v75_artwork_intake_preview"](self.project, external)
        self.assertEqual(result["status"], "READY_FOR_EXPLICIT_IMPORT")
        self.assertEqual(result["matches"][0]["image_id"], "IMG-001")
        self.assertFalse(result["copies_performed"])
        self.assertFalse((self.project / "ARTWORK_QUEUE" / "SOURCE" / "IMG-001.png").exists())

    def test_artwork_intake_preview_blocks_one_file_matching_multiple_ids(self):
        self.write_context()
        queue = {"jobs": [
            {"image_id": "IMG-001", "status": "READY"},
            {"image_id": "IMG-002", "status": "READY"},
        ]}
        (self.project / "ARTWORK_QUEUE.json").write_text(json.dumps(queue), encoding="utf-8")
        external = self.root / "generated"
        external.mkdir()
        (external / "IMG-001_IMG-002.png").write_bytes(b"ambiguous-art")
        result = self.ns["v75_artwork_intake_preview"](self.project, external)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["ambiguous_ids"])
        self.assertFalse(result["copies_performed"])

    def test_assembly_gate_requires_every_job_to_pass_with_project_local_approved_art(self):
        approved = self.project / "ARTWORK_QUEUE" / "APPROVED" / "IMG-001.png"
        approved.parent.mkdir(parents=True)
        approved.write_bytes(b"approved-art")
        self.write_context(queue_status="PASS", approved_file=str(approved))
        result = self.ns["v76_assembly_readiness_gate"](self.project)
        self.assertEqual(result["status"], "READY_FOR_ASSEMBLY")
        self.assertFalse(result["assembly_started"])
        queue = json.loads((self.project / "ARTWORK_QUEUE.json").read_text(encoding="utf-8"))
        queue["jobs"][0]["status"] = "REVIEW"
        (self.project / "ARTWORK_QUEUE.json").write_text(json.dumps(queue), encoding="utf-8")
        result = self.ns["v76_assembly_readiness_gate"](self.project)
        self.assertEqual(result["status"], "BLOCKED")

    def test_one_click_handoff_orchestrator_does_not_copy_build_or_publish(self):
        calls = []
        self.ns.update({
            "v73_prompt_lore_continuity_audit": lambda project: calls.append("continuity") or {"status": "PASS", "errors": [], "warnings": []},
            "v70_prompt_handoff_audit": lambda project: calls.append("handoff") or {"status": "READY", "missing_prompt_files": [], "stale_prompt_files": []},
            "v74_export_prompt_generation_batch": lambda *args: calls.append("export") or {"status": "EXPORTED_FOR_GENERATION", "path": "prompt.zip"},
            "v75_artwork_intake_preview": lambda *args: calls.append("intake") or {"status": "READY_FOR_EXPLICIT_IMPORT", "errors": [], "missing_ids": []},
            "v76_assembly_readiness_gate": lambda project: calls.append("assembly") or {"status": "READY_FOR_ASSEMBLY", "errors": [], "warnings": []},
        })
        result = self.ns["v77_run_artwork_handoff_workflow"](self.project, self.root)
        self.assertEqual(calls, ["continuity", "handoff", "export", "intake", "assembly"])
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["canon_modified"])
        self.assertFalse(result["source_artwork_copied"])
        self.assertFalse(result["assembly_started"])
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["published"])

    def test_version_and_menu_wiring(self):
        self.assertIn('FACTORY_VERSION = "82.0"', self.source)
        self.assertIn('26. Artwork Generation Handoff & Assembly Gate', self.source)
        self.assertIn('elif c=="26": v77_artwork_handoff_menu()', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
