"""Layered, public-safe collection configuration resolution.

Collection resolves only operational/discovery configuration. Analysis-specific
model/stage switches are intentionally discarded when legacy/private layers are
adapted into the modular Collection package.
"""
from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from .models import CanonicalRecord, CollectionProvenance

_LAYER_ORDER = ("project", "arena", "machine", "execution", "private", "override")
_ANALYSIS_ONLY_KEYS = {"analysis", "model", "stages", "memory_dir"}
_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "cookie",
    "credential",
    "access_key",
    "api_key",
)
_PRIVATE_LIST_KEYS = {
    "accounts",
    "candidates",
    "parties",
    "handles",
    "sources",
    "source_lists",
    "feeds",
    "web_sources",
}


@dataclass(frozen=True)
class ConfigLayer:
    """One resolved configuration layer with a safe provenance fingerprint."""

    kind: str
    source_id: str
    digest: str
    version: str = ""


@dataclass(frozen=True)
class EffectiveCollectionConfig:
    """Fully merged collection config plus safe layer provenance."""

    data: dict[str, Any]
    layers: tuple[ConfigLayer, ...]
    digest: str

    def safe_snapshot(self) -> dict[str, Any]:
        """Return an inspectable snapshot with secrets/private target lists redacted."""
        return {
            "config_version": 1,
            "effective_config_hash": self.digest,
            "layers": [
                {
                    "kind": layer.kind,
                    "source_id": layer.source_id,
                    "hash": layer.digest,
                    "version": layer.version,
                }
                for layer in self.layers
            ],
            "config": _sanitize(self.data),
        }

    def provenance_metadata(self) -> dict[str, Any]:
        """Small metadata envelope suitable for canonical record provenance."""
        window = self.data.get("window")
        storage = self.data.get("storage")
        return {
            "study": str(self.data.get("study") or self.data.get("project") or ""),
            "arena": str(self.data.get("arena") or ""),
            "machine": str(self.data.get("machine") or ""),
            "execution": str(self.data.get("execution") or ""),
            "effective_config_hash": self.digest,
            "config_layers": [
                {"kind": layer.kind, "source_id": layer.source_id, "hash": layer.digest}
                for layer in self.layers
            ],
            "window": _sanitize(window) if isinstance(window, Mapping) else {},
            "storage": _sanitize(storage) if isinstance(storage, Mapping) else {},
        }


def resolve_collection_config(
    *,
    project: str | Path | Mapping[str, Any],
    arena: str | Path | Mapping[str, Any] | None = None,
    machine: str | Path | Mapping[str, Any] | None = None,
    execution: str | Path | Mapping[str, Any] | None = None,
    private_overrides: Sequence[str | Path | Mapping[str, Any]] = (),
    overrides: Mapping[str, Any] | None = None,
) -> EffectiveCollectionConfig:
    """Resolve project -> arena -> machine -> execution -> private -> overrides.

    Later layers replace scalar/list values and recursively merge mappings. YAML
    and TOML files are supported so existing study YAML and deployment TOML can
    participate in one deterministic effective configuration.
    """
    specs: list[tuple[str, str | Path | Mapping[str, Any]]] = [("project", project)]
    if arena is not None:
        specs.append(("arena", arena))
    if machine is not None:
        specs.append(("machine", machine))
    if execution is not None:
        specs.append(("execution", execution))
    specs.extend(("private", item) for item in private_overrides)
    if overrides:
        specs.append(("override", overrides))

    merged: dict[str, Any] = {}
    layers: list[ConfigLayer] = []
    for kind, source in specs:
        raw, source_id = _load_mapping(source)
        view = _collection_view(raw, layer_kind=kind)
        merged = _deep_merge(merged, view)
        layers.append(
            ConfigLayer(
                kind=kind,
                source_id=source_id,
                digest=_digest(view),
                version=str(raw.get("version") or raw.get("config_version") or ""),
            )
        )

    kinds = [layer.kind for layer in layers]
    if kinds != sorted(kinds, key=_LAYER_ORDER.index):
        raise ValueError("collection configuration layers are out of canonical order")
    _validate_effective(merged)
    return EffectiveCollectionConfig(data=merged, layers=tuple(layers), digest=_digest(merged))


def stamp_config_provenance(
    record: CanonicalRecord,
    config: EffectiveCollectionConfig,
) -> CanonicalRecord:
    """Attach only safe configuration provenance to a canonical record."""
    metadata = {"collection_config": config.provenance_metadata()}
    if record.provenance:
        record.provenance[-1].metadata.update(metadata)
    else:
        record.provenance.append(CollectionProvenance(metadata=metadata))
    return record


def _load_mapping(source: str | Path | Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(source, Mapping):
        return deepcopy(dict(source)), "inline"
    path = Path(source)
    suffix = path.suffix.casefold()
    text = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        value = yaml.safe_load(text)
    elif suffix == ".toml":
        value = tomllib.loads(text)
    else:
        raise ValueError(f"unsupported collection config format: {path.suffix or '<none>'}")
    if not isinstance(value, dict):
        raise ValueError(f"collection config {path!s} must contain a mapping")
    # Basename only: private runtime directory structure is not provenance data.
    return {str(key): item for key, item in value.items()}, path.name


def _collection_view(data: Mapping[str, Any], *, layer_kind: str) -> dict[str, Any]:
    view = {
        str(key): deepcopy(value)
        for key, value in data.items()
        if str(key) not in _ANALYSIS_ONLY_KEYS
    }
    if "project" in view and "study" not in view:
        view["study"] = view["project"]

    dataset = view.pop("dataset", None)
    if isinstance(dataset, Mapping):
        arena_data: dict[str, Any] = {}
        for key in ("title", "paper_section", "topic_key", "platforms", "languages", "countries"):
            if key in dataset:
                arena_data[key] = deepcopy(dataset[key])
        if "collection_notes" in dataset:
            arena_data["notes"] = deepcopy(dataset["collection_notes"])
        hints = dataset.get("analytic_hints")
        if isinstance(hints, Mapping):
            arena_data["discovery_hints"] = {
                key: deepcopy(value)
                for key, value in hints.items()
                if key in {"signifiers", "actors", "formations", "governance_anchors"}
            }
        if layer_kind == "arena":
            view["arena_config"] = arena_data
        else:
            for key, value in arena_data.items():
                view.setdefault(key, value)

    return view


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def _sanitize(value: Any, *, key: str = "") -> Any:
    lowered = key.casefold()
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if lowered in _PRIVATE_LIST_KEYS and isinstance(value, (list, dict)):
        return {"redacted": True, "count": len(value)}
    if isinstance(value, Mapping):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return deepcopy(value)


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _validate_effective(data: Mapping[str, Any]) -> None:
    study = data.get("study") or data.get("project")
    if not study:
        raise ValueError("effective collection config requires a study/project ID")
    window = data.get("window")
    if isinstance(window, Mapping):
        start = window.get("start")
        end = window.get("end")
        if start and end and str(start) > str(end):
            raise ValueError("collection window start must not be after end")
    platforms = data.get("platforms")
    if platforms is not None and not isinstance(platforms, (Mapping, list)):
        raise ValueError("platforms must be a mapping or list")
