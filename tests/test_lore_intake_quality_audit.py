import ast
import difflib
import re
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class LoreIntakeQualityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_quality_audit"]
        if len(matches) != 1:
            raise AssertionError("lore_intake_quality_audit must have exactly one definition")
        module = ast.Module(body=matches, type_ignores=[])
        cls.audit = {"re": re, "difflib": difflib}
        exec(compile(module, str(FACTORY_PATH), "exec"), cls.audit)
        cls.audit = staticmethod(cls.audit["lore_intake_quality_audit"])

    def test_prioritizes_low_confidence_unresolved_records_without_mutating_input(self):
        records = [{
            "file": "uncertain.pdf", "kind": "unmatched", "name": "(unresolved)",
            "confidence": "LOW", "evidence": "none", "unresolved": True,
            "duplicate": False, "extracted_entity_candidates": [{"name": "Unknown Creature"}],
        }]
        before = repr(records)
        result = self.audit(records, {"entities": [], "relationships": []})
        self.assertEqual(repr(records), before)
        self.assertEqual(result["quality_queue"][0]["priority"], "HIGH")
        self.assertLess(result["quality_queue"][0]["score"], 60)
        self.assertTrue(result["review_only"])
        self.assertFalse(result["canon_written"])

    def test_suggests_similar_names_without_merging(self):
        graph = {"entities": [
            {"kind": "creature", "name": "Willow Stalker", "source_files": ["a.pdf"]},
            {"kind": "creature", "name": "Willow Stalkers", "source_files": ["b.pdf"]},
        ], "relationships": []}
        result = self.audit([], graph)
        self.assertEqual(len(result["near_duplicate_suggestions"]), 1)
        self.assertEqual(len(graph["entities"]), 2)

    def test_reports_conflicts_invalid_types_and_missing_relationship_endpoints(self):
        graph = {
            "entities": [{"kind": "planetary_beast", "name": "Ash Maw", "source_files": ["a.pdf"]}],
            "relationships": [{"subject": "Ash Maw", "relation": "haunts_location",
                               "object": "Forgotten Wing", "source_files": ["a.pdf"]}],
            "duplicate_name_warnings": [{"name": "Ash Maw", "reason": "conflicting context"}],
            "archive_id_conflicts": [{"archive_id": "HSN-001", "candidate_names": ["Ash Maw", "Ashmaw"]}],
        }
        result = self.audit([], graph)
        self.assertEqual(result["summary"]["invalid_entity_type_count"], 1)
        self.assertEqual(result["summary"]["contradiction_count"], 2)
        self.assertEqual(result["summary"]["unresolved_relationship_count"], 1)
        self.assertEqual(result["unresolved_relationships"][0]["missing_endpoints"], ["object"])


    def test_malformed_graph_shapes_and_source_file_fields_are_reported_safely(self):
        graph = {
            "entities": [
                {"kind": "creature", "name": "Willow Stalker", "source_files": ["a.pdf"]},
                {"kind": "creature", "name": "Willow Stalkers", "source_files": "b.pdf"},
            ],
            "relationships": "not-a-list",
        }
        result = self.audit("not-a-record-list", graph)
        self.assertEqual(result["summary"]["input_shape_finding_count"], 2)
        self.assertEqual(result["review_summary"]["finding_group_counts"]["input_shape_findings"], 2)
        self.assertEqual(result["summary"]["entity_structure_finding_count"], 1)
        self.assertTrue(result["review_only"])
        self.assertFalse(result["canon_written"])
        self.assertEqual(graph["relationships"], "not-a-list")

    def test_placeholder_evidence_and_whitespace_confidence_are_scored_correctly(self):
        records = [{
            "file": "placeholder.pdf", "kind": "creature", "name": "Ash Maw",
            "confidence": " high ", "evidence": "N/A", "unresolved": False, "duplicate": False,
        }]
        result = self.audit(records, {"entities": [], "relationships": []})
        item = result["quality_queue"][0]
        self.assertIn("missing evidence", item["flags"])
        self.assertNotIn("unknown confidence", item["flags"])
        self.assertEqual(result["summary"]["evidence_finding_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
