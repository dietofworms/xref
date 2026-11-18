# uey

Cross-project refs for dbt v2. See README.md for usage and spike/FINDINGS.md
for the dbt behaviour the design relies on.

## Commits

- Commit as the repository owner: `Steve Karmaniolos
  <28944297+dietofworms@users.noreply.github.com>`.
- Do not add `Co-Authored-By` or `Claude-Session` trailers to commit messages,
  and no attribution footer in pull request descriptions.

## Checks

Run before every commit:

```
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
```

`pytest -m dbt` runs real dbt builds against DuckDB; dbt v2 downloads its
DuckDB driver from public.cdn.getdbt.com on first use.

## Layout

- `src/uey/manifest.py`: reads dbt manifest.json (schema v12 only).
- `src/uey/published.py`: the slim manifest format in the store.
- `src/uey/stubs.py`: renders the stub dbt package.
- `src/uey/store.py`: `ManifestStore` protocol; local and fsspec stores.
- `src/uey/config.py`: `uey.yml`.
- `src/uey/packages.py`: edits the consumer's packages file as text.
- `src/uey/operations.py`: publish and sync.
- `src/uey/cli.py`: Typer CLI.
