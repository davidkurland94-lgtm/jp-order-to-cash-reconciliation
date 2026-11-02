WITH source AS (
    SELECT * FROM {{ source('raw','erp_invoices')  }}

),

datatype_cast AS (

    SELECT
        invoice_id,
        order_id,
        customer_name,
        CAST(invoice_date AS DATE) as invoice_date,
        CAST(due_date AS DATE) as due_date,
        CAST(amount_jpy AS INTEGER) as invoice_amount_jpy
    FROM source
)

SELECT * FROM datatype_cast
