# xref

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

- `src/xref/manifest.py`: reads dbt manifest.json (schema v12 only).
- `src/xref/published.py`: the slim manifest format in the store.
- `src/xref/stubs.py`: renders the stub dbt package.
- `src/xref/store.py`: `ManifestStore` protocol; local and fsspec stores.
- `src/xref/config.py`: `xref.yml`.
- `src/xref/packages.py`: edits the consumer's packages file as text.
- `src/xref/operations.py`: publish and sync.
- `src/xref/cli.py`: Typer CLI.
