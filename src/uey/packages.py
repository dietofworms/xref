"""Make sure the consumer's packages file points at the generated stub packages.

dbt reads packages from `dependencies.yml` or `packages.yml` (not both). The
file is edited as text, inserting lines under `packages:`, so the user's
comments and formatting survive.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from uey._typing import as_list, as_mapping
from uey.errors import UeyError

_PACKAGES_KEY = re.compile(r"^packages:[ \t]*(#.*)?$")
_EMPTY_PACKAGES = re.compile(r"^packages:[ \t]*\[[ \t]*\][ \t]*(#.*)?$")
_LOCAL_ITEM = re.compile(r"""^[ \t]*-[ \t]*local:[ \t]*['"]?([^'"#]*?)['"]?[ \t]*(#.*)?$""")
_LIST_ITEM = re.compile(r"^([ \t]*)-[ \t]")


def packages_file(project_dir: Path) -> Path:
    dependencies = project_dir / "dependencies.yml"
    packages = project_dir / "packages.yml"
    if dependencies.exists() and _has_packages_key(dependencies):
        return dependencies
    if packages.exists():
        return packages
    if dependencies.exists():
        return dependencies
    return packages


def ensure_local_packages(project_dir: Path, local_paths: list[str]) -> tuple[Path, list[str]]:
    """Add a `local:` entry for each path that is missing. Returns the file and the paths added."""
    path = packages_file(project_dir)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = _existing_local_paths(text, path)
    missing = [p for p in local_paths if _normalise(p) not in existing]
    if not missing:
        return path, []

    new_lines = [f"local: {p}" for p in missing]
    # `packages: []` (as left by remove_local_packages) becomes a block list we can extend.
    lines = [
        "packages:\n" if _EMPTY_PACKAGES.match(line.rstrip("\r\n")) else line
        for line in text.splitlines(keepends=True)
    ]
    text = "".join(lines)
    key_index = next(
        (i for i, line in enumerate(lines) if _PACKAGES_KEY.match(line.rstrip("\r\n"))),
        None,
    )

    if key_index is None and "packages" in _load(text, path):
        # `packages:` exists but not as a block list we can safely insert into.
        raise _manual_edit_error(path, missing)
    if key_index is None:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "packages:\n" + "".join(f"  - {line}\n" for line in new_lines)
    else:
        indent = _item_indent(lines[key_index + 1 :])
        insert = [f"{indent}- {line}\n" for line in new_lines]
        lines[key_index + 1 : key_index + 1] = insert
        text = "".join(lines)

    _check_parses(text, path, missing)
    path.write_text(text, encoding="utf-8")
    return path, missing


def remove_local_packages(project_dir: Path, local_paths: list[str]) -> list[str]:
    """Remove single-line `- local: <path>` entries. Returns the paths removed.

    Raises before changing anything if an entry is written in a form uey cannot
    remove safely, so the caller can stop before deleting the package folder.
    """
    path = packages_file(project_dir)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    targets = {_normalise(p) for p in local_paths}
    present = targets & _existing_local_paths(text, path)
    if not present:
        return []

    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _LOCAL_ITEM.match(line.rstrip("\r\n"))
        if match and _normalise(match.group(1)) in present:
            continue
        kept.append(line)
    new_text = "".join(kept)

    if present & _existing_local_paths(new_text, path):
        lines = "".join(f"  - local: {p}\n" for p in sorted(present))
        raise UeyError(
            f"Could not remove stub packages from {path} automatically. Delete these entries:\n{lines}"
        )
    if "packages" in _load(new_text, path) and _load(new_text, path)["packages"] is None:
        # An empty `packages:` key parses as null, which dbt rejects.
        new_text = "".join(
            "packages: []\n" if _PACKAGES_KEY.match(line.rstrip("\r\n")) else line
            for line in new_text.splitlines(keepends=True)
        )
    path.write_text(new_text, encoding="utf-8")
    return sorted(present)


def _has_packages_key(path: Path) -> bool:
    data = _load(path.read_text(encoding="utf-8"), path)
    return "packages" in data


def _load(text: str, path: Path) -> dict[str, Any]:
    try:
        data = as_mapping(yaml.safe_load(text) or {})
    except yaml.YAMLError as exc:
        raise UeyError(f"{path} is not valid YAML: {exc}") from None
    if data is None:
        raise UeyError(f"{path} should be a YAML mapping.")
    return data


def _existing_local_paths(text: str, path: Path) -> set[str]:
    packages = as_list(_load(text, path).get("packages") or [])
    if packages is None:
        raise UeyError(f"`packages` in {path} should be a list.")
    entries = [as_mapping(p) for p in packages]
    return {_normalise(str(e["local"])) for e in entries if e is not None and "local" in e}


def _normalise(path: str) -> str:
    return path.strip().removeprefix("./").rstrip("/")


def _item_indent(lines_after_key: list[str]) -> str:
    for line in lines_after_key:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LIST_ITEM.match(line)
        return match.group(1) if match else "  "
    return "  "


def _check_parses(text: str, path: Path, added: list[str]) -> None:
    if not {_normalise(p) for p in added} <= _existing_local_paths(text, path):
        raise _manual_edit_error(path, added)


def _manual_edit_error(path: Path, paths: list[str]) -> UeyError:
    snippet = "".join(f"  - local: {p}\n" for p in paths)
    return UeyError(
        f"Could not add the stub packages to {path} automatically. Add these under `packages:`:\n{snippet}"
    )
