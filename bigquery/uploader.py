from google.cloud import bigquery
import pandas as pd
from datetime import datetime
import re

def insert_new_sales_orders(orders: list, credentials_path: str, table_id_sales_orders_production: str):
    """
    Inserts new sales orders into the sales orders production table.

    Args:
        orders (list): The list of sales orders to insert.
        credentials_path (str): The path to the credentials file for the BigQuery client.
        table_id_sales_orders_production (str): The ID of the sales orders production table.

    Returns:
        None
    """

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
        destination = table_id_sales_orders_production,
        job_config = job_config
    )

    job.result()

def update_sales_orders_schedule_table(df: pd.DataFrame, credentials_path: str, table_id_current_schedule: str):
    """
    Updates the sales orders schedule table with the new sales orders.

    Args:
        df (pd.DataFrame): The DataFrame containing the sales orders data.
        credentials_path (str): The path to the credentials file for the BigQuery client.
        table_id_current_schedule (str): The ID of the current schedule table.


    Columns:
    - numero_pedido: INTEGER
    - estado: STRING
    - cumplimiento: STRING
    - fecha_inicio_prevista: TIMESTAMP
    - fecha_fin_prevista: TIMESTAMP
    - fecha_entrega: TIMESTAMP
    - ot_id_linea: INTEGER
    - nombre_articulo: STRING
    - cantidad: INTEGER
    - proceso: STRING
    - subproceso: STRING
    - secuencia: STRING
    - dias_duracion: INTEGER
    - operario: STRING

    Returns:
        None
    """

    try:
        # Add column for table update date
        df['fecha_actualizacion_tabla'] = pd.NaT

        # Create client
        client = bigquery.Client.from_service_account_json(credentials_path)
        
        # Create job config
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")

        # Load data
        job = client.load_table_from_dataframe(df, table_id_current_schedule, job_config=job_config)
        job.result()
    
    except Exception as e:
        print(f"Error updating sales orders schedule table: {str(e)}")

