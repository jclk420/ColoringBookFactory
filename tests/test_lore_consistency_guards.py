import ast
import difflib
import re
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class LoreConsistencyGuardTests(unittest.TestCase):
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

    def test_source_file_shared_by_distinct_entities_is_flagged(self):
        graph = {"entities": [
            {"kind": "creature", "name": "Ash Maw", "source_files": ["C:/Books/a.pdf"]},
            {"kind": "location", "name": "North Wing", "source_files": ["c:\\books\\a.pdf"]},
        ], "relationships": []}
        result = self.audit([], graph)
        self.assertEqual(result["summary"]["duplicate_source_finding_count"], 1)

    def test_high_confidence_without_evidence_and_bad_pages_are_flagged(self):
        records = [{"file": "intake.pdf", "confidence": "HIGH", "evidence": "", "source_pages": [0, "bad"]}]
        result = self.audit(records, {"entities": [], "relationships": []})
        kinds = {item["type"] for item in result["evidence_findings"]}
        self.assertIn("high_confidence_without_evidence", kinds)
        self.assertIn("invalid_record_source_pages", kinds)

    def test_context_placeholders_and_world_location_collision_are_flagged(self):
        records = [
            {"file": "one.pdf", "world": "Nightmare World", "location": "Nightmare World"},
            {"file": "two.pdf", "world": "Unassigned World", "location": "Unknown"},
        ]
        result = self.audit(records, {"entities": [], "relationships": []})
        kinds = {item["type"] for item in result["context_findings"]}
        self.assertIn("world_equals_location", kinds)
        self.assertIn("placeholder_context_value", kinds)

    def test_duplicate_candidates_and_malformed_candidate_list_are_flagged(self):
        records = [
            {"file": "dupes.pdf", "extracted_entity_candidates": [
                {"name": "Ash Maw", "kind": "creature"}, {"name": "Ash-Maw", "kind": "creature"}
            ]},
            {"file": "bad.pdf", "extracted_entity_candidates": "not-a-list"},
        ]
        result = self.audit(records, {"entities": [], "relationships": []})
        kinds = {item["type"] for item in result["candidate_findings"]}
        self.assertIn("duplicate_candidate_in_record", kinds)
        self.assertIn("candidate_list_wrong_type", kinds)
        self.assertFalse(result["canon_written"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
