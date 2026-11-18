with orders as (
    select
        customer_id,
        count(*) as order_count,
        sum(case when status = 'completed' then amount else 0 end) as lifetime_value
    from {{ ref('stg_orders') }}
    group by customer_id
)

select
    c.customer_id,
    c.first_name,
    c.last_name,
    c.email,
    c.signup_date,
    coalesce(o.order_count, 0) as order_count,
    cast(coalesce(o.lifetime_value, 0) as decimal(12, 2)) as lifetime_value
from {{ ref('stg_customers') }} as c
left join orders as o using (customer_id)
