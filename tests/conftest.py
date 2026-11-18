from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
V12 = "https://schemas.getdbt.com/dbt/manifest/v12.json"


@pytest.fixture
def producer_manifest_path() -> Path:
    return FIXTURES / "producer_manifest.json"


def model_node(
    name: str,
    *,
    project: str = "core",
    access: str = "public",
    version: int | str | None = None,
    latest_version: int | str | None = None,
    deprecation_date: str | None = None,
    columns: list[tuple[str, str | None]] | None = None,
    materialized: str = "table",
) -> dict[str, Any]:
    unique_id = f"model.{project}.{name}" + (f".v{version}" if version is not None else "")
    alias = name if version is None else f"{name}_v{version}"
    return {
        "resource_type": "model",
        "unique_id": unique_id,
        "name": name,
        "package_name": project,
        "access": access,
        "database": "warehouse",
        "schema": "analytics",
        "alias": alias,
        "relation_name": None
        if materialized == "ephemeral"
        else f'"warehouse"."analytics"."{alias}"',
        "description": f"The {name} model.",
        "columns": {
            col: {"name": col, "description": "", "data_type": dtype, "meta": {}}
            for col, dtype in (columns or [("id", "integer")])
        },
        "version": version,
        "latest_version": latest_version,
        "deprecation_date": deprecation_date,
        "config": {"materialized": materialized},
    }


def manifest_dict(
    *nodes: dict[str, Any], project: str = "core", schema_version: str = V12
) -> dict[str, Any]:
    return {
        "metadata": {
            "dbt_schema_version": schema_version,
            "dbt_version": "2.0.11",
            "generated_at": "2026-11-12T04:29:41.553526242Z",
            "project_name": project,
            "adapter_type": "duckdb",
        },
        "nodes": {n["unique_id"]: n for n in nodes},
    }


def write_manifest(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
