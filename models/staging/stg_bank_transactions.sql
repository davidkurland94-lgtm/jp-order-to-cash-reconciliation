WITH source AS (

  FROM {{  source('raw','bank_transactions')  }}
  ),

rename AS (
  SELECT
    txn_id AS transaction_id,
    CAST(paid_on as DATE) as paid_on_date,
    CAST(amount_jpy as INTEGER) as amount_paid_jpy,
    payer_name,
    memo,
    case
      when regexp_matches(memo, 'INV-?\d+')
      then 'INV-' || regexp_extract(memo, 'INV-?(\d+)', 1)
    end as memo_invoice_id
  FROM source
  )

SELECT * from rename
