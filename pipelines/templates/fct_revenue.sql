CREATE OR REPLACE VIEW analytics.fct_revenue AS
SELECT
    created_at::date AS day,
    count(*) AS orders,
    sum(order_amount) AS revenue
FROM analytics.stg_orders
WHERE status <> 'refunded'
GROUP BY 1;
