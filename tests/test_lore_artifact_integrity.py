"""Runtime tests for read-only staged/OCR artifact integrity helpers."""
import ast
import hashlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_helper(name, namespace):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {name} helper")
    helper_names = {"lore_intake_resolve_recorded_path", "lore_intake_verify_artifact",
                    "lore_intake_audit_ocr_history", "lore_intake_next_ocr_page_start"}
    helpers = [node for node in tree.body
               if isinstance(node, ast.FunctionDef) and node.name in helper_names]
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace[name]


class LoreArtifactIntegrityTests(unittest.TestCase):
    def test_artifact_verifier_distinguishes_verified_missing_bad_hash_and_mismatch(self):
        namespace = {
            "Path": Path,
            "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        verify = load_helper("lore_intake_verify_artifact", namespace)
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "evidence.txt"
            artifact.write_text("page evidence\n", encoding="utf-8")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.assertEqual(verify(artifact, digest)["status"], "VERIFIED")
            self.assertEqual(verify(artifact, "not-a-hash")["status"], "INVALID_HASH")
            self.assertEqual(verify(artifact, "0" * 64)["status"], "HASH_MISMATCH")
            self.assertEqual(verify(Path(temp) / "missing.txt", digest)["status"], "MISSING")

    def test_ocr_history_validates_each_batch_and_detects_overlapping_ranges(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        audit = load_helper("lore_intake_audit_ocr_history", namespace)
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "INTAKE_BATCH.json"
            evidence = Path(temp) / "OCR_TEXT_P1.txt"
            evidence.write_text("page evidence\n", encoding="utf-8")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            metadata = {"ocr_batches": [
                {"text_path": str(evidence), "text_sha256": digest,
                 "page_start": 1, "page_limit": 10, "page_end_requested": 10},
                {"text_path": str(evidence), "text_sha256": digest,
                 "page_start": 11, "page_limit": 10, "page_end_requested": 20},
            ]}
            result = audit(metadata, report, ())
            self.assertEqual(result["integrity"], "VERIFIED")
            self.assertEqual(result["page_ranges"], "1-10, 11-20")
            self.assertEqual(result["counts"]["ocr_text_hash_mismatches"], 0)
            metadata["ocr_batches"][1]["page_start"] = 10
            metadata["ocr_batches"][1]["page_end_requested"] = 19
            overlap = audit(metadata, report, ())
            self.assertEqual(overlap["counts"]["overlapping_ocr_page_ranges"], 1)

    def test_next_ocr_start_uses_highest_saved_range(self):
        namespace = {"Path": Path}
        next_start = load_helper("lore_intake_next_ocr_page_start", namespace)
        self.assertEqual(next_start({}), 1)
        self.assertEqual(next_start({"ocr_batches": [
            {"page_start": 1, "page_limit": 10, "page_end_requested": 10},
            {"page_start": 11, "page_limit": 10, "page_end_requested": 20},
        ]}), 21)

    def test_relative_artifact_paths_resolve_beside_the_report_first(self):
        namespace = {"Path": Path}
        resolve = load_helper("lore_intake_resolve_recorded_path", namespace)
        with tempfile.TemporaryDirectory() as temp:
            report_dir = Path(temp) / "Batches" / "batch_01"
            report_dir.mkdir(parents=True)
            artifact = report_dir / "OCR_TEXT_P1.txt"
            artifact.write_text("evidence", encoding="utf-8")
            resolved = resolve("OCR_TEXT_P1.txt", report_dir / "INTAKE_BATCH.json", ())
            self.assertEqual(resolved, artifact.resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
