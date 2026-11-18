select
    order_id,
    customer_id,
    order_date,
    status,
    amount,
    status = 'completed' as is_completed
from {{ ref('stg_orders') }}
