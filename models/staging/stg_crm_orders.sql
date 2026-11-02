WITH source AS (

    SELECT * FROM {{ source('raw','crm_orders') }}

),

type_changed AS (

    SELECT
        order_id,
        account_name,
        cast(amount_jpy AS integer) AS order_amount_jpy,
        cast(order_date AS date) AS order_date
    FROM source

)

SELECT * FROM type_changed
