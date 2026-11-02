from pathlib import Path

import duckdb

DATABASE_FILE = 'o2c.duckdb'
RAW_FOLDER = Path('raw_data')

connection = duckdb.connect(DATABASE_FILE)
connection.execute('create schema if not exists raw')

for csv_file in sorted(RAW_FOLDER.glob('*.csv')):
    table_name = csv_file.stem

    connection.execute(f"""
        create or replace table raw.{table_name} as
        select * from read_csv('{csv_file}', header = true, all_varchar = true)
        """)

    row_count = connection.execute(f'select count(*) from raw.{table_name}').fetchone()[0]
    print(f'loaded {row_count:>4} rows -> raw.{table_name}')

connection.close()
