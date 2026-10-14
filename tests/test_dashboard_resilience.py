import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "factory.py"


class DashboardResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FACTORY.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        matches = [node for node in cls.tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_review_dashboard"]
        if len(matches) != 1:
            raise AssertionError("Expected exactly one lore_intake_review_dashboard definition")
        cls.dashboard = ast.get_source_segment(cls.source, matches[0])

    def test_factory_version_is_consistent(self):
        self.assertIn('FACTORY_VERSION = "60.0"', self.source)
        self.assertIn("# Current version: 60.0.", self.source)

    def test_malformed_manifest_batches_are_reported_and_returned_safely(self):
        self.assertIn('manifest_batches_wrong_type', self.dashboard)
        self.assertIn('expected a list', self.dashboard)

    def test_malformed_batches_and_reports_are_counted(self):
        for field in ("malformed_batches", "unreadable_reports", "malformed_reports"):
            with self.subTest(field=field):
                self.assertIn(field, self.dashboard)

    def test_candidate_lists_are_type_checked_before_display(self):
        self.assertIn('if isinstance(classification.get("extracted_entity_candidates", []), list)', self.dashboard)
        self.assertIn('if isinstance(classification.get("extracted_relationships", []), list)', self.dashboard)

    def test_manifest_and_report_paths_are_validated(self):
        for token in ("manifest_wrong_type", "missing_record_paths", "invalid_record_paths", "missing_reports"):
            with self.subTest(token=token):
                self.assertIn(token, self.dashboard)

    def test_malformed_items_and_missing_statuses_are_counted(self):
        self.assertIn('"malformed_items"] += 1', self.dashboard)
        self.assertIn('"missing_statuses"] += 1', self.dashboard)


    def test_dashboard_reports_malformed_nested_fields(self):
        for field in ("malformed_classifications", "malformed_metadata", "malformed_candidates",
                      "malformed_relationship_candidates", "malformed_evidence"):
            with self.subTest(field=field):
                self.assertIn(field, self.dashboard)

    def test_dashboard_reports_status_and_source_quality(self):
        for field in ("unknown_statuses", "missing_sources", "duplicate_report_paths"):
            with self.subTest(field=field):
                self.assertIn(field, self.dashboard)

    def test_dashboard_deduplicates_report_path_warnings_without_mutation(self):
        self.assertIn("seen_report_paths", self.dashboard)
        self.assertIn("duplicate_report_paths", self.dashboard)
        self.assertIn("No records were changed", self.dashboard)

    def test_factory_ocr_persists_text_and_page_range_provenance(self):
        self.assertIn("lore_ocr_select_page_range", self.source)
        self.assertIn('metadata["ocr_text_path"] = str(text_path)', self.source)
        self.assertIn('metadata["ocr_page_start"] = ocr_start_page', self.source)
        self.assertIn('metadata["ocr_text_sha256"]', self.source)
        self.assertIn("lore_intake_write_text_atomic(text_path, batch_text)", self.source)
        self.assertIn("No intake record was changed.", self.source)

    def test_dashboard_checks_staged_and_ocr_evidence_integrity(self):
        for token in (
            "missing_staged_files", "invalid_staged_hashes", "staged_hash_mismatches",
            "missing_ocr_text_paths", "missing_ocr_text_files", "ocr_text_hash_mismatches",
            "invalid_ocr_page_ranges", "malformed_ocr_batches", "overlapping_ocr_page_ranges", "duplicate_ocr_text_paths", "ocr_text_paths_outside_roots", "invalid_ocr_source_hashes", "ocr_source_hash_mismatches", "duplicate_ocr_page_ranges", "ocr_batch_count_mismatches", "ocr_latest_metadata_mismatches", "invalid_ocr_confidence_labels", "malformed_ocr_warning_lists", "invalid_ocr_methods",
            "lore_intake_audit_ocr_history",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.dashboard)

    def test_ocr_rechecks_source_and_staged_hashes_before_attaching(self):
        self.assertIn("lore_intake_validate_ocr_source", self.source)
        self.assertIn("Source integrity changed during OCR", self.source)
        self.assertIn("No OCR evidence or intake metadata was attached.", self.source)

    def test_ocr_evidence_writer_is_no_clobber_and_legacy_history_is_preserved(self):
        writer_start = self.source.index("def lore_intake_write_text_atomic(")
        writer_end = self.source.index("\ndef lore_intake_inspect_file", writer_start)
        writer = self.source[writer_start:writer_end]
        self.assertIn("os.link(str(temp_path), str(path))", writer)
        self.assertNotIn("os.replace(str(temp_path), str(path))", writer)
        self.assertIn('"ocr_generated_at", "legacy"', self.source)
        self.assertIn('Could not update the intake report', self.source)

    def test_dashboard_remains_read_only(self):
        self.assertIn("READ ONLY", self.dashboard)
        self.assertIn("no source or canon data was changed", self.dashboard)


    def test_ocr_batch_writer_records_original_source_hash(self):
        self.assertIn('"source_sha256": source_digest', self.source)
        self.assertIn('item.get("sha256")', self.source)


    def test_dashboard_warning_gate_includes_all_ocr_integrity_findings(self):
        start = self.dashboard.index("if any(summary[key] for key in")
        end = self.dashboard.index("):", start)
        warning_gate = self.dashboard[start:end]
        for token in (
            '"duplicate_ocr_text_paths"', '"ocr_text_paths_outside_roots"',
            '"invalid_ocr_source_hashes"', '"ocr_source_hash_mismatches"',
            '"duplicate_ocr_page_ranges"', '"ocr_batch_count_mismatches"',
            '"ocr_latest_metadata_mismatches"', '"invalid_ocr_confidence_labels"',
            '"malformed_ocr_warning_lists"', '"invalid_ocr_methods"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, warning_gate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
