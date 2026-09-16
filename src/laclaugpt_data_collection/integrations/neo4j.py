"""Optional Neo4j adapter for collection-owned factual graph structure.

The neo4j package is imported lazily so Data Collection has no hard graph dependency.
"""
from __future__ import annotations

from typing import Any


class Neo4jRecordIndexer:
    """Idempotently MERGE canonical records and source-factual relationships."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        if not uri:
            raise ValueError("Neo4j URI is required when the Neo4j indexer is enabled")
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Neo4j support is optional; install laclaugpt-data-collection[rag]"
            ) from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jRecordIndexer":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def index(self, payload: dict[str, Any], *, idempotency_key: str) -> None:
        """Write only Collection-owned nodes/edges using canonical identity as MERGE key."""
        with self._driver.session(database=self._database) as session:
            session.execute_write(self._write_payload, payload, idempotency_key)

    @staticmethod
    def _write_payload(tx: Any, payload: dict[str, Any], idempotency_key: str) -> None:
        record_id = payload["record_id"]
        tx.run(
            """
            MERGE (r:Record {record_id: $record_id})
            SET r.source_url = $source_url,
                r.schema_version = $schema_version,
                r.created_at = $created_at,
                r.collected_at = $collected_at,
                r.collector = $collector,
                r.collector_version = $collector_version,
                r.raw_ref = $raw_ref,
                r.idempotency_key = $idempotency_key
            """,
            record_id=record_id,
            source_url=payload.get("source_url"),
            schema_version=payload.get("schema_version"),
            created_at=payload.get("created_at"),
            collected_at=payload.get("collected_at"),
            collector=payload.get("collector"),
            collector_version=payload.get("collector_version"),
            raw_ref=payload.get("raw_ref"),
            idempotency_key=idempotency_key,
        )

        platform = payload.get("platform")
        if platform:
            tx.run(
                """
                MATCH (r:Record {record_id: $record_id})
                MERGE (p:Platform {name: $platform})
                MERGE (r)-[:ON_PLATFORM]->(p)
                """,
                record_id=record_id,
                platform=platform,
            )

        dataset = payload.get("dataset")
        if dataset:
            tx.run(
                """
                MATCH (r:Record {record_id: $record_id})
                MERGE (d:Dataset {name: $dataset})
                MERGE (r)-[:IN_DATASET]->(d)
                """,
                record_id=record_id,
                dataset=dataset,
            )

        language = payload.get("language")
        if language:
            tx.run(
                """
                MATCH (r:Record {record_id: $record_id})
                MERGE (l:Language {code: $language})
                MERGE (r)-[:HAS_LANGUAGE]->(l)
                """,
                record_id=record_id,
                language=language,
            )

        source_type = payload.get("source_type") or "source"
        source_key = f"{platform or 'source'}:{source_type}"
        tx.run(
            """
            MATCH (r:Record {record_id: $record_id})
            MERGE (s:Source {source_key: $source_key})
            SET s.platform = $platform, s.source_type = $source_type
            MERGE (r)-[:FROM_SOURCE]->(s)
            """,
            record_id=record_id,
            source_key=source_key,
            platform=platform or "",
            source_type=source_type,
        )
