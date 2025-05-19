from google.cloud import bigquery

def insert_sales_orders(orders: list, credentials_path: str, table_id: str):

    # Create client
    client = bigquery.Client.from_service_account_json(credentials_path)

    # Create job config
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
        )
    
    # Create job
    job = client.load_table_from_json(
        json_rows = orders,
        destination = table_id,
        job_config = job_config
    )

    job.result()