import ast
import difflib
import re
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class LoreReviewHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_quality_audit"]
        if len(functions) != 1:
            raise AssertionError("Expected one lore_intake_quality_audit function")
        namespace = {"re": re, "difflib": difflib}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
        cls.audit = staticmethod(namespace["lore_intake_quality_audit"])

    def test_unknown_confidence_is_flagged_without_rewriting_record(self):
        record = {"file": "scan.pdf", "confidence": "ABSOLUTE"}
        result = self.audit([record], {"entities": [], "relationships": []})
        self.assertEqual(result["confidence_findings"][0]["type"], "unknown_confidence_label")
        self.assertEqual(record["confidence"], "ABSOLUTE")

    def test_duplicate_page_references_are_flagged_across_records(self):
        result = self.audit(
            [{"file": "scan.pdf", "source_pages": [2, "2", 3]}],
            {"entities": [{"name": "Ghoul", "source_pages": [4, 4]}],
             "relationships": [{"subject": "Ghoul", "relation": "haunts", "object": "Cell", "source_pages": [7, 7]}]})
        self.assertEqual(len(result["repeated_page_findings"]), 3)

    def test_duplicate_aliases_and_malformed_alias_type_are_flagged(self):
        result = self.audit([], {"entities": [
            {"name": "Ash Maw", "aliases": ["The Maw", "the-maw"]},
            {"name": "Bog Thing", "aliases": "Bog Beast"}], "relationships": []})
        kinds = {row["type"] for row in result["duplicate_alias_findings"]}
        self.assertIn("duplicate_alias_within_entity", kinds)
        self.assertIn("aliases_wrong_type", kinds)

    def test_relationships_without_provenance_are_flagged(self):
        result = self.audit([], {"entities": [], "relationships": [
            {"subject": "Ash Maw", "relation": "guards", "object": "Gate"}]})
        finding = result["relationship_provenance_findings"][0]
        self.assertEqual(set(finding["missing"]), {"source file", "evidence", "source page"})

    def test_duplicate_canonical_entities_and_alias_name_collisions_are_flagged(self):
        graph = {"entities": [
            {"name": "Ash Maw", "kind": "creature", "aliases": ["Bog Thing"]},
            {"name": "ash-maw", "kind": "creature"},
            {"name": "Bog Thing", "kind": "creature"}], "relationships": []}
        result = self.audit([], graph)
        kinds = {row["type"] for row in result["entity_structure_findings"]}
        self.assertIn("duplicate_canonical_entity", kinds)
        self.assertIn("alias_matches_canonical_name", kinds)
        self.assertFalse(result["canon_written"])

    def test_malformed_entity_relationship_and_record_shapes_are_reported(self):
        result = self.audit(
            [None, {"source_pages": "page 2", "extracted_entity_candidates": "Ghoul", "evidence": "TBD"}],
            {"entities": [None, {"name": " ", "aliases": "one", "source_files": ["", "a.pdf", "A.PDF"]}],
             "relationships": [False, {"subject": "A", "relation": "haunts", "object": "B",
                                       "source_pages": "3", "confidence": "ABSOLUTE"}]})
        entity_types = {row["type"] for row in result["entity_structure_findings"]}
        relationship_types = {row["type"] for row in result["relationship_structure_findings"]}
        record_types = {row["type"] for row in result["record_structure_findings"]}
        self.assertIn("entity_not_object", entity_types)
        self.assertIn("missing_entity_name", entity_types)
        self.assertIn("entity_field_wrong_type", entity_types)
        self.assertIn("duplicate_list_entries", entity_types)
        self.assertIn("relationship_not_object", relationship_types)
        self.assertIn("relationship_field_wrong_type", relationship_types)
        self.assertIn("unknown_relationship_confidence", relationship_types)
        self.assertIn("record_not_object", record_types)
        self.assertIn("record_field_wrong_type", record_types)
        self.assertIn("placeholder_evidence", record_types)

    def test_actionable_review_gives_plain_language_next_steps(self):
        result = self.audit([{"file": "", "confidence": "HIGH", "evidence": "unknown"}],
                            {"entities": [], "relationships": []})
        self.assertTrue(result["actionable_review"])
        self.assertTrue(all(item.get("next_step") for item in result["actionable_review"]))
        self.assertEqual(result["summary"]["actionable_review_count"], len(result["actionable_review"]))
        self.assertFalse(result["canon_written"])

    def test_cross_kind_name_collisions_and_ambiguous_endpoints_are_flagged(self):
        graph = {"entities": [
            {"name": "Hollow Gate", "kind": "location", "source_files": ["lore.pdf"]},
            {"name": "Hollow Gate", "kind": "creature", "source_files": ["cryptids.pdf"]}],
            "relationships": [{"subject": "Hollow Gate", "relation": "guards", "object": "Hollow Gate"}]}
        result = self.audit([], graph)
        self.assertTrue(result["entity_kind_name_collisions"])
        self.assertEqual(len(result["ambiguous_relationship_endpoints"]), 2)
        self.assertFalse(result["canon_written"])

    def test_source_paths_and_candidate_traceability_are_flagged(self):
        records = [{"file": "Scan.PDF", "source_files": ["A/Scan.pdf", "a\\scan.PDF"],
                    "extracted_entity_candidates": [
                        {"name": "Ghoul", "confidence": "HIGH", "evidence": "unknown"},
                        {"name": "", "source_pages": [], "source_files": []}]}]
        result = self.audit(records, {"entities": [], "relationships": []})
        self.assertTrue(result["source_path_findings"])
        self.assertTrue(result["candidate_traceability_findings"])
        self.assertTrue(result["evidence_quality_findings"])
        self.assertEqual(result["review_summary"]["canon_written"], False)
        self.assertEqual(result["summary"]["candidate_traceability_finding_count"],
                         len(result["candidate_traceability_findings"]))

    def test_audit_handles_non_list_graph_collections_without_mutation(self):
        graph = {"entities": "bad", "relationships": {"subject": "A"}}
        records = {"file": "not-a-list"}
        result = self.audit(records, graph)
        self.assertEqual(result["record_count"], 0)
        self.assertEqual(result["unresolved_relationships"], [])
        self.assertFalse(result["canon_written"])

    def test_duplicate_relationships_are_flagged_but_not_removed(self):
        links = [
            {"subject": "Ash Maw", "relation": "guards", "object": "Gate", "source_files": ["a.pdf"]},
            {"subject": "ash-maw", "relation": "GUARDS", "object": "gate", "source_files": ["b.pdf"]}]
        result = self.audit([], {"entities": [], "relationships": links})
        self.assertEqual(result["duplicate_relationship_findings"][0]["count"], 2)
        self.assertEqual(len(links), 2)
        self.assertFalse(result["canon_written"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
