"""The slim manifest that `uey publish` writes and `uey sync` reads.

It holds only what consumers need: the producer's public models, where they
live in the warehouse, and their documentation. `format_version` changes
whenever a change would break older readers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from uey.errors import UeyError
from uey.manifest import PROJECT_NAME, Column, Manifest, ModelVersion

FORMAT_VERSION = 1


class PublishedColumn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    data_type: str | None = None


class PublishedModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    relation_name: str
    description: str = ""
    columns: list[PublishedColumn] = []
    version: ModelVersion | None = None
    latest_version: ModelVersion | None = None
    deprecation_date: str | None = None

    @property
    def file_stem(self) -> str:
        return self.name if self.version is None else f"{self.name}_v{self.version}"


class PublishedManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format_version: Literal[1] = FORMAT_VERSION
    project_name: str
    environment: str
    dbt_version: str
    adapter_type: str | None = None
    generated_at: str
    published_at: str
    models: list[PublishedModel]

    @field_validator("project_name")
    @classmethod
    def _valid_project_name(cls, value: str) -> str:
        if not PROJECT_NAME.match(value):
            raise ValueError(f"{value!r} is not a valid dbt project name")
        return value


def from_manifest(
    manifest: Manifest, environment: str, now: datetime | None = None
) -> tuple[PublishedManifest, list[str]]:
    """Build the published manifest. Returns it with a list of warnings."""
    warnings: list[str] = []
    models: list[PublishedModel] = []
    for node in manifest.public_models():
        if node.relation_name is None:
            warnings.append(
                f"{node.unique_id} is public but has no relation (ephemeral?); consumers cannot use it."
            )
            continue
        models.append(
            PublishedModel(
                name=node.name,
                relation_name=node.relation_name,
                description=node.description,
                columns=[_column(c) for c in node.columns.values()],
                version=node.version,
                latest_version=node.latest_version,
                deprecation_date=node.deprecation_date,
            )
        )
    if not models:
        warnings.append(
            f"{manifest.project_name} has no public models; set `access: public` on the models consumers need."
        )

    published = PublishedManifest(
        project_name=manifest.project_name,
        environment=environment,
        dbt_version=manifest.metadata.dbt_version,
        adapter_type=manifest.metadata.adapter_type,
        generated_at=manifest.metadata.generated_at,
        published_at=(now or datetime.now(UTC)).isoformat(),
        models=sorted(models, key=_sort_key),
    )
    return published, warnings


def _sort_key(model: PublishedModel) -> tuple[str, int, float, str]:
    """Order by name, then numerically by version where versions are numbers."""
    version = model.version
    if version is None:
        return (model.name, 0, 0.0, "")
    try:
        return (model.name, 1, float(version), "")
    except ValueError:
        return (model.name, 2, 0.0, str(version))


def _column(column: Column) -> PublishedColumn:
    return PublishedColumn(
        name=column.name, description=column.description, data_type=column.data_type
    )


def parse_published(data: bytes, source: str) -> PublishedManifest:
    try:
        return PublishedManifest.model_validate_json(data)
    except ValueError as exc:
        raise UeyError(f"{source} is not a manifest uey can read: {exc}") from None
