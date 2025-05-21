import pandas as pd
import numpy as np
from datetime import date

def rename_columns():
    return {
        'Nº de pedido': 'numero_pedido',
        'Cliente': 'cliente',
        'Fecha Pedido': 'fecha_pedido',
        'Fecha Entrega': 'fecha_entrega'
    }

def set_data_types(df):
    df['numero_pedido'] = df['numero_pedido'].apply(int)
    df['Cantidad'] = df['Cantidad'].fillna(0).apply(int)
    df['ID Línea'] = df['ID Línea'].apply(int)

    df['fecha_pedido'] = pd.to_datetime(df['fecha_pedido']).dt.date
    df['fecha_entrega'] = pd.to_datetime(df['fecha_entrega']).dt.date

    df['Familia'] = df['Familia'].fillna('').astype(str)
    df['Unnamed: 6'] = df['Unnamed: 6'].fillna('').astype(str)

    return df

def _convert_to_native_types(value):
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer, np.int64)):
        return int(value)
    if isinstance(value, (np.floating, np.float64)):
        return float(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    return value

def process_data(df: pd.DataFrame) -> list:
    """
    Process and transform order data from an Excel file into a structured format.
    
    This function takes a DataFrame containing order data and transforms it into a list of dictionaries,
    where each dictionary represents an order with its associated articles and manufacturing processes.
    
    Parameters
    ----------
    df : pd.DataFrame. Input DataFrame containing order data.
    
    Returns
    -------
    list
        A list of dictionaries, where each dictionary represents an order.
    
    Notes
    -----
    - The function groups orders by order number, customer, order date, and delivery date
    - Each order can have multiple articles
    - Manufacturing processes (IT columns) are organized hierarchically
    - Dates are converted to datetime.date objects
    - Quantities are converted to integers
    - Family and subfamily fields are combined into a single string
    """

    df = df.rename(columns = rename_columns())
    df = set_data_types(df)
    
    grouped_df = df.groupby(['numero_pedido', 'cliente', 'fecha_pedido', 'fecha_entrega']).apply(
        lambda x: {
            'numero_pedido': _convert_to_native_types(x.name[0]),
            'cliente': _convert_to_native_types(x.name[1]),
            'fecha_pedido': _convert_to_native_types(x.name[2]),
            'fecha_entrega': _convert_to_native_types(x.name[3]),
            'articulos': [
                {
                'nombre': _convert_to_native_types(row['Articulo']),
                'OT_ID_Linea': _convert_to_native_types(row['ID Línea']),
                'familia': _convert_to_native_types(f"{row['Familia']} {row['Unnamed: 6']}".strip()),
                'cantidad': _convert_to_native_types(row['Cantidad']),
                'importe': _convert_to_native_types(row['Importe']),
                'IT01_Dibujo': _convert_to_native_types(row['IT01 Dibujo']),
                'IT02_Pantalla': _convert_to_native_types(row['IT02 Pantalla']),
                'IT03_Corte': _convert_to_native_types(row['IT03 Corte']),
                'IT04_Impresion': {
                    '_': _convert_to_native_types(row['IT04 Impresión']),
                    'digital': _convert_to_native_types(row['IT04 Impresión Digital']),
                    'serigrafia': _convert_to_native_types(row['IT04 Impresión Serigrafia']),
                },
                'IT05_Grabado': _convert_to_native_types(row['IT05 Grabado']),
                'IT06_Adhesivo': _convert_to_native_types(row['IT06 Adhesivo']),
                'IT06_Laminado': _convert_to_native_types(row['IT06 Laminado']),
                'IT07_Mecanizado': {
                    '_': _convert_to_native_types(row['IT07 Mecanizado']),
                    'plotter': _convert_to_native_types(row['IT07 Mecanizado Plotter']),
                    'fresado': _convert_to_native_types(row['IT07 Mecanizado Fresado']),
                    'troquelado': _convert_to_native_types(row['IT07 Mecanizado Troquelado']),
                    'laser': _convert_to_native_types(row['IT07 Mecanizado Laser']),
                    'semicorte': _convert_to_native_types(row['IT07 Mecanizado Semicorte']),
                    'plegado': _convert_to_native_types(row['IT07 Mecanizado Plegado']),
                    'burbuja_teclas': _convert_to_native_types(row['IT07 Mecanizado Burbuja Teclas']),
                    'hendido': _convert_to_native_types(row['IT07 Mecanizado Hendido']),
                    'cepillado': _convert_to_native_types(row['IT07 Mecanizado Cepillado']),
                },
                'IT07_Taladro': _convert_to_native_types(row['IT07 Taladro']),
                'IT07_Can_romo': _convert_to_native_types(row['IT07 Can. Romo']),
                'IT07_Numerado': _convert_to_native_types(row['IT07 Numerado']),
                'IT08_Embalaje': _convert_to_native_types(row['IT08 Embalaje']),
                'servido': _convert_to_native_types(row['Servido'])
                }
                for _, row in x.iterrows()
            ]
        }
    ).tolist()
    
    return grouped_df