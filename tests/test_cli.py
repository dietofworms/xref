from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tests.conftest import manifest_dict, model_node, write_manifest
from uey.cli import app

runner = CliRunner()


def _producer(tmp_path: Path, name: str = "core", relation_schema: str = "analytics") -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / "dbt_project.yml").write_text(f"name: {name}\n")
    node = model_node("orders", project=name)
    node["relation_name"] = f'"warehouse"."{relation_schema}"."orders"'
    write_manifest(project / "target" / "manifest.json", manifest_dict(node, project=name))
    return project


def _consumer(tmp_path: Path, config: str) -> Path:
    project = tmp_path / "consumer"
    project.mkdir()
    (project / "dbt_project.yml").write_text("name: consumer\n")
    (project / "uey.yml").write_text(config)
    return project


def _run(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_publish_then_sync(tmp_path: Path) -> None:
    store = tmp_path / "store"
    producer = _producer(tmp_path)
    out = _run("publish", "--project-dir", str(producer), "--store", str(store))
    assert "Published 1 public model(s) from core (prod)" in out

    published = json.loads((store / "core" / "prod" / "manifest.json").read_text())
    assert published["format_version"] == 1
    assert [m["name"] for m in published["models"]] == ["orders"]

    consumer = _consumer(tmp_path, f"store: {store}\nprojects: [core]\n")
    out = _run("sync", "--project-dir", str(consumer))
    assert "Synced core (prod" in out
    assert "run `dbt deps` next" in out

    sql = (consumer / ".mesh" / "core" / "models" / "orders.sql").read_text()
    assert 'select * from "warehouse"."analytics"."orders"' in sql
    packages = yaml.safe_load((consumer / "packages.yml").read_text())
    assert packages == {"packages": [{"local": ".mesh/core"}]}

    # A second sync changes nothing in packages.yml and does not ask for deps again.
    out = _run("sync", "--project-dir", str(consumer))
    assert "dbt deps" not in out


def test_dev_falls_back_to_prod_then_prefers_dev(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _run("publish", "--project-dir", str(_producer(tmp_path)), "--store", str(store))
    consumer = _consumer(tmp_path, f"store: {store}\nprojects: [core]\n")

    _run("sync", "--project-dir", str(consumer), "--env", "dev")
    marker = yaml.safe_load((consumer / ".mesh" / "core" / ".uey.json").read_text())
    assert marker["environment"] == "prod"

    shutil.rmtree(tmp_path / "core")
    dev_producer = _producer(tmp_path, relation_schema="dbt_dev")
    _run("publish", "--project-dir", str(dev_producer), "--store", str(store), "--env", "dev")
    _run("sync", "--project-dir", str(consumer), "--env", "dev")
    sql = (consumer / ".mesh" / "core" / "models" / "orders.sql").read_text()
    assert '"dbt_dev"' in sql


def test_store_and_env_from_environment_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store"
    monkeypatch.setenv("UEY_STORE", str(store))
    monkeypatch.setenv("UEY_ENV", "staging")
    _run("publish", "--project-dir", str(_producer(tmp_path)))
    assert (store / "core" / "staging" / "manifest.json").exists()


def test_sync_reports_missing_manifest(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path, f"store: {tmp_path / 'store'}\nprojects: [core]\n")
    result = runner.invoke(app, ["sync", "--project-dir", str(consumer), "--env", "dev"])
    assert result.exit_code == 1
    assert "No published manifest for core" in result.output
    assert "core/dev/manifest.json" in result.output
    assert "core/prod/manifest.json" in result.output


def test_sync_removes_packages_dropped_from_config(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _run("publish", "--project-dir", str(_producer(tmp_path, "core")), "--store", str(store))
    _run("publish", "--project-dir", str(_producer(tmp_path, "finance")), "--store", str(store))
    consumer = _consumer(tmp_path, f"store: {store}\nprojects: [core, finance]\n")
    _run("sync", "--project-dir", str(consumer))

    (consumer / "uey.yml").write_text(f"store: {store}\nprojects: [core]\n")
    out = _run("sync", "--project-dir", str(consumer))
    assert "Removed stub package for finance" in out
    assert not (consumer / ".mesh" / "finance").exists()
    packages = yaml.safe_load((consumer / "packages.yml").read_text())
    assert packages == {"packages": [{"local": ".mesh/core"}]}

    # Dropping the last project leaves a valid, empty list, and adding it back works.
    (consumer / "uey.yml").write_text(f"store: {store}\nprojects: [finance]\n")
    _run("sync", "--project-dir", str(consumer))
    packages = yaml.safe_load((consumer / "packages.yml").read_text())
    assert packages == {"packages": [{"local": ".mesh/finance"}]}


def test_sync_will_not_overwrite_a_folder_it_did_not_create(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _run("publish", "--project-dir", str(_producer(tmp_path)), "--store", str(store))
    consumer = _consumer(tmp_path, f"store: {store}\nprojects: [core]\n")
    (consumer / ".mesh" / "core").mkdir(parents=True)
    (consumer / ".mesh" / "core" / "mine.sql").write_text("select 1")

    result = runner.invoke(app, ["sync", "--project-dir", str(consumer)])
    assert result.exit_code == 1
    assert "not created by uey" in result.output
    assert (consumer / ".mesh" / "core" / "mine.sql").exists()


def test_project_cannot_be_its_own_upstream(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path, f"store: {tmp_path}\nprojects: [consumer]\n")
    result = runner.invoke(app, ["sync", "--project-dir", str(consumer)])
    assert result.exit_code == 1
    assert "own name" in result.output


def test_missing_store_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UEY_STORE", raising=False)
    result = runner.invoke(app, ["publish", "--project-dir", str(_producer(tmp_path))])
    assert result.exit_code == 1
    assert "No store configured" in result.output


def test_failed_fetch_leaves_existing_packages_untouched(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _run("publish", "--project-dir", str(_producer(tmp_path, "core")), "--store", str(store))
    consumer = _consumer(tmp_path, f"store: {store}\nprojects: [core]\n")
    _run("sync", "--project-dir", str(consumer))
    marker = consumer / ".mesh" / "core" / ".uey.json"
    before = marker.read_text()

    (consumer / "uey.yml").write_text(f"store: {store}\nprojects: [core, missing]\n")
    result = runner.invoke(app, ["sync", "--project-dir", str(consumer)])
    assert result.exit_code == 1
    assert "No published manifest for missing" in result.output
    assert marker.read_text() == before
