"""Optional RDF and knowledge-graph projection for collection records.

Collectors keep emitting the canonical record. This module projects that record into
backend-neutral entities and relations only when explicitly called.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import CanonicalRecord

LACLAUGPT_NS = "https://laclaugpt.org/ns/"
ID_BASE = "https://laclaugpt.org/id/"

JSONLD_CONTEXT: dict[str, Any] = {
    "@version": 1.1,
    "schema": "https://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "oa": "http://www.w3.org/ns/oa#",
    "laclau": LACLAUGPT_NS,
    "id": "@id",
    "type": "@type",
    "label": "schema:name",
    "url": {"@id": "schema:url", "@type": "@id"},
    "identifier": "dcterms:identifier",
    "author": {"@id": "schema:author", "@type": "@id"},
    "isPartOf": {"@id": "schema:isPartOf", "@type": "@id"},
    "hasPart": {"@id": "schema:hasPart", "@type": "@id"},
    "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@type": "@id"},
    "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
    "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
}


def stable_uri(kind: str, identity: str, *, base: str = ID_BASE) -> str:
    """Return a deterministic semantic URI independent of storage backends."""
    normalized_kind = kind.strip().lower().replace("_", "-")
    identity = identity.strip()
    if not normalized_kind or not identity:
        raise ValueError("kind and identity are required")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{base.rstrip('/')}/{normalized_kind}/{digest}"


@dataclass(frozen=True, slots=True)
class KGNode:
    id: str
    type: str
    label: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KGEdge:
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KGProjection:
    nodes: list[KGNode] = field(default_factory=list)
    edges: list[KGEdge] = field(default_factory=list)

    def node_map(self) -> dict[str, KGNode]:
        return {node.id: node for node in self.nodes}


def _edge(edge_type: str, source: str, target: str, **properties: Any) -> KGEdge:
    identity = json.dumps(
        [edge_type, source, target, properties],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return KGEdge(
        id=stable_uri("relation", identity),
        type=edge_type,
        source=source,
        target=target,
        properties=properties,
    )


def project_record(record: CanonicalRecord, *, study_id: str | None = None) -> KGProjection:
    """Project one canonical record to backend-neutral KG nodes and edges."""
    nodes: list[KGNode] = []
    edges: list[KGEdge] = []

    record_uri = stable_uri("document", record.source_url)
    nodes.append(
        KGNode(
            id=record_uri,
            type="schema:DigitalDocument",
            label=record.content.title or record.source_url,
            properties={
                "url": record.source_url,
                "identifier": dict(record.source_native_ids),
                "schema:dateCreated": record.source.created_at,
                "laclau:collectedAt": record.source.collected_at,
                "laclau:language": record.source.language or record.content.language,
                "laclau:schemaVersion": record.schema_version,
                "laclau:sourceType": record.source.source_type,
            },
        )
    )

    if study_id:
        study_uri = stable_uri("study", study_id)
        nodes.append(
            KGNode(
                id=study_uri,
                type="schema:ResearchProject",
                label=study_id,
                properties={"identifier": study_id},
            )
        )
        edges.append(_edge("schema:isPartOf", record_uri, study_uri))

    if record.source.platform:
        platform_uri = stable_uri("platform", record.source.platform)
        nodes.append(
            KGNode(
                id=platform_uri,
                type="schema:WebSite",
                label=record.source.platform,
                properties={"identifier": record.source.platform},
            )
        )
        edges.append(_edge("dcterms:source", record_uri, platform_uri))

    if record.source.author:
        author_identity = f"{record.source.platform}:{record.source.author}"
        author_uri = stable_uri("account", author_identity)
        nodes.append(
            KGNode(
                id=author_uri,
                type="schema:Person",
                label=record.source.author_fullname or record.source.author,
                properties={
                    "identifier": record.source.author,
                    "laclau:platform": record.source.platform,
                },
            )
        )
        edges.append(_edge("schema:author", record_uri, author_uri))

    if record.source.parent_source_url:
        parent_uri = stable_uri("document", record.source.parent_source_url)
        nodes.append(
            KGNode(
                id=parent_uri,
                type="schema:DigitalDocument",
                label=record.source.parent_source_url,
                properties={"url": record.source.parent_source_url},
            )
        )
        edges.append(_edge("laclau:repliesTo", record_uri, parent_uri))

    raw_identity = record.raw_capture.ref or record.source.raw_ref
    if raw_identity:
        raw_uri = stable_uri("raw-object", raw_identity)
        nodes.append(
            KGNode(
                id=raw_uri,
                type="prov:Entity",
                label=raw_identity,
                properties={
                    "laclau:objectRef": raw_identity,
                    "laclau:checksum": record.raw_capture.checksum,
                    "laclau:contentType": record.raw_capture.content_type,
                },
            )
        )
        edges.append(_edge("prov:wasDerivedFrom", record_uri, raw_uri))

    for media in record.content.media_references:
        media_identity = media.object_ref or media.url or media.ref or media.local_ref
        if not media_identity:
            continue
        media_uri = stable_uri("media", media_identity)
        nodes.append(
            KGNode(
                id=media_uri,
                type="schema:MediaObject",
                label=media.kind or media.media_type or media_identity,
                properties={
                    "url": media.url or None,
                    "laclau:objectRef": media.object_ref or media.ref or media.local_ref or None,
                    "laclau:checksum": media.checksum or None,
                    "laclau:mediaType": media.media_type or None,
                    "laclau:mediaIndex": media.media_index,
                },
            )
        )
        edges.append(_edge("schema:hasPart", record_uri, media_uri))

    for index, provenance in enumerate(record.provenance):
        provenance_identity = provenance.provenance_id or (
            f"{record.source_url}:{provenance.collector}:{provenance.captured_at}:{index}"
        )
        activity_uri = stable_uri("collection-activity", provenance_identity)
        nodes.append(
            KGNode(
                id=activity_uri,
                type="prov:Activity",
                label=provenance.method or provenance.collector,
                properties={
                    "identifier": provenance_identity,
                    "prov:startedAtTime": provenance.captured_at,
                    "laclau:collector": provenance.collector,
                    "laclau:collectorVersion": provenance.collector_version,
                    "laclau:method": provenance.method,
                    "laclau:runId": provenance.run_id,
                    "laclau:gitCommit": provenance.git_commit,
                },
            )
        )
        edges.append(_edge("prov:wasGeneratedBy", record_uri, activity_uri))
        collector_identity = provenance.module or provenance.collector
        if collector_identity:
            agent_uri = stable_uri("agent", collector_identity)
            nodes.append(
                KGNode(
                    id=agent_uri,
                    type="prov:SoftwareAgent",
                    label=collector_identity,
                    properties={"identifier": collector_identity},
                )
            )
            edges.append(_edge("prov:wasAssociatedWith", activity_uri, agent_uri))
        for input_ref in provenance.input_refs:
            input_uri = stable_uri("entity", input_ref)
            nodes.append(
                KGNode(
                    id=input_uri,
                    type="prov:Entity",
                    label=input_ref,
                    properties={"identifier": input_ref},
                )
            )
            edges.append(_edge("prov:used", activity_uri, input_uri))

    return KGProjection(
        nodes=list({node.id: node for node in nodes}.values()),
        edges=list({edge.id: edge for edge in edges}.values()),
    )


def _expand_term(value: str) -> str:
    prefixes = {
        "schema": "https://schema.org/",
        "dcterms": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "oa": "http://www.w3.org/ns/oa#",
        "laclau": LACLAUGPT_NS,
    }
    if ":" not in value:
        return f"{LACLAUGPT_NS}{value}"
    prefix, local = value.split(":", 1)
    return f"{prefixes.get(prefix, prefix + ':')}{local}"


def to_jsonld(projection: KGProjection) -> dict[str, Any]:
    """Return compact JSON-LD without requiring RDFLib."""
    graph: list[dict[str, Any]] = []
    for node in projection.nodes:
        item = {"id": node.id, "type": node.type, "label": node.label}
        item.update({k: v for k, v in node.properties.items() if v not in (None, "", [], {})})
        graph.append(item)
    for edge in projection.edges:
        graph.append(
            {
                "id": edge.id,
                "type": "rdf:Statement",
                "rdf:subject": {"id": edge.source},
                "rdf:predicate": {"id": _expand_term(edge.type)},
                "rdf:object": {"id": edge.target},
                "laclau:relationType": edge.type,
            }
        )
    context = dict(JSONLD_CONTEXT)
    context["rdf"] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    return {"@context": context, "@graph": graph}


def to_rdf_graph(projection: KGProjection) -> Any:
    """Build an RDFLib graph lazily so normal collection has no RDF dependency."""
    try:
        from rdflib import Graph, Literal, RDF, URIRef
        from rdflib.namespace import XSD
    except ImportError as exc:
        raise RuntimeError("RDF export requires the optional kg dependency set") from exc

    graph = Graph()
    graph.bind("schema", "https://schema.org/")
    graph.bind("prov", "http://www.w3.org/ns/prov#")
    graph.bind("laclau", LACLAUGPT_NS)
    for node in projection.nodes:
        subject = URIRef(node.id)
        graph.add((subject, RDF.type, URIRef(_expand_term(node.type))))
        if node.label:
            graph.add((subject, URIRef("https://schema.org/name"), Literal(node.label)))
        for key, value in node.properties.items():
            if value in (None, "", [], {}):
                continue
            predicate = URIRef(_expand_term(key))
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, dict):
                    graph.add((subject, predicate, Literal(json.dumps(item, sort_keys=True))))
                elif isinstance(item, bool):
                    graph.add((subject, predicate, Literal(item, datatype=XSD.boolean)))
                elif isinstance(item, int):
                    graph.add((subject, predicate, Literal(item, datatype=XSD.integer)))
                elif isinstance(item, str) and item.startswith(("http://", "https://", "urn:")):
                    graph.add((subject, predicate, URIRef(item)))
                else:
                    graph.add((subject, predicate, Literal(item)))
    for edge in projection.edges:
        graph.add((URIRef(edge.source), URIRef(_expand_term(edge.type)), URIRef(edge.target)))
    return graph


def serialize_rdf(projection: KGProjection, *, format: str = "turtle") -> str:
    """Serialize the projection through RDFLib."""
    graph = to_rdf_graph(projection)
    if format in {"nquads", "n-quads"}:
        from rdflib import Dataset

        dataset = Dataset()
        for triple in graph:
            dataset.default_context.add(triple)
        return str(dataset.serialize(format="nquads"))
    return str(graph.serialize(format=format))


def write_csv_tables(directory: Path, projection: KGProjection) -> tuple[Path, Path]:
    """Write canonical node and edge tables for local and CSC workflows."""
    directory.mkdir(parents=True, exist_ok=True)
    nodes_path = directory / "nodes.csv"
    edges_path = directory / "edges.csv"
    with nodes_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "type", "label", "properties_json"])
        writer.writeheader()
        for node in projection.nodes:
            writer.writerow(
                {
                    "id": node.id,
                    "type": node.type,
                    "label": node.label,
                    "properties_json": json.dumps(node.properties, ensure_ascii=False, sort_keys=True),
                }
            )
    with edges_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "type", "source", "target", "properties_json"],
        )
        writer.writeheader()
        for edge in projection.edges:
            writer.writerow(
                {
                    "id": edge.id,
                    "type": edge.type,
                    "source": edge.source,
                    "target": edge.target,
                    "properties_json": json.dumps(edge.properties, ensure_ascii=False, sort_keys=True),
                }
            )
    return nodes_path, edges_path


class SQLiteKGStore:
    """Local node/edge tables; SQLite is not treated as a native triple store."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, projection: KGProjection) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    properties_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    properties_json TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO kg_nodes(id, type, label, properties_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        node.id,
                        node.type,
                        node.label,
                        json.dumps(node.properties, ensure_ascii=False, sort_keys=True),
                    )
                    for node in projection.nodes
                ],
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO kg_edges(id, type, source, target, properties_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.id,
                        edge.type,
                        edge.source,
                        edge.target,
                        json.dumps(edge.properties, ensure_ascii=False, sort_keys=True),
                    )
                    for edge in projection.edges
                ],
            )


