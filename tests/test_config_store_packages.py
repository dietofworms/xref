from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uey.config import Config, Upstream, load_config
from uey.errors import UeyError
from uey.packages import ensure_local_packages
from uey.store import FsspecStore, LocalStore, open_store

# --- config ---------------------------------------------------------------


def test_missing_config_is_empty(tmp_path: Path) -> None:
    assert load_config(tmp_path) == Config()


def test_projects_accept_plain_names(tmp_path: Path) -> None:
    (tmp_path / "uey.yml").write_text(
        "store: ./store\nprojects:\n  - core\n  - name: finance\n    environment: prod\n"
    )
    config = load_config(tmp_path)
    assert config.projects == [Upstream(name="core"), Upstream(name="finance", environment="prod")]


def test_unknown_config_keys_are_errors(tmp_path: Path) -> None:
    (tmp_path / "uey.yml").write_text("stor: typo\n")
    with pytest.raises(UeyError, match="stor"):
        load_config(tmp_path)


def test_invalid_project_name_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "uey.yml").write_text("projects:\n  - ../etc\n")
    with pytest.raises(UeyError, match="valid dbt project name"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("environments", "upstream", "env", "expected"),
    [
        ({}, Upstream(name="a"), "prod", ["prod"]),
        ({}, Upstream(name="a"), "dev", ["dev", "prod"]),
        ({"dev": ["staging", "prod"]}, Upstream(name="a"), "dev", ["staging", "prod"]),
        ({"dev": ["staging", "prod"]}, Upstream(name="a", environment="prod"), "dev", ["prod"]),
    ],
)
def test_environment_routing(
    environments: dict[str, list[str]], upstream: Upstream, env: str, expected: list[str]
) -> None:
    assert Config(environments=environments).environments_for(upstream, env) == expected


# --- stores ---------------------------------------------------------------


def test_local_store_round_trip(tmp_path: Path) -> None:
    store = LocalStore(tmp_path)
    assert store.read("core/prod/manifest.json") is None
    store.write("core/prod/manifest.json", b"{}")
    assert store.read("core/prod/manifest.json") == b"{}"
    assert list(tmp_path.rglob("*.tmp")) == []


def test_local_store_refuses_escaping_keys(tmp_path: Path) -> None:
    with pytest.raises(UeyError, match="escapes"):
        LocalStore(tmp_path / "store").write("../outside", b"x")


def test_fsspec_store_round_trip() -> None:
    store = open_store("memory://uey-test-bucket/prefix")
    assert isinstance(store, FsspecStore)
    assert store.read("core/prod/manifest.json") is None
    store.write("core/prod/manifest.json", b"{}")
    assert store.read("core/prod/manifest.json") == b"{}"
    assert store.describe("k") == "memory://uey-test-bucket/prefix/k"


def test_relative_local_store_resolves_against_project(tmp_path: Path) -> None:
    store = open_store("../shared", base_dir=tmp_path / "project")
    assert isinstance(store, LocalStore)
    assert store.root == tmp_path / "project" / ".." / "shared"


def test_unknown_scheme_gives_clear_error() -> None:
    with pytest.raises(UeyError, match="Cannot open store"):
        open_store("nosuchscheme://bucket")


# --- packages file --------------------------------------------------------


def _locals(path: Path) -> list[str]:
    return [p["local"] for p in yaml.safe_load(path.read_text())["packages"] if "local" in p]


def test_creates_packages_yml(tmp_path: Path) -> None:
    path, added = ensure_local_packages(tmp_path, [".mesh/core"])
    assert path.name == "packages.yml"
    assert added == [".mesh/core"]
    assert _locals(path) == [".mesh/core"]


def test_inserts_into_existing_list_keeping_comments(tmp_path: Path) -> None:
    (tmp_path / "packages.yml").write_text(
        "# our packages\npackages:\n    - package: dbt-labs/dbt_utils  # keep\n      version: 1.3.0\n"
    )
    path, _ = ensure_local_packages(tmp_path, [".mesh/core"])
    text = path.read_text()
    assert "# our packages" in text
    assert "# keep" in text
    assert "    - local: .mesh/core\n" in text
    assert _locals(path) == [".mesh/core"]


def test_existing_entry_is_left_alone(tmp_path: Path) -> None:
    original = "packages:\n  - local: ./.mesh/core/\n"
    (tmp_path / "packages.yml").write_text(original)
    _, added = ensure_local_packages(tmp_path, [".mesh/core"])
    assert added == []
    assert (tmp_path / "packages.yml").read_text() == original


def test_prefers_dependencies_yml_with_packages(tmp_path: Path) -> None:
    (tmp_path / "dependencies.yml").write_text("packages:\n  - package: x/y\n    version: 1.0.0\n")
    path, _ = ensure_local_packages(tmp_path, [".mesh/core"])
    assert path.name == "dependencies.yml"
    assert not (tmp_path / "packages.yml").exists()


def test_adds_packages_key_to_dependencies_yml(tmp_path: Path) -> None:
    (tmp_path / "dependencies.yml").write_text("projects:\n  - name: other\n")
    path, _ = ensure_local_packages(tmp_path, [".mesh/core"])
    assert path.name == "dependencies.yml"
    assert _locals(path) == [".mesh/core"]


def test_flow_style_list_falls_back_to_instructions(tmp_path: Path) -> None:
    (tmp_path / "packages.yml").write_text("packages: [{package: x/y, version: 1.0.0}]\n")
    with pytest.raises(UeyError, match=r"local: \.mesh/core"):
        ensure_local_packages(tmp_path, [".mesh/core"])
