import json
from pathlib import Path
import unittest


SNAPSHOT = Path(__file__).resolve().parents[1] / "clients" / "ansys_mechanical" / "v0.11.1"


class AnsysClientSnapshotTests(unittest.TestCase):
    def read_json(self, name: str):
        return json.loads((SNAPSHOT / name).read_text(encoding="utf-8"))

    def test_required_snapshot_files_exist(self):
        required = {
            "adapter.py",
            "loads.py",
            "mechanical_loads.py",
            "mechanical_tools.py",
            "verification.py",
            "tool_bridge.py",
            "tools.schema.json",
            "workflow.schema.json",
            "knowledge_catalog.json",
            "rules.ansys252.json",
            "SNAPSHOT.md",
        }
        self.assertTrue(required.issubset({path.name for path in SNAPSHOT.iterdir()}))

    def test_knowledge_and_rule_counts_are_stable(self):
        catalog = self.read_json("knowledge_catalog.json")
        rules = self.read_json("rules.ansys252.json")
        self.assertEqual(catalog["version"], "1")
        self.assertEqual(len(catalog["knowledge"]), 90)
        self.assertEqual(rules["version"], "ansys252-linear-static-loads-2")
        self.assertEqual(len(rules["rules"]), 9)

    def test_tool_bridge_remains_allowlisted(self):
        schema = self.read_json("tools.schema.json")
        names = {tool["function"]["name"] for tool in schema}
        self.assertEqual(
            names,
            {
                "mechanical_status",
                "inspect_project",
                "review_static_model",
                "validate_static_plan",
                "run_static_workflow",
                "run_static_cases",
                "search_engineering_knowledge",
            },
        )

    def test_release_binaries_are_not_imported(self):
        forbidden = {"_internal", "runtime_payload", "Ansys力学助手_v0.11.1.exe"}
        self.assertTrue(forbidden.isdisjoint({path.name for path in SNAPSHOT.iterdir()}))


if __name__ == "__main__":
    unittest.main()
