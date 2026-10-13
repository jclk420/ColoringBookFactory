"""Runtime regression tests for resumable production queue behavior."""
import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_queue_menu(projects, queue, project_list, build_book, choice, saved):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    wanted = {"queue_item_is_safe", "production_queue_menu"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("Expected queue safety helper and menu exactly once")
    namespace = {
        "Path": Path,
        "PROJECTS": projects,
        "load_queue": lambda: queue,
        "save_queue": lambda value: saved.append(list(value.get("items", []))),
        "get_projects": lambda: project_list,
        "build_book": build_book,
        "input": lambda _prompt: choice,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class ProductionQueueRuntimeTests(unittest.TestCase):
    def test_run_removes_success_and_retains_failed_and_missing_items(self):
        with tempfile.TemporaryDirectory() as temp:
            projects = Path(temp) / "Projects"
            projects.mkdir()
            success = projects / "Success"
            failed = projects / "Failed"
            success.mkdir()
            failed.mkdir()
            (success / "project.json").write_text("{}", encoding="utf-8")
            (failed / "project.json").write_text("{}", encoding="utf-8")
            missing = projects / "Missing"
            queue = {"items": [str(success), str(failed), str(missing)]}
            built = []
            saved = []

            def build_book(project):
                built.append(project.name)
                return {"status": "SUCCESS" if project.name == "Success" else "NOT_READY"}

            load_queue_menu(projects, queue, [success, failed], build_book, "r", saved)["production_queue_menu"]()
            self.assertEqual(built, ["Success", "Failed"])
            self.assertEqual(queue["items"], [str(failed), str(missing)])
            self.assertTrue(saved)
            self.assertEqual(saved[0], [str(failed), str(missing)])

    def test_run_catches_exceptions_and_keeps_item_for_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            projects = Path(temp) / "Projects"
            projects.mkdir()
            project = projects / "Crash"
            project.mkdir()
            (project / "project.json").write_text("{}", encoding="utf-8")
            queue = {"items": [str(project)]}
            saved = []

            def fail(_project):
                raise RuntimeError("simulated failure")

            load_queue_menu(projects, queue, [project], fail, "r", saved)["production_queue_menu"]()
            self.assertEqual(queue["items"], [str(project)])

    def test_manual_add_does_not_duplicate_existing_item(self):
        with tempfile.TemporaryDirectory() as temp:
            projects = Path(temp) / "Projects"
            projects.mkdir()
            project = projects / "Book"
            project.mkdir()
            (project / "project.json").write_text("{}", encoding="utf-8")
            queue = {"items": [str(project)]}
            saved = []
            load_queue_menu(projects, queue, [project], lambda _p: {"status": "SUCCESS"}, "1", saved)["production_queue_menu"]()
            self.assertEqual(queue["items"], [str(project)])
            self.assertEqual(saved, [])

    def test_add_all_merges_existing_queue_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            projects = Path(temp) / "Projects"
            projects.mkdir()
            first = projects / "First"
            second = projects / "Second"
            first.mkdir()
            second.mkdir()
            queue = {"items": [str(first)]}
            saved = []
            load_queue_menu(projects, queue, [first, second], lambda _p: {"status": "SUCCESS"}, "a", saved)["production_queue_menu"]()
            self.assertEqual(queue["items"], [str(first), str(second)])

    def test_stale_queue_can_be_cleared_when_no_projects_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            projects = Path(temp) / "Projects"
            projects.mkdir()
            queue = {"items": [str(projects / "DeletedBook")]}
            saved = []
            load_queue_menu(projects, queue, [], lambda _p: {"status": "SUCCESS"}, "c", saved)["production_queue_menu"]()
            self.assertEqual(queue["items"], [])
            self.assertEqual(saved[-1], [])

    def test_build_book_exposes_explicit_outcome_statuses(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_book")
        segment = ast.get_source_segment(source, node) or ""
        for status in ("FAILED", "NOT_READY", "SKIPPED", "SUCCESS"):
            with self.subTest(status=status):
                self.assertIn('"status": "' + status + '"', segment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
