with customers as (
    select * from {{ ref('producer', 'dim_customers') }}
),

recent as (
    select customer_id, max(order_date) as last_order_date
    from {{ ref('producer', 'fct_orders') }}
    group by customer_id
)

select
    c.customer_id,
    c.email,
    c.lifetime_value,
    r.last_order_date,
    case
        when c.lifetime_value >= 100 then 'high'
        when c.lifetime_value > 0 then 'active'
        else 'none'
    end as segment
from customers as c
left join recent as r using (customer_id)
