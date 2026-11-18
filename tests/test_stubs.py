from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from tests.conftest import manifest_dict, model_node
from xref.manifest import load_manifest, parse_manifest
from xref.published import PublishedManifest, from_manifest
from xref.stubs import MODELS_YAML, render_stub_package

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _publish(raw: dict[str, Any]) -> PublishedManifest:
    published, _ = from_manifest(parse_manifest(raw), "prod", NOW)
    return published


def test_stub_package_for_real_manifest(producer_manifest_path: Path) -> None:
    published, warnings = from_manifest(load_manifest(producer_manifest_path), "prod", NOW)
    files = render_stub_package(published)

    assert warnings == []
    assert set(files) == {
        PurePosixPath("dbt_project.yml"),
        PurePosixPath("models/dim_customers.sql"),
        PurePosixPath("models/fct_orders.sql"),
        MODELS_YAML,
    }
    assert yaml.safe_load(files[PurePosixPath("dbt_project.yml")])["name"] == "producer"

    sql = files[PurePosixPath("models/dim_customers.sql")]
    assert "{{ config(materialized='ephemeral') }}" in sql
    assert sql.endswith('select * from "warehouse"."core"."dim_customers"\n')

    models = yaml.safe_load(files[MODELS_YAML])["models"]
    dim = next(m for m in models if m["name"] == "dim_customers")
    assert dim["config"] == {"access": "public"}
    assert dim["columns"][0] == {
        "name": "customer_id",
        "description": "Primary key.",
        "data_type": "integer",
    }


def test_stubs_carry_no_tests_or_contracts(producer_manifest_path: Path) -> None:
    published, _ = from_manifest(load_manifest(producer_manifest_path), "prod", NOW)
    text = render_stub_package(published)[MODELS_YAML]
    assert "tests" not in text
    assert "contract" not in text


def test_only_public_models_are_published() -> None:
    published = _publish(
        manifest_dict(model_node("orders"), model_node("stg_orders", access="protected"))
    )
    assert [m.name for m in published.models] == ["orders"]


def test_public_ephemeral_model_is_skipped_with_warning() -> None:
    published, warnings = from_manifest(
        parse_manifest(manifest_dict(model_node("orders", materialized="ephemeral"))), "prod", NOW
    )
    assert published.models == []
    assert any("no relation" in w for w in warnings)


def test_versioned_model_gets_one_file_per_version() -> None:
    published = _publish(
        manifest_dict(
            model_node(
                "orders", version=1, latest_version=2, deprecation_date="2026-12-31T00:00:00Z"
            ),
            model_node("orders", version=2, latest_version=2, columns=[("id", "bigint")]),
            model_node("orders", version=10, latest_version=2),
        )
    )
    files = render_stub_package(published)

    assert PurePosixPath("models/orders_v1.sql") in files
    assert PurePosixPath("models/orders_v2.sql") in files
    assert '"orders_v1"' in files[PurePosixPath("models/orders_v1.sql")]

    (entry,) = yaml.safe_load(files[MODELS_YAML])["models"]
    assert entry["latest_version"] == 2
    assert entry["versions"] == [
        {"v": 1, "deprecation_date": "2026-12-31T00:00:00Z"},
        {"v": 2},
        {"v": 10},
    ]
    assert entry["columns"] == [{"name": "id", "data_type": "bigint"}]


def test_rendering_is_deterministic() -> None:
    raw = manifest_dict(model_node("b"), model_node("a"))
    assert render_stub_package(_publish(raw)) == render_stub_package(_publish(raw))


def test_relation_names_pass_through_as_the_warehouse_quotes_them() -> None:
    bigquery = model_node("orders")
    bigquery["relation_name"] = "`my-gcp-project`.`analytics`.`orders`"
    snowflake = model_node("customers")
    snowflake["relation_name"] = 'ANALYTICS.CORE."Customers"'
    files = render_stub_package(_publish(manifest_dict(bigquery, snowflake)))
    assert files[PurePosixPath("models/orders.sql")].endswith(
        "select * from `my-gcp-project`.`analytics`.`orders`\n"
    )
    assert files[PurePosixPath("models/customers.sql")].endswith(
        'select * from ANALYTICS.CORE."Customers"\n'
    )


def test_braces_in_descriptions_are_not_evaluated() -> None:
    node = model_node("orders")
    node["description"] = "Use {{ var }} literally"
    node["columns"]["id"]["description"] = "{% not jinja %}"
    entry = yaml.safe_load(render_stub_package(_publish(manifest_dict(node)))[MODELS_YAML])
    (model,) = entry["models"]
    assert model["description"] == "{% raw %}Use {{ var }} literally{% endraw %}"
    assert model["columns"][0]["description"] == "{% raw %}{% not jinja %}{% endraw %}"
