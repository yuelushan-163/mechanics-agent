from __future__ import annotations

import json
from pathlib import Path

from mechanics_agent.models import CaseSpec


ROOT = Path(__file__).resolve().parents[1]


def load_case() -> CaseSpec:
    return CaseSpec.model_validate(
        json.loads((ROOT / "examples" / "linear_static_case.json").read_text(encoding="utf-8"))
    )

