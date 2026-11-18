"""uey.yml: per-project settings, read from the dbt project directory.

store: s3://analytics-artifacts/uey      # where manifests are published
projects:                                # upstream projects this one refs
  - core_platform
  - name: finance
    environment: prod                    # always read this environment
environments:                            # which upstream environments each
  dev: [staging, prod]                   # local environment reads, in order
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from uey._typing import as_list
from uey.errors import UeyError
from uey.manifest import PROJECT_NAME

CONFIG_FILE = "uey.yml"
DEFAULT_ENVIRONMENT = "prod"


class Upstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    environment: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not PROJECT_NAME.match(value):
            raise ValueError(f"{value!r} is not a valid dbt project name")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store: str | None = None
    projects: list[Upstream] = []
    environments: dict[str, list[str]] = {}
    mesh_dir: str = ".mesh"

    @field_validator("projects", mode="before")
    @classmethod
    def _names_as_strings(cls, value: Any) -> Any:
        items = as_list(value)
        if items is None:
            return value
        return [{"name": v} if isinstance(v, str) else v for v in items]

    def environments_for(self, upstream: Upstream, environment: str) -> list[str]:
        """The upstream environments to try, in order, when running in `environment`."""
        if upstream.environment is not None:
            return [upstream.environment]
        if environment in self.environments:
            return self.environments[environment]
        if environment == DEFAULT_ENVIRONMENT:
            return [DEFAULT_ENVIRONMENT]
        return [environment, DEFAULT_ENVIRONMENT]


def load_config(project_dir: Path) -> Config:
    path = project_dir / CONFIG_FILE
    if not path.exists():
        return Config()
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise UeyError(f"{path} is not valid YAML: {exc}") from None
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise UeyError(f"{path} is not a valid uey config:\n{exc}") from None
