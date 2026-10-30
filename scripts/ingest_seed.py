from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mechanics_agent.config import Settings
from mechanics_agent.embeddings import build_embedder
from mechanics_agent.knowledge.elasticsearch import ElasticsearchKnowledgeRepository
from mechanics_agent.planner import LocalPlanner
from mechanics_agent.seed import load_jsonl_documents
from mechanics_agent.service import MechanicsAgentService


async def _run(path: Path) -> None:
    settings = Settings.from_env()
    service = MechanicsAgentService(
        ElasticsearchKnowledgeRepository(settings),
        LocalPlanner(),
        build_embedder(settings),
    )
    try:
        await service.initialize()
        documents = load_jsonl_documents(path)
        result = await service.ingest(documents)
        print(f"Indexed {result.indexed} documents into {result.index_name}")
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest demo mechanics knowledge into ES")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("data/seed_knowledge.jsonl"),
    )
    args = parser.parse_args()
    asyncio.run(_run(args.path))


if __name__ == "__main__":
    main()

