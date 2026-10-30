from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from mechanics_agent.config import Settings
from mechanics_agent.models import (
    AuditRecord,
    DocumentType,
    KnowledgeDocument,
    ModelUsageRecord,
    ModelUsageSummary,
    ModelUsageSummaryRow,
    SearchHit,
    VerificationRule,
    VerificationStage,
)


class ElasticsearchRepositoryError(RuntimeError):
    pass


class ElasticsearchKnowledgeRepository:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        headers: dict[str, str] = {"Accept": "application/json"}
        auth: httpx.BasicAuth | None = None
        if settings.es_api_key:
            headers["Authorization"] = f"ApiKey {settings.es_api_key}"
        elif settings.es_username:
            auth = httpx.BasicAuth(settings.es_username, settings.es_password or "")
        self.client = httpx.AsyncClient(
            base_url=settings.es_url,
            headers=headers,
            auth=auth,
            verify=settings.es_verify_certs,
            timeout=settings.es_request_timeout_seconds,
            transport=transport,
        )

    @property
    def knowledge_index_name(self) -> str:
        return self.settings.knowledge_index

    async def ensure_indices(self) -> None:
        await self._ensure_index(
            self.settings.knowledge_index,
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "dynamic": "strict",
                    "properties": {
                        "doc_id": {"type": "keyword"},
                        "doc_type": {"type": "keyword"},
                        "title": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        },
                        "content": {"type": "text"},
                        "domain": {"type": "keyword"},
                        "analysis_types": {"type": "keyword"},
                        "tags": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "evidence_level": {"type": "keyword"},
                        "sources": {"type": "object", "enabled": False},
                        "rule": {"type": "object", "enabled": False},
                        "rule_stage": {"type": "keyword"},
                        "rule_enabled": {"type": "boolean"},
                        "metadata": {"type": "object", "enabled": False},
                        "embedding": {
                            "type": "dense_vector",
                            "dims": self.settings.es_vector_dims,
                            "index": True,
                            "similarity": "cosine",
                        },
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                    },
                }
            },
        )
        await self._ensure_index(
            self.settings.runs_index,
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "dynamic": "strict",
                    "properties": {
                        "run_id": {"type": "keyword"},
                        "case_id": {"type": "keyword"},
                        "event_type": {"type": "keyword"},
                        "overall": {"type": "keyword"},
                        "payload": {"type": "object", "enabled": False},
                        "created_at": {"type": "date"},
                    },
                }
            },
        )
        await self._ensure_index(
            self.settings.usage_index,
            {
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "dynamic": "strict",
                    "properties": {
                        "usage_id": {"type": "keyword"},
                        "provider": {"type": "keyword"},
                        "model": {"type": "keyword"},
                        "model_key": {"type": "keyword"},
                        "operation": {"type": "keyword"},
                        "request_id": {"type": "keyword"},
                        "provider_request_id": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "http_status": {"type": "integer"},
                        "input_tokens": {"type": "long"},
                        "cached_input_tokens": {"type": "long"},
                        "uncached_input_tokens": {"type": "long"},
                        "output_tokens": {"type": "long"},
                        "total_tokens": {"type": "long"},
                        "usage_reported": {"type": "boolean"},
                        "pricing_found": {"type": "boolean"},
                        "currency": {"type": "keyword"},
                        "input_rate_per_k_tokens": {"type": "double"},
                        "cached_input_rate_per_k_tokens": {"type": "double"},
                        "output_rate_per_k_tokens": {"type": "double"},
                        "input_cost": {"type": "double"},
                        "cached_input_cost": {"type": "double"},
                        "output_cost": {"type": "double"},
                        "total_cost": {"type": "double"},
                        "latency_ms": {"type": "double"},
                        "error_type": {"type": "keyword"},
                        "created_at": {"type": "date"},
                    },
                }
            },
        )

    async def _ensure_index(self, index_name: str, mapping: dict[str, Any]) -> None:
        response = await self._request(
            "HEAD",
            f"/{index_name}",
            action=f"checking index {index_name}",
        )
        if response.status_code == 200:
            return
        if response.status_code != 404:
            self._raise(response, f"checking index {index_name}")
        response = await self._request(
            "PUT",
            f"/{index_name}",
            action=f"creating index {index_name}",
            json=mapping,
        )
        if response.status_code not in {200, 201}:
            self._raise(response, f"creating index {index_name}")

    async def upsert_documents(self, documents: list[KnowledgeDocument]) -> int:
        if not documents:
            return 0
        lines: list[str] = []
        for document in documents:
            if document.embedding is not None and len(document.embedding) != self.settings.es_vector_dims:
                raise ValueError(
                    f"{document.doc_id}: embedding dimension {len(document.embedding)} "
                    f"does not match ES_VECTOR_DIMS={self.settings.es_vector_dims}"
                )
            source = document.model_dump(mode="json")
            source["rule_stage"] = document.rule.stage.value if document.rule else None
            source["rule_enabled"] = document.rule.enabled if document.rule else False
            lines.append(
                json.dumps(
                    {"index": {"_index": self.settings.knowledge_index, "_id": document.doc_id}},
                    ensure_ascii=False,
                )
            )
            lines.append(json.dumps(source, ensure_ascii=False))
        payload = "\n".join(lines) + "\n"
        response = await self._request(
            "POST",
            "/_bulk?refresh=wait_for",
            action="bulk indexing knowledge documents",
            content=payload.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
        )
        if response.status_code != 200:
            self._raise(response, "bulk indexing knowledge documents")
        result = response.json()
        if result.get("errors"):
            failures = [
                item["index"].get("error")
                for item in result.get("items", [])
                if item.get("index", {}).get("error")
            ]
            raise ElasticsearchRepositoryError(
                f"Elasticsearch bulk indexing had failures: {failures[:3]}"
            )
        return len(documents)

    async def search(
        self,
        query: str,
        *,
        analysis_type: str | None = None,
        domain: str | None = None,
        document_types: list[DocumentType] | None = None,
        query_vector: list[float] | None = None,
        top_k: int = 8,
    ) -> list[SearchHit]:
        if query_vector is not None and len(query_vector) != self.settings.es_vector_dims:
            raise ValueError(
                f"query vector dimension {len(query_vector)} does not match "
                f"ES_VECTOR_DIMS={self.settings.es_vector_dims}"
            )
        filters: list[dict[str, Any]] = [{"term": {"status": "approved"}}]
        if analysis_type:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"analysis_types": analysis_type}},
                            {"term": {"analysis_types": "*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if domain:
            filters.append({"term": {"domain": domain}})
        if document_types:
            filters.append({"terms": {"doc_type": [item.value for item in document_types]}})

        base_bool: dict[str, Any] = {"filter": filters}
        text_clause = {
            "multi_match": {
                "query": query,
                "fields": ["title^3", "content", "tags^2", "domain"],
                "type": "best_fields",
            }
        }
        if query_vector is not None:
            # Vector recall must not depend on sharing exact query terms. Text score is a bonus.
            if query.strip():
                base_bool["should"] = [text_clause]
        elif query.strip():
            base_bool["must"] = [text_clause]
        else:
            base_bool["must"] = [{"match_all": {}}]

        query_body: dict[str, Any] = {"bool": base_bool}
        if query_vector is not None:
            query_body = {
                "script_score": {
                    "query": query_body,
                    "script": {
                        "source": (
                            "doc['embedding'].size() == 0 ? _score : "
                            "_score + cosineSimilarity(params.query_vector, 'embedding') + 1.0"
                        ),
                        "params": {"query_vector": query_vector},
                    },
                }
            }

        response = await self._request(
            "POST",
            f"/{self.settings.knowledge_index}/_search",
            action="searching knowledge",
            json={
                "size": top_k,
                "query": query_body,
                "_source": {"excludes": ["embedding"]},
            },
        )
        if response.status_code != 200:
            self._raise(response, "searching knowledge")
        return [
            SearchHit(
                score=float(hit.get("_score") or 0.0),
                document=self._parse_document(hit["_source"]),
            )
            for hit in response.json().get("hits", {}).get("hits", [])
        ]

    async def get_rules(
        self, stage: VerificationStage, analysis_type: str
    ) -> list[tuple[str, VerificationRule]]:
        response = await self._request(
            "POST",
            f"/{self.settings.knowledge_index}/_search",
            action="loading verification rules",
            json={
                "size": 500,
                "sort": [{"doc_id": "asc"}],
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"doc_type": DocumentType.VERIFICATION_RULE.value}},
                            {"term": {"status": "approved"}},
                            {"term": {"rule_stage": stage.value}},
                            {"term": {"rule_enabled": True}},
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"analysis_types": analysis_type}},
                                        {"term": {"analysis_types": "*"}},
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ]
                    }
                },
                "_source": {"excludes": ["embedding"]},
            },
        )
        if response.status_code != 200:
            self._raise(response, "loading verification rules")
        rules: list[tuple[str, VerificationRule]] = []
        for hit in response.json().get("hits", {}).get("hits", []):
            document = self._parse_document(hit["_source"])
            if document.rule:
                rules.append((document.doc_id, document.rule))
        return rules

    async def record_run(self, record: AuditRecord) -> None:
        response = await self._request(
            "PUT",
            f"/{self.settings.runs_index}/_doc/{record.run_id}",
            action="recording audit run",
            params={"refresh": "wait_for"},
            json=record.model_dump(mode="json"),
        )
        if response.status_code not in {200, 201}:
            self._raise(response, "recording audit run")

    async def record_model_usage(self, record: ModelUsageRecord) -> None:
        response = await self._request(
            "PUT",
            f"/{self.settings.usage_index}/_doc/{record.usage_id}",
            action="recording model usage",
            json=record.model_dump(mode="json"),
        )
        if response.status_code not in {200, 201}:
            self._raise(response, "recording model usage")

    async def list_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 200,
    ) -> list[ModelUsageRecord]:
        response = await self._request(
            "POST",
            f"/{self.settings.usage_index}/_search",
            action="listing model usage",
            json={
                "size": limit,
                "sort": [{"created_at": "desc"}],
                "query": self._usage_query(
                    provider=provider,
                    model=model,
                    operation=operation,
                    from_time=from_time,
                    to_time=to_time,
                ),
            },
        )
        if response.status_code != 200:
            self._raise(response, "listing model usage")
        return [
            ModelUsageRecord.model_validate(hit["_source"])
            for hit in response.json().get("hits", {}).get("hits", [])
        ]

    async def summarize_model_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        operation: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> ModelUsageSummary:
        sum_fields = [
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "total_tokens",
            "total_cost",
        ]
        metric_aggs = {
            field: {"sum": {"field": field}}
            for field in sum_fields
        }
        response = await self._request(
            "POST",
            f"/{self.settings.usage_index}/_search",
            action="summarizing model usage",
            json={
                "size": 0,
                "query": self._usage_query(
                    provider=provider,
                    model=model,
                    operation=operation,
                    from_time=from_time,
                    to_time=to_time,
                ),
                "aggs": {
                    "by_model": {
                        "terms": {"field": "model_key", "size": 200},
                        "aggs": {
                            **metric_aggs,
                            "successes": {
                                "filter": {"term": {"status": "success"}}
                            },
                            "errors": {
                                "filter": {"term": {"status": "error"}}
                            },
                            "usage_missing": {
                                "filter": {"term": {"usage_reported": False}}
                            },
                            "pricing_missing": {
                                "filter": {"term": {"pricing_found": False}}
                            },
                        },
                    }
                },
            },
        )
        if response.status_code != 200:
            self._raise(response, "summarizing model usage")

        buckets = (
            response.json()
            .get("aggregations", {})
            .get("by_model", {})
            .get("buckets", [])
        )
        rows: list[ModelUsageSummaryRow] = []
        for bucket in buckets:
            model_key = str(bucket.get("key", "unknown|unknown"))
            provider_name, _, model_name = model_key.partition("|")
            rows.append(
                ModelUsageSummaryRow(
                    provider=provider_name or "unknown",
                    model=model_name or model_key,
                    request_count=int(bucket.get("doc_count", 0)),
                    success_count=int(bucket.get("successes", {}).get("doc_count", 0)),
                    error_count=int(bucket.get("errors", {}).get("doc_count", 0)),
                    usage_missing_count=int(
                        bucket.get("usage_missing", {}).get("doc_count", 0)
                    ),
                    pricing_missing_count=int(
                        bucket.get("pricing_missing", {}).get("doc_count", 0)
                    ),
                    input_tokens=self._sum_metric(bucket, "input_tokens"),
                    cached_input_tokens=self._sum_metric(
                        bucket, "cached_input_tokens"
                    ),
                    uncached_input_tokens=self._sum_metric(
                        bucket, "uncached_input_tokens"
                    ),
                    output_tokens=self._sum_metric(bucket, "output_tokens"),
                    total_tokens=self._sum_metric(bucket, "total_tokens"),
                    total_cost=self._cost_metric(bucket, "total_cost"),
                    currency="CNY",
                )
            )
        rows.sort(key=lambda item: (-item.total_cost, item.provider, item.model))
        return ModelUsageSummary(
            rows=rows,
            request_count=sum(item.request_count for item in rows),
            input_tokens=sum(item.input_tokens for item in rows),
            cached_input_tokens=sum(item.cached_input_tokens for item in rows),
            uncached_input_tokens=sum(
                item.uncached_input_tokens for item in rows
            ),
            output_tokens=sum(item.output_tokens for item in rows),
            total_tokens=sum(item.total_tokens for item in rows),
            total_cost=round(sum(item.total_cost for item in rows), 12),
            currency="CNY",
        )

    async def health(self) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "/",
            action="checking Elasticsearch health",
        )
        if response.status_code != 200:
            self._raise(response, "checking Elasticsearch health")
        body = response.json()
        return {
            "status": "ok",
            "backend": "elasticsearch",
            "cluster_name": body.get("cluster_name"),
            "version": body.get("version", {}).get("number"),
            "knowledge_index": self.settings.knowledge_index,
            "usage_index": self.settings.usage_index,
        }

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        action: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            return await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ElasticsearchRepositoryError(
                f"Elasticsearch connection failed while {action}: {exc}"
            ) from exc

    @staticmethod
    def _parse_document(source: dict[str, Any]) -> KnowledgeDocument:
        cleaned = {
            key: value
            for key, value in source.items()
            if key not in {"rule_stage", "rule_enabled"}
        }
        return KnowledgeDocument.model_validate(cleaned)

    @staticmethod
    def _usage_query(
        *,
        provider: str | None,
        model: str | None,
        operation: str | None,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        if provider:
            filters.append({"term": {"provider": provider}})
        if model:
            filters.append({"term": {"model": model}})
        if operation:
            filters.append({"term": {"operation": operation}})
        if from_time or to_time:
            date_range: dict[str, str] = {}
            if from_time:
                date_range["gte"] = from_time.isoformat()
            if to_time:
                date_range["lte"] = to_time.isoformat()
            filters.append({"range": {"created_at": date_range}})
        if not filters:
            return {"match_all": {}}
        return {"bool": {"filter": filters}}

    @staticmethod
    def _sum_metric(bucket: dict[str, Any], name: str) -> int:
        return int(round(float(bucket.get(name, {}).get("value") or 0)))

    @staticmethod
    def _cost_metric(bucket: dict[str, Any], name: str) -> float:
        return round(float(bucket.get(name, {}).get("value") or 0), 12)

    @staticmethod
    def _raise(response: httpx.Response, action: str) -> None:
        detail = response.text[:1000]
        raise ElasticsearchRepositoryError(
            f"Elasticsearch error while {action}: HTTP {response.status_code}: {detail}"
        )
