-- Compares our reconciliation against the answer key the data generator wrote.
-- Every row returned is an invoice we got wrong. Set to warn (not error) because
-- the matching rules are still being improved; the count shows how close we are.

{{ config(severity='warn') }}

select
    f.invoice_id,
    f.reconciliation_status,
    e.expected_status,
    f.open_amount_jpy,
    e.expected_open_amount_jpy,
    e.planted_scenario
from {{ ref('fct_invoice_reconciliation') }} as f
inner join {{ ref('expected_invoice_status') }} as e
    on e.invoice_id = f.invoice_id
where f.reconciliation_status <> e.expected_status
   or f.open_amount_jpy <> e.expected_open_amount_jpy
