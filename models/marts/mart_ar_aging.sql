-- mart_ar_aging — one row per customer: how much they still owe, split by how late it is.
-- The classic accounts-receivable (売掛金) aging report. Only invoices with money still
-- owed count; overpayments are refunds, so they live in mart_exceptions instead.

with open_invoices as (

    select * from {{ ref('fct_invoice_reconciliation') }}
    where open_amount_jpy > 0

),

bucketed as (

    select
        *,
        case
            when days_past_due = 0  then 'current'
            when days_past_due <= 30 then '1_30'
            when days_past_due <= 60 then '31_60'
            when days_past_due <= 90 then '61_90'
            else 'over_90'
        end as aging_bucket
    from open_invoices

),

-- Pivot: one column per bucket
by_customer as (

    select
        customer_id,
        customer_name,
        sum(open_amount_jpy) filter (where aging_bucket = 'current') as current_jpy,
        sum(open_amount_jpy) filter (where aging_bucket = '1_30')    as days_1_30_jpy,
        sum(open_amount_jpy) filter (where aging_bucket = '31_60')   as days_31_60_jpy,
        sum(open_amount_jpy) filter (where aging_bucket = '61_90')   as days_61_90_jpy,
        sum(open_amount_jpy) filter (where aging_bucket = 'over_90') as days_over_90_jpy,
        sum(open_amount_jpy)                                         as total_open_jpy,
        count(*)                                                     as open_invoice_count,
        max(days_past_due)                                           as max_days_past_due,
        any_value(as_of_date)                                        as as_of_date
    from bucketed
    group by customer_id, customer_name

),

final as (

    select
        customer_id,
        customer_name,
        coalesce(current_jpy, 0)      as current_jpy,
        coalesce(days_1_30_jpy, 0)    as days_1_30_jpy,
        coalesce(days_31_60_jpy, 0)   as days_31_60_jpy,
        coalesce(days_61_90_jpy, 0)   as days_61_90_jpy,
        coalesce(days_over_90_jpy, 0) as days_over_90_jpy,
        total_open_jpy,
        open_invoice_count,
        max_days_past_due,
        as_of_date
    from by_customer

)

select * from final
