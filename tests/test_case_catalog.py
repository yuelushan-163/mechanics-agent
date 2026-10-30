from __future__ import annotations

import math
import unittest

from fastapi.testclient import TestClient

from mechanics_agent.api import create_app
from mechanics_agent.case_catalog import get_case_template, list_case_templates
from mechanics_agent.embeddings import DisabledEmbedder
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository
from mechanics_agent.models import CaseTemplateStatus
from mechanics_agent.planner import LocalPlanner


class CaseCatalogTests(unittest.TestCase):
    def test_catalog_contains_seven_approved_templates(self) -> None:
        templates = list_case_templates()

        self.assertEqual(7, len(templates))
        self.assertEqual(7, len({item.template_id for item in templates}))
        self.assertTrue(
            all(item.status == CaseTemplateStatus.APPROVED for item in templates)
        )
        self.assertTrue(all(item.case.metadata["solver_execution_requested"] is False for item in templates))

    def test_beam_analytical_baseline_is_dimensionally_consistent(self) -> None:
        template = get_case_template("beam-simply-supported-v2")
        assert template is not None
        p, length, e, width, height = 5000.0, 1000.0, 210000.0, 50.0, 80.0
        inertia = width * height**3 / 12.0
        displacement = p * length**3 / (48.0 * e * inertia)
        stress = (p * length / 4.0) * (height / 2.0) / inertia

        self.assertTrue(
            math.isclose(
                displacement,
                float(template.expected_results["analytical_displacement_mm"]),
                rel_tol=1e-12,
            )
        )
        self.assertTrue(
            math.isclose(
                stress,
                float(template.expected_results["analytical_bending_stress_mpa"]),
                rel_tol=1e-12,
            )
        )
        self.assertEqual(20, template.case.mesh.target_element_count)

    def test_pressure_template_does_not_confuse_axial_and_circumferential_symmetry(self) -> None:
        template = get_case_template("pressure-shell-open-ended-v2")
        assert template is not None

        self.assertEqual(
            "open_no_end_pressure",
            template.case.geometry.parameters["end_closure"],
        )
        self.assertIn("周向1/4", template.case.idealization.symmetry)
        self.assertEqual(125.0, template.expected_results["analytical_hoop_stress_mpa"])

    def test_bolted_joint_inventory_and_screening_capacity_are_consistent(self) -> None:
        template = get_case_template("bolted-lap-joint-v2")
        assert template is not None

        inventory = template.case.geometry.assembly_inventory
        self.assertEqual(10, sum(inventory.values()))
        self.assertEqual(27000.0, template.expected_results["initial_friction_capacity_upper_bound_n"])
        self.assertEqual(0.01, template.case.acceptance.max_relative_slip)

    def test_thermal_template_matches_free_expansion_equation(self) -> None:
        template = get_case_template("thermal-pipe-free-expansion-v2")
        assert template is not None

        expected = 1.2e-5 * 600.0 * (200.0 - 20.0)
        self.assertTrue(
            math.isclose(
                expected,
                float(template.expected_results["analytical_free_end_displacement_mm"]),
                rel_tol=1e-12,
            )
        )
        self.assertEqual(0.0, template.expected_results["far_field_axial_stress_mpa"])

    def test_separate_failure_and_restraint_workflows_have_distinct_gates(self) -> None:
        beam = get_case_template("beam-simply-supported-overload-v1")
        closed = get_case_template("pressure-shell-closed-ended-v1")
        restrained = get_case_template("thermal-pipe-fully-restrained-v1")
        assert beam is not None and closed is not None and restrained is not None

        self.assertEqual("fail", beam.expected_results["expected_acceptance"])
        self.assertAlmostEqual(108.25317547305482, closed.expected_results["analytical_mises_stress_mpa"])
        self.assertGreater(
            restrained.expected_results["elastic_screening_stress_mpa"],
            restrained.expected_results["yield_strength_mpa"],
        )
        self.assertFalse(restrained.case.material.plastic_stress_strain)
        self.assertIn("block_until", restrained.expected_results["expected_precheck"])

    def test_template_api_is_read_only_and_does_not_call_planner(self) -> None:
        app = create_app(
            repository=InMemoryKnowledgeRepository(),
            planner=LocalPlanner(),
            embedder=DisabledEmbedder(),
        )
        with TestClient(app) as client:
            response = client.get("/v1/cases/templates")
            detail = client.get("/v1/cases/templates/beam-simply-supported-v2")
            missing = client.get("/v1/cases/templates/not-found")

        self.assertEqual(200, response.status_code)
        self.assertEqual(7, len(response.json()))
        self.assertEqual(200, detail.status_code)
        self.assertEqual("approved", detail.json()["status"])
        self.assertEqual(404, missing.status_code)


if __name__ == "__main__":
    unittest.main()
