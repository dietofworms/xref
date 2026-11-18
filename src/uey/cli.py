"""uey command line."""

from __future__ import annotations

import os
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated

import typer

from uey.config import DEFAULT_ENVIRONMENT, load_config
from uey.errors import UeyError
from uey.operations import age_of, publish, sync
from uey.store import open_store

app = typer.Typer(
    help="Cross-project refs for dbt v2 without the dbt platform.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectDir = Annotated[
    Path,
    typer.Option("--project-dir", help="The dbt project directory.", file_okay=False, exists=True),
]
Environment = Annotated[
    str | None,
    typer.Option(
        "--env",
        "-e",
        help=f"Environment name. Defaults to $UEY_ENV, then {DEFAULT_ENVIRONMENT!r}.",
    ),
]
StoreUrl = Annotated[
    str | None,
    typer.Option(
        "--store",
        help="Store URL or directory. Defaults to $UEY_STORE, then `store` in uey.yml.",
    ),
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"uey {package_version('uey')}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version.",
        ),
    ] = False,
) -> None:
    """Publish a producer's public models; sync them into consumers as stub packages."""


def _environment(env: str | None) -> str:
    return env or os.environ.get("UEY_ENV") or DEFAULT_ENVIRONMENT


def _store_url(store: str | None, configured: str | None) -> str:
    url = store or os.environ.get("UEY_STORE") or configured
    if not url:
        raise UeyError(
            "No store configured. Pass --store, set UEY_STORE, or set `store:` in uey.yml."
        )
    return url


def _fail(error: UeyError) -> typer.Exit:
    typer.secho(f"Error: {error}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


@app.command("publish")
def publish_command(
    project_dir: ProjectDir = Path("."),
    env: Environment = None,
    store: StoreUrl = None,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Path to manifest.json. Defaults to <project-dir>/target/manifest.json."),
    ] = None,
) -> None:
    """Publish this project's public models after a dbt run."""
    try:
        config = load_config(project_dir)
        target = open_store(_store_url(store, config.store), base_dir=project_dir)
        result = publish(
            manifest or project_dir / "target" / "manifest.json",
            target,
            _environment(env),
        )
    except UeyError as error:
        raise _fail(error) from None
    for warning in result.warnings:
        typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)
    published = result.published
    typer.echo(
        f"Published {len(published.models)} public model(s) from {published.project_name} "
        f"({published.environment}) to {result.location}"
    )


@app.command("sync")
def sync_command(
    project_dir: ProjectDir = Path("."),
    env: Environment = None,
    store: StoreUrl = None,
) -> None:
    """Fetch upstream manifests and write stub packages. Run before `dbt deps`."""
    try:
        config = load_config(project_dir)
        source = open_store(_store_url(store, config.store), base_dir=project_dir)
        result = sync(project_dir, config, source, _environment(env))
    except UeyError as error:
        raise _fail(error) from None
    for project in result.projects:
        published = project.published
        typer.echo(
            f"Synced {published.project_name} ({published.environment}, built "
            f"{age_of(published.generated_at)}): {len(published.models)} model(s) -> "
            f"{project.package_dir.relative_to(project_dir)}"
        )
    for name in result.removed:
        typer.echo(f"Removed stub package for {name}, which is no longer in uey.yml")
    if result.packages_added and result.packages_file is not None:
        typer.echo(
            f"Added {', '.join(result.packages_added)} to {result.packages_file.name}; run `dbt deps` next."
        )
