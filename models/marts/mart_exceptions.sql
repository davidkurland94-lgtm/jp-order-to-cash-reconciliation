-- mart_exceptions — one row per problem a person needs to look at (the finance team's to-do list).
-- An invoice can appear more than once, e.g. partially paid AND missing its order.
-- Fee-deducted invoices are NOT here: those are settled, the fee just gets booked as an expense.

with invoices as (

    select * from {{ ref('fct_invoice_reconciliation') }}

),

payments as (

    select * from {{ ref('int_payments_matched') }}

),

-- Money arrived but no rule could tie it to an invoice
unmatched_payments as (

    select
        'unmatched_payment'     as exception_type,
        cast(null as varchar)   as invoice_id,
        transaction_id,
        cast(null as varchar)   as customer_id,
        payer_name              as name_on_record,
        amount_paid_jpy         as amount_jpy,
        paid_on_date            as exception_date,
        'Find out who paid and what for; one payment may cover several invoices' as next_step
    from payments
    where match_method = 'unmatched'

),

invoice_exceptions as (

    select
        case reconciliation_status
            when 'overpaid'       then 'overpaid'
            when 'partial'        then 'partial_payment'
            when 'unpaid_overdue' then 'unpaid_overdue'
        end                     as exception_type,
        invoice_id,
        cast(null as varchar)   as transaction_id,
        customer_id,
        customer_name           as name_on_record,
        open_amount_jpy         as amount_jpy,
        due_date                as exception_date,
        case reconciliation_status
            when 'overpaid'       then 'Refund the customer or apply the credit to a future invoice'
            when 'partial'        then 'Ask the customer about the remaining balance'
            when 'unpaid_overdue' then 'Send a payment reminder (督促)'
        end                     as next_step
    from invoices
    where reconciliation_status in ('overpaid', 'partial', 'unpaid_overdue')

),

-- Billing problems: sales and finance disagree about the order
order_exceptions as (

    select
        case
            when is_missing_order then 'invoice_without_order'
            else 'amount_differs_from_order'
        end                     as exception_type,
        invoice_id,
        cast(null as varchar)   as transaction_id,
        customer_id,
        customer_name           as name_on_record,
        case
            when is_missing_order then invoice_amount_jpy
            else invoice_amount_jpy - order_amount_jpy
        end                     as amount_jpy,
        invoice_date            as exception_date,
        case
            when is_missing_order then 'Check with sales that this order exists in the CRM'
            else 'Confirm the correct amount with sales; reissue the invoice if needed'
        end                     as next_step
    from invoices
    where is_missing_order or is_amount_differs_from_order

),

unioned as (

    select * from unmatched_payments
    union all
    select * from invoice_exceptions
    union all
    select * from order_exceptions

),

final as (

    select
        exception_type || ':' || coalesce(invoice_id, transaction_id) as exception_id,
        *
    from unioned

)

select * from final
