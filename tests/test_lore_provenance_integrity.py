import ast
import difflib
import re
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class LoreProvenanceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_quality_audit"]
        if len(matches) != 1:
            raise AssertionError("lore_intake_quality_audit must have exactly one definition")
        module = ast.Module(body=matches, type_ignores=[])
        namespace = {"re": re, "difflib": difflib}
        exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
        cls.audit = staticmethod(namespace["lore_intake_quality_audit"])

    def test_missing_provenance_and_invalid_pages_are_reported(self):
        graph = {"entities": [
            {"kind": "creature", "name": "Ash Maw", "source_files": [], "evidence": [], "source_pages": [0, "bad"]}
        ], "relationships": []}
        result = self.audit([], graph)
        self.assertEqual(result["summary"]["provenance_finding_count"], 2)
        self.assertIn("source file", result["provenance_findings"][0]["missing"])
        self.assertEqual(result["provenance_findings"][1]["invalid_source_pages"], [0, "bad"])

    def test_alias_that_maps_to_two_entities_is_flagged_without_mutation(self):
        graph = {"entities": [
            {"kind": "creature", "name": "Ash Maw", "aliases": ["The Ash Beast"]},
            {"kind": "creature", "name": "Cinder Jaw", "aliases": ["The Ash Beast"]},
        ], "relationships": []}
        before = repr(graph)
        result = self.audit([], graph)
        self.assertEqual(len(result["alias_conflicts"]), 1)
        self.assertEqual(len(graph["entities"]), 2)
        self.assertEqual(repr(graph), before)
        self.assertFalse(result["canon_written"])

    def test_self_relationship_and_conflicting_targets_are_reported(self):
        graph = {"entities": [], "relationships": [
            {"subject": "Ash Maw", "relation": "guards", "object": "Ash Maw", "source_files": ["a.pdf"]},
            {"subject": "Cinder Jaw", "relation": "haunts", "object": "North Wing", "source_files": ["b.pdf"]},
            {"subject": "Cinder Jaw", "relation": "haunts", "object": "South Wing", "source_files": ["c.pdf"]},
        ]}
        result = self.audit([], graph)
        types = {row["type"] for row in result["relationship_quality_findings"]}
        self.assertIn("self_relationship", types)
        self.assertIn("multiple_targets_same_relation", types)

    def test_incomplete_relationship_is_reported(self):
        graph = {"entities": [], "relationships": [
            {"subject": "Ash Maw", "relation": "", "object": "North Wing"}
        ]}
        result = self.audit([], graph)
        self.assertEqual(result["relationship_quality_findings"][0]["type"], "incomplete_relationship")
        self.assertEqual(result["relationship_quality_findings"][0]["missing_fields"], ["relation"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
