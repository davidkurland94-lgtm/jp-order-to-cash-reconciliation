-- fct_invoice_reconciliation — one row per invoice: what we billed, what arrived, and what's left.
--
-- Status rules (checked in this order):
--   nothing received : not_yet_due if due_date is after as_of_date, else unpaid_overdue
--   received = billed: paid
--   received > billed: overpaid          (usually a duplicate payment -> refund)
--   short by <= fee  : paid_fee_deducted (the fee is booked as an expense, so it's settled)
--   short by more    : partial

{% set as_of_date = var('as_of_date') %}
{% set max_bank_fee_jpy = var('max_bank_fee_jpy') %}

with invoices as (

    select * from {{ ref('stg_erp_invoices') }}

),

orders as (

    select * from {{ ref('stg_crm_orders') }}

),

customer_names as (

    select * from {{ ref('int_customer_names') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

invoice_payments as (

    select * from {{ ref('int_invoice_payments') }}

),

joined as (

    select
        i.invoice_id,
        i.order_id,
        n.customer_id,
        c.official_name                         as customer_name,
        i.invoice_date,
        i.due_date,
        i.invoice_amount_jpy,
        o.order_amount_jpy,
        coalesce(p.total_received_jpy, 0)       as total_received_jpy,
        coalesce(p.payment_count, 0)            as payment_count,
        p.first_paid_on_date,
        p.last_paid_on_date,
        i.invoice_amount_jpy - coalesce(p.total_received_jpy, 0) as short_amount_jpy,
        o.order_id is null                      as is_missing_order,
        o.order_amount_jpy is not null
            and o.order_amount_jpy <> i.invoice_amount_jpy        as is_amount_differs_from_order
    from invoices as i
    left join customer_names as n
        on n.name_variant = i.customer_name
    left join customers as c
        on c.customer_id = n.customer_id
    left join orders as o
        on o.order_id = i.order_id
    left join invoice_payments as p
        on p.invoice_id = i.invoice_id

),

with_status as (

    select
        *,
        case
            when total_received_jpy = 0 and due_date > date '{{ as_of_date }}' then 'not_yet_due'
            when total_received_jpy = 0                                       then 'unpaid_overdue'
            when short_amount_jpy = 0                                         then 'paid'
            when short_amount_jpy < 0                                         then 'overpaid'
            when short_amount_jpy <= {{ max_bank_fee_jpy }}                   then 'paid_fee_deducted'
            else 'partial'
        end as reconciliation_status
    from joined

),

final as (

    select
        *,
        case
            when reconciliation_status = 'paid_fee_deducted' then 0
            else short_amount_jpy
        end as open_amount_jpy,
        case
            when reconciliation_status = 'paid_fee_deducted' then short_amount_jpy
            else 0
        end as bank_fee_jpy,
        greatest(date_diff('day', due_date, date '{{ as_of_date }}'), 0) as days_past_due,
        date '{{ as_of_date }}' as as_of_date
    from with_status

)

select * from final