def to_mongo_graph_documents(projection: KGProjection) -> dict[str, list[dict[str, Any]]]:
    """Return MongoDB-ready documents with semantic identity preserved."""
    return {
        "entities": [
            {"semantic_id": node.id, "entity_type": node.type, "label": node.label, **node.properties}
            for node in projection.nodes
        ],
        "relations": [
            {
                "semantic_id": edge.id,
                "relation_type": edge.type,
                "source_id": edge.source,
                "target_id": edge.target,
                **edge.properties,
            }
            for edge in projection.edges
        ],
    }


def to_arango_documents(projection: KGProjection) -> dict[str, list[dict[str, Any]]]:
    """Return ArangoDB-ready vertices and edges without leaking its IDs upstream."""
    key_by_id = {
        node.id: hashlib.sha256(node.id.encode("utf-8")).hexdigest()[:32]
        for node in projection.nodes
    }
    vertices = [
        {
            "_key": key_by_id[node.id],
            "semantic_id": node.id,
            "entity_type": node.type,
            "label": node.label,
            **node.properties,
        }
        for node in projection.nodes
    ]
    edges = []
    for edge in projection.edges:
        source_key = key_by_id.get(edge.source)
        target_key = key_by_id.get(edge.target)
        if source_key is None or target_key is None:
            continue
        edges.append(
            {
                "_key": hashlib.sha256(edge.id.encode("utf-8")).hexdigest()[:32],
                "_from": f"kg_entities/{source_key}",
                "_to": f"kg_entities/{target_key}",
                "semantic_id": edge.id,
                "relation_type": edge.type,
                "source_id": edge.source,
                "target_id": edge.target,
                **edge.properties,
            }
        )
    return {"vertices": vertices, "edges": edges}


def merge_projections(projections: Iterable[KGProjection]) -> KGProjection:
    """Merge a batch without changing semantic identities."""
    nodes: dict[str, KGNode] = {}
    edges: dict[str, KGEdge] = {}
    for projection in projections:
        nodes.update({node.id: node for node in projection.nodes})
        edges.update({edge.id: edge for edge in projection.edges})
    return KGProjection(nodes=list(nodes.values()), edges=list(edges.values()))
