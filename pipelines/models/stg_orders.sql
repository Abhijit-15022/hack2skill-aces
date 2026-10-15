CREATE SCHEMA IF NOT EXISTS analytics;
CREATE OR REPLACE VIEW analytics.stg_orders AS
SELECT
    order_id,
    customer_id,
    amount AS order_amount,
    status,
    created_at
FROM raw.orders;
