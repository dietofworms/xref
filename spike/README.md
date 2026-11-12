# Phase 0 spike

Goal: find out whether dbt v2 resolves `ref('producer', 'dim_customers')` through a
hand-written stub package, before any `uey` code exists. Each experiment below has
something to do, something to look for, and something to write down in
[FINDINGS.md](FINDINGS.md).

## Layout

```
spike/
  Makefile            make producer | make consumer | make compile-consumer | make query Q="..." | make clean
  warehouse.duckdb    created by the first build; shared by both projects (git-ignored)
  producer/           seeds are done; you write the models
  consumer/           you write the stub package, packages.yml and models
```

Both projects write to one DuckDB file, `warehouse`. Seeds land in schema
`core_raw`, producer models in `core`, consumer models in `marts`. A producer
table is therefore `warehouse.core.<name>`.

Run everything from `spike/` through the Makefile. The DuckDB path in each
`profiles.yml` is relative to the directory dbt runs in, and the Makefile `cd`s
into the right one.

dbt v2 is `dbt-oss` 2.0.11 from PyPI, installed by `uv sync`. Its DuckDB driver
downloads from `public.cdn.getdbt.com` on first use.

## Experiments

### 1. Build the producer

Write four models in `producer/models/`:

- `stg_customers` and `stg_orders`: light cleanup over the seeds. Leave access at the default.
- `dim_customers`: one row per customer with order counts and lifetime value. Mark it `access: public` and give it an enforced contract (`contract: {enforced: true}` with every column's `data_type`).
- `fct_orders`: one row per order. `access: public`, no contract.

Run `make producer`.

Look for: where `manifest.json` lands, the value of `metadata.dbt_schema_version`,
and how `access`, `contract`, `columns` and `relation_name` appear on the
`dim_customers` node. `publish` will read exactly these fields, so this is the
input to Phase 1.

### 2. Hand-write the stub package

In `consumer/.mesh/producer/` create:

- `dbt_project.yml` with `name: producer`.
- One `.sql` file per public model, ephemeral, selecting from the producer's real relation.
- A YAML file with descriptions, columns and `access: public`. Leave contracts out for now.

Point `consumer/packages.yml` at it with a `local:` entry.

Look for: what `dbt deps` does with a local package in v2 (copy, symlink or
nothing) and whether the package name has to match the folder name.

### 3. Reference it

Write `consumer/models/customer_segments.sql` using
`{{ ref('producer', 'dim_customers') }}` and `fct_orders`. Run `make compile-consumer`.

Look for: the compiled SQL under `consumer/target/`. Is it a CTE over
`warehouse.core.dim_customers`? Any warnings from v2's static analysis about a
relation or column it cannot resolve?

### 4. Lineage

Look for: does `model.producer.dim_customers` appear in the consumer manifest's
`parent_map` for `customer_segments`? Try `uv run dbt ls --select +customer_segments`
from `consumer/` and the `--show lineage` flag.

### 5. Does `build` leave the stubs alone?

Run `make consumer`, then `make query Q="select table_schema, table_name, table_type from information_schema.tables"`.

Look for: no stub objects in `marts`, no extra objects in `core`, and what the
build log says about the stub nodes. Add a `not_null` test to a stub column and
note whether `dbt build` runs it against the producer's table.

### 6. Contracts and drift

1. Add `contract: {enforced: true}` and column types to the stub YAML. Compile and build.
2. Rename a column in the producer's `dim_customers`, rebuild the producer, and leave the stub alone. Compile and build the consumer.

Look for: whether v2 accepts a contract on an ephemeral model, and when the
drift is caught: at compile (static analysis), at run (warehouse error), or never.
This decides whether stubs stay ephemeral and how much checking `uey` must do itself.

### 7. `projects:` in `dependencies.yml`

Replace `packages.yml` with a `dependencies.yml` that lists `projects: [{name: producer}]`
alongside the local package, then try with only `projects:`.

Look for: an error, a warning, or silence. Copy the exact message.

### 8. Versions (optional)

Give `dim_customers` two versions in the producer, mirror them in the stub, and
try `ref('producer', 'dim_customers', v=1)`.

## Go or no-go

Go if experiments 3, 4 and 5 pass and experiment 6 has a workable answer.
Otherwise the fallback in the handoff (rewriting refs to relation names) is
on the table.

Before contacting the dbt-loom maintainer, check which GitHub owner is right: the
handoff links both `nicholasyager/dbt-loom` and `adrienneyager/dbt-loom`.
