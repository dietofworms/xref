from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import manifest_dict, model_node, write_manifest
from uey.errors import UeyError
from uey.manifest import Column, load_manifest, parse_manifest


def test_column_with_declared_type() -> None:
    column = Column.model_validate(
        {"name": "customer_id", "data_type": "integer", "description": "Primary key.", "meta": {}}
    )
    assert column.data_type == "integer"
    assert column.description == "Primary key."


def test_column_without_declared_type() -> None:
    column = Column.model_validate({"name": "order_id", "data_type": None, "description": ""})
    assert column.data_type is None


def test_loads_real_dbt_v2_manifest(producer_manifest_path: Path) -> None:
    manifest = load_manifest(producer_manifest_path)

    assert manifest.project_name == "producer"
    assert [m.name for m in manifest.public_models()] == ["dim_customers", "fct_orders"]

    dim = next(m for m in manifest.models if m.name == "dim_customers")
    assert dim.relation_name == '"warehouse"."core"."dim_customers"'
    assert dim.schema_name == "core"
    assert list(dim.columns) == [
        "customer_id",
        "first_name",
        "last_name",
        "email",
        "signup_date",
        "order_count",
        "lifetime_value",
    ]
    assert dim.columns["lifetime_value"].data_type == "decimal(12, 2)"

    stg = next(m for m in manifest.models if m.name == "stg_customers")
    assert stg.access == "protected"


def test_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "manifest.json",
        manifest_dict(schema_version="https://schemas.getdbt.com/dbt/manifest/v20.json"),
    )
    with pytest.raises(UeyError, match="v20"):
        load_manifest(path)


def test_missing_manifest_says_what_to_run(tmp_path: Path) -> None:
    with pytest.raises(UeyError, match="dbt parse"):
        load_manifest(tmp_path / "manifest.json")


def test_ignores_models_from_installed_packages() -> None:
    manifest = parse_manifest(
        manifest_dict(model_node("orders"), model_node("utils_model", project="dbt_utils"))
    )
    assert [m.name for m in manifest.models] == ["orders"]


def test_infers_project_name_when_metadata_lacks_it() -> None:
    raw = manifest_dict(model_node("orders"))
    del raw["metadata"]["project_name"]
    assert parse_manifest(raw).project_name == "core"


def test_reads_versions_of_mixed_types() -> None:
    manifest = parse_manifest(
        manifest_dict(
            model_node("orders", version=1, latest_version=2),
            model_node("orders", version="2", latest_version=2),
        )
    )
    assert sorted(str(m.version) for m in manifest.models) == ["1", "2"]
