-- stg_customers.sql
-- A staging model does ONE job: take one raw table and make it clean and typed.
-- No joins and no business logic here. Those come later.
--
-- We read everything as text (all_varchar = true in _sources.yml) and choose
-- the types ourselves here, so the raw file can never surprise us.

with source as (

    select * from {{ source('raw', 'customers') }}

),

renamed as (

    select
        customer_id,
        official_name,
        short_name   as sales_name,
        bank_name    as bank_payer_name
    from source

)

select * from renamed
