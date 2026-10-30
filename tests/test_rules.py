from __future__ import annotations

import unittest
from pathlib import Path

from mechanics_agent.models import (
    CaseSpec,
    CheckStatus,
    OverallStatus,
    VerificationStage,
)
from mechanics_agent.rules import VerificationEngine
from mechanics_agent.seed import load_jsonl_documents
from tests.helpers import ROOT, load_case


def _rules(stage: VerificationStage):
    documents = load_jsonl_documents(ROOT / "data" / "seed_knowledge.jsonl")
    return [
        (document.doc_id, document.rule)
        for document in documents
        if document.rule is not None and document.rule.stage == stage
    ]


class VerificationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = VerificationEngine()

    def test_precheck_blocks_missing_engineering_inputs(self) -> None:
        case = CaseSpec(case_id="missing", title="缺少输入")
        result = self.engine.evaluate(case, VerificationStage.PRE, {}, _rules(VerificationStage.PRE))
        self.assertEqual(OverallStatus.BLOCK, result.overall)
        failed_ids = {
            item.rule_id for item in result.results if item.status == CheckStatus.BLOCK
        }
        self.assertEqual(
            {"PRE-UNIT-001", "PRE-LOAD-001", "PRE-BC-001", "PRE-MAT-001"},
            failed_ids,
        )

    def test_complete_case_passes_precheck(self) -> None:
        result = self.engine.evaluate(
            load_case(), VerificationStage.PRE, {}, _rules(VerificationStage.PRE)
        )
        self.assertEqual(OverallStatus.PASS, result.overall)
        self.assertTrue(all(item.status == CheckStatus.PASS for item in result.results))

    def test_valid_postcheck_evidence_passes(self) -> None:
        evidence = {
            "job_status": "COMPLETED",
            "external_force": [0, -10000, 0],
            "reaction_force": [0, 9998, 0],
            "mesh_metric_coarse": 1.82,
            "mesh_metric_fine": 1.88,
            "max_displacement": 1.88,
            "max_equivalent_stress": 210,
            "high_risk_warnings": [],
        }
        result = self.engine.evaluate(
            load_case(),
            VerificationStage.POST,
            evidence,
            _rules(VerificationStage.POST),
        )
        self.assertEqual(OverallStatus.PASS, result.overall)
        self.assertTrue(all(item.status == CheckStatus.PASS for item in result.results))

    def test_force_imbalance_blocks_result(self) -> None:
        evidence = {
            "job_status": "COMPLETED",
            "external_force": [0, -10000, 0],
            "reaction_force": [0, 8000, 0],
            "mesh_metric_coarse": 1.82,
            "mesh_metric_fine": 1.88,
            "max_displacement": 1.88,
            "max_equivalent_stress": 210,
            "high_risk_warnings": [],
        }
        result = self.engine.evaluate(
            load_case(),
            VerificationStage.POST,
            evidence,
            _rules(VerificationStage.POST),
        )
        balance = next(item for item in result.results if item.rule_id == "POST-EQ-001")
        self.assertEqual(OverallStatus.BLOCK, result.overall)
        self.assertEqual(CheckStatus.BLOCK, balance.status)
        self.assertAlmostEqual(0.2, balance.observed["ratio"])

    def test_optional_displacement_rule_is_not_applicable_without_limit(self) -> None:
        case = load_case().model_copy(
            update={
                "acceptance": load_case().acceptance.model_copy(
                    update={"max_displacement": None}
                )
            }
        )
        result = self.engine.evaluate(
            case,
            VerificationStage.POST,
            {
                "job_status": "COMPLETED",
                "external_force": [0, -10000, 0],
                "reaction_force": [0, 10000, 0],
                "mesh_metric_coarse": 1.0,
                "mesh_metric_fine": 1.0,
                "max_equivalent_stress": 100,
                "high_risk_warnings": [],
            },
            _rules(VerificationStage.POST),
        )
        displacement = next(
            item for item in result.results if item.rule_id == "POST-DISP-001"
        )
        self.assertEqual(CheckStatus.NOT_APPLICABLE, displacement.status)


if __name__ == "__main__":
    unittest.main()

