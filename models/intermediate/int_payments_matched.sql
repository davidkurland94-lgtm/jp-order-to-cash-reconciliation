-- int_payments_matched — one row per bank transaction, with the invoice it pays (if we can tell).
--
-- Three matching rules, tried in order. Each rule only looks at the transactions
-- and invoices that the earlier rules left over:
--   1. memo     : the memo contains an invoice number
--   2. amount   : the amount equals exactly ONE open invoice's amount
--   3. customer : the payer's bank name identifies the customer, and the amount equals
--                 one of that customer's invoices (or is short by a bank transfer fee)
-- Anything still unmatched gets match_method = 'unmatched' -> exceptions mart.

-- The biggest bank transfer fee (振込手数料) a customer may deduct; set in dbt_project.yml
{% set max_bank_fee_jpy = var('max_bank_fee_jpy') %}

with transactions as (

    select * from {{ ref('stg_bank_transactions') }}

),

invoices as (

    select * from {{ ref('stg_erp_invoices') }}

),

customer_names as (

    select * from {{ ref('int_customer_names') }}

),

-- Rule 1: the memo names the invoice
memo_matches as (

    select
        t.transaction_id,
        i.invoice_id,
        'memo' as match_method
    from transactions as t
    inner join invoices as i
        on t.memo_invoice_id = i.invoice_id

),

-- What rule 1 left over
unmatched_after_memo as (

    select * from transactions
    where transaction_id not in (select transaction_id from memo_matches)

),

open_after_memo as (

    select * from invoices
    where invoice_id not in (select invoice_id from memo_matches)

),

-- Rule 2: the amount matches exactly one open invoice (and vice versa)
amount_matches as (

    select
        t.transaction_id,
        i.invoice_id,
        'amount' as match_method
    from unmatched_after_memo as t
    inner join open_after_memo as i
        on t.amount_paid_jpy = i.invoice_amount_jpy
        and t.paid_on_date >= i.invoice_date
    qualify
        count(*) over (partition by t.transaction_id) = 1
        and count(*) over (partition by i.invoice_id) = 1

),

-- What rule 2 left over
unmatched_after_amount as (

    select * from unmatched_after_memo
    where transaction_id not in (select transaction_id from amount_matches)

),

open_after_amount as (

    select * from open_after_memo
    where invoice_id not in (select invoice_id from amount_matches)

),

-- Give both sides a customer_id so rule 3 can compare them.
-- Bank side: the payer name is the customer's bank name.
transactions_with_customer as (

    select
        t.*,
        c.customer_id
    from unmatched_after_amount as t
    inner join customer_names as c
        on c.name_variant = t.payer_name

),

-- Map the ERP name to customer_id via the lookup
invoices_with_customer as (

    select
        i.*,
        c.customer_id
    from open_after_amount as i
    inner join customer_names as c
        on c.name_variant = i.customer_name

),

-- Rule 3: same customer, and the amount is the invoice minus 0 to max_bank_fee_jpy
customer_matches as (

    select
        t.transaction_id,
        i.invoice_id,
        'customer' as match_method
    from transactions_with_customer as t
    inner join invoices_with_customer as i
        on t.customer_id = i.customer_id
        and t.paid_on_date >= i.invoice_date
        and i.invoice_amount_jpy - t.amount_paid_jpy between 0 and {{ max_bank_fee_jpy }}
    qualify
        count(*) over (partition by t.transaction_id) = 1
        and count(*) over (partition by i.invoice_id) = 1

),

all_matches as (

    select * from memo_matches
    union all
    select * from amount_matches
    union all
    select * from customer_matches

),

final as (

    select
        t.transaction_id,
        t.paid_on_date,
        t.amount_paid_jpy,
        t.payer_name,
        t.memo,
        m.invoice_id,
        coalesce(m.match_method, 'unmatched') as match_method
    from transactions as t
    left join all_matches as m
        on t.transaction_id = m.transaction_id

)

select * from final
