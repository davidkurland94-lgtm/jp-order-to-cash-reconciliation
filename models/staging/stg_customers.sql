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
