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
                    "lore_intake_audit_ocr_history", "lore_intake_next_ocr_page_start",
                    "lore_intake_validate_ocr_source", "lore_intake_write_text_atomic"}
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

    def test_ocr_source_guard_rejects_changed_selected_or_staged_files(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        validate = load_helper("lore_intake_validate_ocr_source", namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            staged = root / "staged.pdf"
            report = root / "INTAKE_BATCH.json"
            payload = b"original-intake-bytes"
            source.write_bytes(payload)
            staged.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            item = {"sha256": digest, "staged_path": str(staged)}
            self.assertEqual(validate(source, item, report, (root,))["status"], "VERIFIED")
            staged.write_bytes(b"changed-staged-copy")
            self.assertEqual(validate(source, item, report, (root,))["status"], "STAGED_HASH_MISMATCH")
            staged.write_bytes(payload)
            source.write_bytes(b"changed-selected-source")
            self.assertEqual(validate(source, item, report, (root,))["status"], "SELECTED_HASH_MISMATCH")

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
            evidence2 = Path(temp) / "OCR_TEXT_P11.txt"
            evidence2.write_text("second batch evidence\n", encoding="utf-8")
            digest2 = hashlib.sha256(evidence2.read_bytes()).hexdigest()
            metadata = {"ocr_batches": [
                {"text_path": str(evidence), "text_sha256": digest,
                 "page_start": 1, "page_limit": 10, "page_end_requested": 10},
                {"text_path": str(evidence2), "text_sha256": digest2,
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

    def test_ocr_text_writer_never_overwrites_existing_evidence(self):
        namespace = {"Path": Path, "tempfile": tempfile, "os": __import__("os")}
        writer = load_helper("lore_intake_write_text_atomic", namespace)
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / "existing.txt"
            existing.write_text("original evidence\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                writer(existing, "replacement evidence")
            self.assertEqual(existing.read_text(encoding="utf-8"), "original evidence\n")
            fresh = Path(temp) / "fresh.txt"
            writer(fresh, "new evidence")
            self.assertEqual(fresh.read_text(encoding="utf-8"), "new evidence\n")

    def test_next_ocr_start_uses_highest_saved_range(self):
        namespace = {"Path": Path}
        next_start = load_helper("lore_intake_next_ocr_page_start", namespace)
        self.assertEqual(next_start({}), 1)
        self.assertEqual(next_start({"ocr_page_start": 1, "ocr_page_limit": 10,
                                     "ocr_page_end_requested": 10}), 11)
        self.assertEqual(next_start({"ocr_batches": [
            {"page_start": 1, "page_limit": 10, "page_end_requested": 10},
            {"page_start": 11, "page_limit": 10, "page_end_requested": 20},
        ]}), 21)
        self.assertEqual(next_start({"ocr_page_start": 1, "ocr_page_limit": 10,
                                     "ocr_page_end_requested": 999}), 1)

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


    def test_ocr_history_flags_reused_and_out_of_root_evidence_paths(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        audit = load_helper("lore_intake_audit_ocr_history", namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report_dir = root / "batch"
            report_dir.mkdir()
            report = report_dir / "INTAKE_BATCH.json"
            evidence = report_dir / "OCR_TEXT_P1.txt"
            evidence.write_text("verified evidence\\n", encoding="utf-8")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            outside_dir = root / "external"
            outside_dir.mkdir()
            outside = outside_dir / "OCR_TEXT_EXTERNAL.txt"
            outside.write_text("external evidence\\n", encoding="utf-8")
            outside_digest = hashlib.sha256(outside.read_bytes()).hexdigest()
            result = audit({"ocr_batches": [
                {"text_path": str(evidence), "text_sha256": digest,
                 "page_start": 1, "page_limit": 10, "page_end_requested": 10},
                {"text_path": str(evidence), "text_sha256": digest,
                 "page_start": 11, "page_limit": 10, "page_end_requested": 20},
                {"text_path": str(outside), "text_sha256": outside_digest,
                 "page_start": 21, "page_limit": 10, "page_end_requested": 30},
            ]}, report)
            self.assertEqual(result["counts"]["duplicate_ocr_text_paths"], 1)
            self.assertEqual(result["counts"]["ocr_text_paths_outside_roots"], 1)
            self.assertEqual(result["integrity"], "DUPLICATE_PATH")
            self.assertEqual(evidence.read_text(encoding="utf-8"), "verified evidence\\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "external evidence\\n")


    def test_ocr_batch_source_hash_is_checked_against_original_intake_hash(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        audit = load_helper("lore_intake_audit_ocr_history", namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "INTAKE_BATCH.json"
            evidence = root / "OCR_TEXT_P1.txt"
            evidence.write_text("batch evidence\n", encoding="utf-8")
            text_digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            source_digest = "a" * 64
            batch = {
                "text_path": str(evidence), "text_sha256": text_digest,
                "source_sha256": source_digest, "page_start": 1,
                "page_limit": 10, "page_end_requested": 10,
            }
            result = audit({"ocr_batches": [batch]}, report, (), source_digest)
            self.assertEqual(result["integrity"], "VERIFIED")
            self.assertEqual(result["counts"]["ocr_source_hash_mismatches"], 0)
            batch["source_sha256"] = "b" * 64
            mismatch = audit({"ocr_batches": [batch]}, report, (), source_digest)
            self.assertEqual(mismatch["integrity"], "SOURCE_HASH_MISMATCH")
            self.assertEqual(mismatch["counts"]["ocr_source_hash_mismatches"], 1)
            batch["source_sha256"] = "invalid"
            malformed = audit({"ocr_batches": [batch]}, report, (), source_digest)
            self.assertEqual(malformed["counts"]["invalid_ocr_source_hashes"], 1)


    def test_ocr_history_detects_batch_count_and_latest_metadata_mismatches(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        audit = load_helper("lore_intake_audit_ocr_history", namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first batch\n", encoding="utf-8")
            second.write_text("second batch\n", encoding="utf-8")
            first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
            second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
            metadata = {
                "ocr_batches": [
                    {"text_path": str(first), "text_sha256": first_hash, "source_sha256": "a" * 64,
                     "page_start": 1, "page_limit": 10, "page_end_requested": 10,
                     "confidence": "LOW", "method": "test", "warnings": []},
                    {"text_path": str(second), "text_sha256": second_hash, "source_sha256": "a" * 64,
                     "page_start": 11, "page_limit": 10, "page_end_requested": 20,
                     "confidence": "LOW", "method": "test", "warnings": []},
                ],
                "ocr_batch_count": 2, "ocr_text_path": str(second), "ocr_text_sha256": second_hash,
                "ocr_page_start": 11, "ocr_page_limit": 10, "ocr_page_end_requested": 20,
            }
            verified = audit(metadata, root / "INTAKE_BATCH.json", (), "a" * 64)
            self.assertEqual(verified["integrity"], "VERIFIED")
            self.assertEqual(verified["counts"]["ocr_batch_count_mismatches"], 0)
            self.assertEqual(verified["counts"]["ocr_latest_metadata_mismatches"], 0)
            metadata["ocr_batch_count"] = 99
            metadata["ocr_page_start"] = 12
            mismatch = audit(metadata, root / "INTAKE_BATCH.json", (), "a" * 64)
            self.assertEqual(mismatch["counts"]["ocr_batch_count_mismatches"], 1)
            self.assertGreaterEqual(mismatch["counts"]["ocr_latest_metadata_mismatches"], 1)

    def test_ocr_history_distinguishes_duplicate_page_ranges_and_malformed_batch_fields(self):
        namespace = {
            "Path": Path, "re": __import__("re"),
            "lore_intake_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        }
        audit = load_helper("lore_intake_audit_ocr_history", namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = [root / "one.txt", root / "two.txt"]
            for path in paths:
                path.write_text("batch evidence\n", encoding="utf-8")
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
            metadata = {"ocr_batches": [
                {"text_path": str(paths[0]), "text_sha256": hashes[0],
                 "page_start": 1, "page_limit": 10, "page_end_requested": 10},
                {"text_path": str(paths[1]), "text_sha256": hashes[1],
                 "page_start": 1, "page_limit": 10, "page_end_requested": 10,
                 "confidence": "CERTAIN", "method": 123, "warnings": "not-a-list"},
            ]}
            result = audit(metadata, root / "INTAKE_BATCH.json")
            self.assertEqual(result["counts"]["duplicate_ocr_page_ranges"], 1)
            self.assertEqual(result["counts"]["overlapping_ocr_page_ranges"], 1)
            self.assertEqual(result["counts"]["invalid_ocr_confidence_labels"], 1)
            self.assertEqual(result["counts"]["invalid_ocr_methods"], 1)
            self.assertEqual(result["counts"]["malformed_ocr_warning_lists"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
