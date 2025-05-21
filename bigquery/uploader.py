from google.cloud import bigquery
import pandas as pd
from datetime import datetime
import re

def load_sales_orders(orders: list, credentials_path: str, table_id: str):

    # Create client
    client = bigquery.Client.from_service_account_json(credentials_path)

    # Create job config
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
        )
    
    # Create job
    job = client.load_table_from_json(
        json_rows = orders,
        destination = table_id,
        job_config = job_config
    )

    job.result()

def load_sales_orders_table(df: pd.DataFrame, credentials_path: str, project_id: str, dataset_id: str, table_name: str):
    """
    Loads a sales orders table into BigQuery.

    Args:
        df (pd.DataFrame): The DataFrame containing the sales orders data.
        credentials_path (str): The path to the credentials file for the BigQuery client.
        project_id (str): The ID of the BigQuery project.
        dataset_id (str): The ID of the BigQuery dataset.
        table_name (str): The name of the BigQuery table.
    
    Returns:
        None
    """

    try:
        # Rename columns
        df_renamed_columns = df.rename(columns=lambda x:
                       re.sub(r'[^\w\s]', '', x)
                   .strip()
                   .replace(" ", "_")
                   .replace(".", "")
                   .replace("º", ""))
    
        # Create client
        client = bigquery.Client.from_service_account_json(credentials_path)

        # Create table id
        now = datetime.now()
        table_sufix = now.strftime("%Y%m%d_%H%M")
        table_id = f"{project_id}.{dataset_id}.{table_name}_{table_sufix}"
        
        # Create job config
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_EMPTY")

        # Load data
        job = client.load_table_from_dataframe(df_renamed_columns, table_id, job_config=job_config)
        job.result()
    
    except Exception as e:
        print(f"Error loading sales orders table: {str(e)}")

