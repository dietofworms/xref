"""End to end against real dbt and DuckDB: build producer, publish, sync, build consumer.

Uses `dbt` from the environment, or the command in $UEY_DBT (for example
`uvx --from dbt==2.0.11 dbt` to test the proprietary distribution).
Run with `pytest -m dbt`; skipped when no dbt is available.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from uey.cli import app

pytestmark = pytest.mark.dbt

SPIKE = Path(__file__).parent.parent / "spike"
DBT_FLAGS = ["--no-version-check", "--no-send-anonymous-usage-stats", "--profiles-dir", "."]

VERSIONED_YML = """
models:
  - name: customer_tiers
    description: "{% raw %}Tiers, with {{ braces }} kept literally{% endraw %}"
    latest_version: 2
    config:
      access: public
    versions:
      - v: 1
        deprecation_date: 2027-01-01
      - v: 2
    columns:
      - name: customer_id
      - name: tier
"""


def _dbt_command() -> list[str]:
    if configured := os.environ.get("UEY_DBT"):
        return shlex.split(configured)
    found = shutil.which("dbt") or shutil.which("dbt", path=str(Path(sys.executable).parent))
    if found is None:
        pytest.skip("dbt is not installed")
    return [found]


def _dbt(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*_dbt_command(), *args, *DBT_FLAGS],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _copy_project(name: str, dest: Path) -> Path:
    project = dest / name
    shutil.copytree(
        SPIKE / name,
        project,
        ignore=shutil.ignore_patterns(
            ".mesh",
            "target",
            "dbt_packages",
            "logs",
            "packages.yml",
            "package-lock.yml",
            ".user.yml",
        ),
    )
    return project


def test_publish_sync_build(tmp_path: Path) -> None:
    producer = _copy_project("producer", tmp_path)
    (producer / "models" / "customer_tiers_v1.sql").write_text(
        "select customer_id, 'all' as tier from {{ ref('stg_customers') }}\n"
    )
    (producer / "models" / "customer_tiers_v2.sql").write_text(
        "select customer_id, case when customer_id < 3 then 'early' else 'late' end as tier\n"
        "from {{ ref('stg_customers') }}\n"
    )
    (producer / "models" / "customer_tiers.yml").write_text(VERSIONED_YML)
    _dbt(producer, "build")

    runner = CliRunner()
    store = tmp_path / "store"
    published = runner.invoke(
        app, ["publish", "--project-dir", str(producer), "--store", str(store)]
    )
    assert published.exit_code == 0, published.output

    consumer = _copy_project("consumer", tmp_path)
    (consumer / "uey.yml").write_text(f"store: {store}\nprojects: [producer]\n")
    (consumer / "models" / "tier_check.sql").write_text(
        "select v1.customer_id, v1.tier as old_tier, v2.tier as new_tier\n"
        "from {{ ref('producer', 'customer_tiers', v=1) }} as v1\n"
        "join {{ ref('producer', 'customer_tiers') }} as v2 using (customer_id)\n"
    )
    synced = runner.invoke(app, ["sync", "--project-dir", str(consumer)])
    assert synced.exit_code == 0, synced.output

    _dbt(consumer, "deps")
    build = _dbt(consumer, "build")
    assert "no-op" in build.stdout

    manifest = json.loads((consumer / "target" / "manifest.json").read_text())
    assert set(manifest["parent_map"]["model.consumer.customer_segments"]) == {
        "model.producer.dim_customers",
        "model.producer.fct_orders",
    }
    stub = manifest["nodes"]["model.producer.customer_tiers.v2"]
    assert stub["description"] == "Tiers, with {{ braces }} kept literally"
    assert set(manifest["parent_map"]["model.consumer.tier_check"]) == {
        "model.producer.customer_tiers.v1",
        "model.producer.customer_tiers.v2",
    }

    with duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True) as db:
        segments = db.sql("select count(*) from marts.customer_segments").fetchall()
        tiers = db.sql("select count(*) from marts.tier_check where new_tier = 'early'").fetchall()
        stub_objects = db.sql(
            "select count(*) from information_schema.tables where table_schema = 'marts' "
            "and table_name in ('dim_customers', 'fct_orders', 'customer_tiers_v1')"
        ).fetchall()
    assert segments == [(5,)]
    assert tiers == [(2,)]
    assert stub_objects == [(0,)]
