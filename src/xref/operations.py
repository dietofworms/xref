"""The two operations behind the CLI: publish and sync."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from xref._typing import as_mapping
from xref.config import Config
from xref.errors import XrefError
from xref.manifest import load_manifest
from xref.packages import ensure_local_packages, remove_local_packages
from xref.published import PublishedManifest, from_manifest, parse_published
from xref.store import ManifestStore, manifest_key
from xref.stubs import render_stub_package

MARKER_FILE = ".xref.json"


@dataclass
class PublishResult:
    published: PublishedManifest
    location: str
    warnings: list[str]


def publish(
    manifest_path: Path,
    store: ManifestStore,
    environment: str,
    now: datetime | None = None,
) -> PublishResult:
    manifest = load_manifest(manifest_path)
    published, warnings = from_manifest(manifest, environment, now)
    key = manifest_key(published.project_name, environment)
    store.write(key, published.model_dump_json(indent=2).encode())
    return PublishResult(published=published, location=store.describe(key), warnings=warnings)


@dataclass
class SyncedProject:
    published: PublishedManifest
    source: str
    package_dir: Path


@dataclass
class SyncResult:
    projects: list[SyncedProject]
    packages_file: Path | None
    packages_added: list[str]
    removed: list[str] = field(default_factory=list[str])


def sync(project_dir: Path, config: Config, store: ManifestStore, environment: str) -> SyncResult:
    if not config.projects:
        raise XrefError(
            f"No upstream projects listed under `projects:` in {project_dir / 'xref.yml'}."
        )

    own_name = _own_project_name(project_dir)
    mesh_dir = project_dir / config.mesh_dir
    synced: list[SyncedProject] = []

    # Fetch every upstream before writing anything, so one missing manifest
    # does not leave some packages updated and others stale.
    for upstream in config.projects:
        if upstream.name == own_name:
            raise XrefError(
                f"{upstream.name} is this project's own name; it cannot be its own upstream."
            )
        published, source = _fetch(
            store, upstream.name, config.environments_for(upstream, environment)
        )
        if published.project_name != upstream.name:
            raise XrefError(
                f"{source} holds project {published.project_name!r}, expected {upstream.name!r}."
            )
        synced.append(
            SyncedProject(published=published, source=source, package_dir=mesh_dir / upstream.name)
        )

    for project in synced:
        _write_package(project.package_dir, project.published, project.source)

    removed = _remove_stale(project_dir, mesh_dir, {u.name for u in config.projects})
    rel_paths = [p.package_dir.relative_to(project_dir).as_posix() for p in synced]
    packages_path, added = ensure_local_packages(project_dir, rel_paths)
    return SyncResult(
        projects=synced,
        packages_file=packages_path,
        packages_added=added,
        removed=removed,
    )


def _fetch(
    store: ManifestStore, project: str, environments: list[str]
) -> tuple[PublishedManifest, str]:
    tried: list[str] = []
    for env in environments:
        key = manifest_key(project, env)
        data = store.read(key)
        location = store.describe(key)
        if data is not None:
            return parse_published(data, location), location
        tried.append(location)
    raise XrefError(
        f"No published manifest for {project}. Tried:\n"
        + "\n".join(f"  {t}" for t in tried)
        + f"\nHas {project} run `xref publish`?"
    )


def _write_package(package_dir: Path, published: PublishedManifest, source: str) -> None:
    if package_dir.exists() and not (package_dir / MARKER_FILE).exists():
        raise XrefError(
            f"{package_dir} exists and was not created by xref; move it before syncing."
        )
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    # Build the new package beside the old one, then swap, so a failed sync
    # never leaves a half-written package behind.
    staging = Path(tempfile.mkdtemp(dir=package_dir.parent, prefix=f".{package_dir.name}-"))
    try:
        for rel, content in render_stub_package(published).items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        marker: dict[str, Any] = {
            "source": source,
            "environment": published.environment,
            "generated_at": published.generated_at,
            "published_at": published.published_at,
        }
        (staging / MARKER_FILE).write_text(
            yaml.safe_dump(marker, sort_keys=False), encoding="utf-8"
        )
        if package_dir.exists():
            shutil.rmtree(package_dir)
        staging.rename(package_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _remove_stale(project_dir: Path, mesh_dir: Path, keep: set[str]) -> list[str]:
    """Delete stub packages for projects no longer in xref.yml, and their packages entries."""
    if not mesh_dir.exists():
        return []
    stale = [
        child
        for child in sorted(mesh_dir.iterdir())
        if child.is_dir() and child.name not in keep and (child / MARKER_FILE).exists()
    ]
    # Remove the packages entries first: if that fails, the folders stay and dbt deps still works.
    remove_local_packages(project_dir, [c.relative_to(project_dir).as_posix() for c in stale])
    for child in stale:
        shutil.rmtree(child)
    return [c.name for c in stale]


def _own_project_name(project_dir: Path) -> str | None:
    path = project_dir / "dbt_project.yml"
    if not path.exists():
        raise XrefError(
            f"No dbt_project.yml in {project_dir}. Run xref from the dbt project directory or pass --project-dir."
        )
    try:
        data = as_mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except yaml.YAMLError as exc:
        raise XrefError(f"{path} is not valid YAML: {exc}") from None
    name = data.get("name") if data is not None else None
    return name if isinstance(name, str) else None


def age_of(timestamp: str, now: datetime | None = None) -> str:
    """'3h ago' style age for a manifest timestamp, or the raw value if unparseable."""
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = int(((now or datetime.now(UTC)) - then).total_seconds())
    if seconds < 0:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"
