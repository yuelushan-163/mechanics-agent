from __future__ import annotations

import json
from pathlib import Path

from mechanics_agent.models import KnowledgeDocument


def load_jsonl_documents(path: Path) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                documents.append(KnowledgeDocument.model_validate(json.loads(text)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid knowledge document") from exc
    return documents

