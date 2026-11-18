{{ config(materialized='ephemeral') }}
select * from "warehouse"."core"."dim_customers"
