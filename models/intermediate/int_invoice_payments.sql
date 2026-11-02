-- int_invoice_payments — one row per invoice that received at least one matched payment.
-- Rolls int_payments_matched (one row per payment) up to the invoice grain.

with payments as (

    select * from {{ ref('int_payments_matched') }}
    where invoice_id is not null

),

totals as (

    select
        invoice_id,
        sum(amount_paid_jpy) as total_received_jpy,
        count(*)             as payment_count,
        min(paid_on_date)    as first_paid_on_date,
        max(paid_on_date)    as last_paid_on_date
    from payments
    group by invoice_id

)

select * from totals
