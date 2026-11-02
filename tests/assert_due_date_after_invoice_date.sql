-- Looks for orders where the due date is earlier than the invoice date.

SELECT
  invoice_id,
  order_id,
  invoice_date,
  due_date
FROM {{ ref('stg_erp_invoices') }}
WHERE due_date < invoice_date
