import json
import os

import streamlit as st
from google.cloud import bigquery

# Variable global para el cliente singleton
_bigquery_client = None

def get_credentials():
    """
    Obtiene las credenciales de BigQuery según el entorno.
    
    Returns:
        dict: Credenciales de BigQuery o None si hay error
    """
    try:
        # En desarrollo local, usar el archivo de credenciales
        if os.path.exists(os.getenv('BIGQUERY_CREDENTIALS_PATH', '')):
            with open(os.getenv('BIGQUERY_CREDENTIALS_PATH'), 'r') as f:
                return json.load(f)
        # En producción (Streamlit Cloud), usar secrets
        elif 'GOOGLE_CREDENTIALS' in st.secrets:
            # Verificar si ya es un diccionario o necesita ser parseado
            creds = st.secrets['GOOGLE_CREDENTIALS']
            if isinstance(creds, str):
                return json.loads(creds)
            return dict(creds)  # Convertir AttrDict a diccionario normal
        else:
            raise Exception("No se encontraron credenciales")
    except Exception as e:
        print(f"Error al cargar las credenciales: {str(e)}")
        return None

def _create_bigquery_client():
    """
    Crea un nuevo cliente de BigQuery.
    
    Returns:
        bigquery.Client: Cliente de BigQuery o None si hay error
    """
    try:
        credentials = get_credentials()
        if credentials:
            return bigquery.Client.from_service_account_info(
                credentials,
                project=credentials.get('project_id'),
                location="europe-southwest1"
            )
        return None
    except Exception as e:
        print(f"Error al crear el cliente de BigQuery: {str(e)}")
        return None

def get_bigquery_client():
    """
    Obtiene el cliente de BigQuery singleton.
    Si no existe, lo crea la primera vez.
    
    Returns:
        bigquery.Client: Cliente de BigQuery singleton o None si hay error
    """
    global _bigquery_client
    
    if _bigquery_client is None:
        _bigquery_client = _create_bigquery_client()
    
    return _bigquery_client

def reset_bigquery_client():
    """
    Resetea el cliente singleton (útil para testing o reconexión).
    """
    global _bigquery_client
    _bigquery_client = None

