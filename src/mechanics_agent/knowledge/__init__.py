"""Knowledge repository adapters."""

from mechanics_agent.knowledge.base import KnowledgeRepository
from mechanics_agent.knowledge.elasticsearch import ElasticsearchKnowledgeRepository
from mechanics_agent.knowledge.memory import InMemoryKnowledgeRepository

__all__ = [
    "ElasticsearchKnowledgeRepository",
    "InMemoryKnowledgeRepository",
    "KnowledgeRepository",
]

