"""Read the parts of a dbt manifest.json that uey needs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from uey._typing import as_mapping
from uey.errors import UeyError

SUPPORTED_SCHEMA_VERSIONS = frozenset({"https://schemas.getdbt.com/dbt/manifest/v12.json"})

PROJECT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Access = Literal["public", "protected", "private"]
ModelVersion = int | float | str


class Column(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    data_type: str | None = None


class ModelNode(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    unique_id: str
    name: str
    package_name: str
    access: Access = "protected"
    database: str | None = None
    schema_name: str = Field(alias="schema")
    alias: str | None = None
    relation_name: str | None = None
    description: str = ""
    columns: dict[str, Column] = Field(default_factory=dict[str, Column])
    version: ModelVersion | None = None
    latest_version: ModelVersion | None = None
    deprecation_date: str | None = None


class Metadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dbt_schema_version: str
    dbt_version: str
    generated_at: str
    project_name: str | None = None
    adapter_type: str | None = None


class Manifest(BaseModel):
    """A dbt manifest reduced to the project's own models."""

    metadata: Metadata
    project_name: str
    models: list[ModelNode]

    def public_models(self) -> list[ModelNode]:
        return [m for m in self.models if m.access == "public"]


def load_manifest(path: Path) -> Manifest:
    try:
        raw = as_mapping(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise UeyError(f"No manifest at {path}. Run `dbt parse` or `dbt build` first.") from None
    except json.JSONDecodeError as exc:
        raise UeyError(f"{path} is not valid JSON: {exc}") from None
    if raw is None:
        raise UeyError(f"{path} is not a dbt manifest.")
    return parse_manifest(raw, source=str(path))


def parse_manifest(raw: dict[str, Any], source: str = "manifest") -> Manifest:
    try:
        metadata = Metadata.model_validate(raw.get("metadata"))
    except ValidationError as exc:
        raise UeyError(f"{source} has no usable metadata block: {exc}") from None

    if metadata.dbt_schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise UeyError(
            f"{source} uses manifest schema {metadata.dbt_schema_version}; uey supports {supported}."
        )

    nodes = as_mapping(raw.get("nodes", {}))
    if nodes is None:
        raise UeyError(f"{source} has no nodes.")

    project_name = metadata.project_name or _infer_project_name(nodes)
    if not PROJECT_NAME.match(project_name):
        raise UeyError(f"{source}: project name {project_name!r} is not a valid dbt project name.")

    models: list[ModelNode] = []
    for unique_id, value in nodes.items():
        node = as_mapping(value)
        if node is None or node.get("resource_type") != "model":
            continue
        # Models from installed packages (dbt_utils and so on) belong to other projects.
        if node.get("package_name") != project_name:
            continue
        try:
            models.append(ModelNode.model_validate(node))
        except ValidationError as exc:
            raise UeyError(f"{source}: could not read {unique_id}: {exc}") from None

    models.sort(key=lambda m: m.unique_id)
    return Manifest(metadata=metadata, project_name=project_name, models=models)


def _infer_project_name(nodes: dict[str, Any]) -> str:
    """Older manifests lack metadata.project_name; fall back to the root project's nodes."""
    packages = {
        str(node.get("package_name"))
        for node in map(as_mapping, nodes.values())
        if node is not None and node.get("resource_type") == "model"
    }
    if len(packages) == 1:
        return packages.pop()
    raise UeyError("The manifest has no metadata.project_name and uey could not infer it.")
