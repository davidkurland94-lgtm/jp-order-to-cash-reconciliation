-- int_customer_names — one row per way a customer's name gets written, mapped to customer_id.
-- Join any source's name column to name_variant to get a customer_id.

with customers as (

    select * from {{ ref('stg_customers') }}

),

-- union (not union all) drops exact duplicates, e.g. the ㈱ variant of a
-- 合同会社 name is identical to its official name
name_variants as (

    select customer_id, official_name as name_variant, 'official' as name_type
    from customers

    union

    -- ERP staff sometimes write 株式会社 as the single character ㈱
    select customer_id, replace(official_name, '株式会社', '㈱'), 'official_abbrev'
    from customers
    where official_name like '%株式会社%'

    union

    select customer_id, sales_name, 'short'
    from customers

    union

    select customer_id, bank_payer_name, 'bank'
    from customers

)

select * from name_variants
