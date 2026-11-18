# Phase 0 findings

dbt-oss 2.0.11 (Apache 2.0) with DuckDB, run on 2026-11-12. On the proprietary
`dbt` 2.0.11, with no license installed, experiments 1 to 4, 8, the no-op part of
experiment 5 and the drift part of experiment 6 were repeated, with the same results
except where experiment 6 notes a difference. Not repeated there: the data test on a
stub (5) and the wrong-type stub contract (6). Both distributions write a
`dim_customers` node with the same set of fields.

**Decision: go.** The stub-package design works on dbt v2 with no hook into the
engine. Two parts of the handoff were wrong; see "Changes to the plan".

| # | Experiment | Result | Evidence |
|---|---|---|---|
| 1 | Producer manifest | v12 schema, not v20 | `metadata.dbt_schema_version` is `https://schemas.getdbt.com/dbt/manifest/v12.json`, `dbt_version` `2.0.11` |
| 2 | Local stub package | Works | `dbt deps` symlinks `dbt_packages/producer -> ../.mesh/producer`. The package name comes from the stub's `dbt_project.yml`, not the folder |
| 3 | Two-argument ref compiles | Pass | `ref('producer', 'dim_customers')` compiles to `__dbt__cte__dim_customers as (select * from "warehouse"."core"."dim_customers")` |
| 4 | Lineage | Pass | `parent_map["model.consumer.customer_segments"]` is `["model.producer.dim_customers", "model.producer.fct_orders"]` |
| 5 | Build skips stubs | Pass, with a catch | Stubs report `no-op` and create no warehouse objects. A data test declared on a stub column **does run** in the consumer build, against the producer's table |
| 6 | Contracts and drift | Contract is metadata only | See below |
| 7 | `projects:` without platform | Silently ignored | With `projects:` plus the local package, everything works. With `projects:` alone: `DependencyNotFound (dbt1048): Ref 'dim_customers' not found in project. Searched for 'producer.dim_customers'`. No warning that `projects:` did nothing |
| 8 | Versions | Pass | Stub files `dim_customers_v1.sql` and `_v2.sql` with `versions:` and `latest_version: 2` in YAML. `ref('producer', 'dim_customers', v=1)` resolves to `model.producer.dim_customers.v1`, and dbt warns on its own: `UpcomingReferenceDeprecation (dbt1073)` when `deprecation_date` is set |

## Experiment 6 in detail

- `contract: {enforced: true}` on an ephemeral stub is accepted with no warning, and the
  consumer manifest records `"enforced": true`.
- It is **not enforced**. Declaring `lifetime_value` as `varchar` in the stub while the
  producer table has `decimal(12,2)` builds successfully.
- Real drift (producer renames `email` to `email_address`, stub unchanged):
  - **dbt-oss**: `compile` succeeds. `build` fails in the warehouse: `Binder Error: Values list "c" does not have a column named "email"`.
    `--static-analysis strict` prints: "this distribution of dbt OSS does not include the static analysis engine".
  - **proprietary dbt**, `compile --static-analysis strict`: fails at compile with
    `UnresolvedIdentifier (dbt0227): No column c.email found. Available are c.email_address, ...`.
    It listed `email_address`, which is only in the warehouse, not the stub YAML, so it read the live table schema.

## Changes to the plan

1. **Manifest version.** dbt v2 writes v12, the same schema as dbt Core 1.x. Phase 1 needs one
   reader, not separate v12 and v20 readers. Keep the check on `dbt_schema_version` so an
   unknown version fails loudly.
2. **Stubs must not carry data tests.** They would rerun the producer's tests in every consumer build.
3. **Contracts in stubs are documentation.** Drift detection is `uey`'s job (the Phase 2
   breaking-change gate). On dbt-oss nothing catches drift before the warehouse does.
4. **Ephemeral stays the default** (answers the comment in the handoff). It works, creates nothing,
   and the CTE is a plain `select *`.
5. **`projects:` is not needed** and does nothing without the platform. `sync` should write a
   `packages.yml` `local:` entry.
6. **Versioned models** need one stub file per version, named `<model>_v<N>.sql`, plus
   `versions`, `latest_version` and `deprecation_date` in the YAML. dbt then handles
   deprecation warnings itself.

## Not tested

- Query performance of the ephemeral CTE on a real warehouse (DuckDB tells us nothing).
- Separate databases for producer and consumer (both share one DuckDB file here).
- Versioned relations in the producer itself (only the stub side was tested).
