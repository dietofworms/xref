{{ config(materialized='ephemeral') }}
select * from "warehouse"."core"."fct_orders"
