import pandas as pd

def rename_columns():
    return {
        'Nº de pedido': 'numero_pedido',
        'Cliente': 'cliente',
        'Fecha Pedido': 'fecha_pedido',
        'Fecha Entrega': 'fecha_entrega'
    }

def set_data_types(df):
    df['numero_pedido'] = df['numero_pedido'].astype(int)
    df['fecha_pedido'] = pd.to_datetime(df['fecha_pedido']).dt.date
    df['fecha_entrega'] = pd.to_datetime(df['fecha_entrega']).dt.date
    df['Cantidad'] = df['Cantidad'].fillna(0).astype(int)
    df['Familia'] = df['Familia'].fillna('').astype(str)
    df['Unnamed: 6'] = df['Unnamed: 6'].fillna('').astype(str)

    return df
    
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
            'numero_pedido': x.name[0],
            'cliente': x.name[1],
            'fecha_pedido': x.name[2],
            'fecha_entrega': x.name[3],
            'articulos': [
                {
                'nombre': row['Articulo'],
                'OT_ID_Linea': row['ID Línea'],
                'familia': f"{row['Familia']} {row['Unnamed: 6']}".strip(),
                'cantidad': int(row['Cantidad']),
                'importe': row['Importe'],
                'IT01_Dibujo': row['IT01 Dibujo'],
                'IT02_Pantalla': row['IT02 Pantalla'],
                'IT03_Corte': row['IT03 Corte'],
                'IT04_Impresion': {
                    '_': row['IT04 Impresión'],
                    'digital': row['IT04 Impresión Digital'],
                    'serigrafia': row['IT04 Impresión Serigrafia'],
                },
                'IT05_Grabado': row['IT05 Grabado'],
                'IT06_Adhesivo': row['IT06 Adhesivo'],
                'IT06_Laminado': row['IT06 Laminado'],
                'IT07_Mecanizado': {
                    '_': row['IT07 Mecanizado'],
                    'plotter': row['IT07 Mecanizado Plotter'],
                    'fresado': row['IT07 Mecanizado Fresado'],
                    'laser': row['IT07 Mecanizado Laser'],
                    'semicorte': row['IT07 Mecanizado Semicorte'],
                    'plegado': row['IT07 Mecanizado Plegado'],
                    'burbuja_teclas': row['IT07 Mecanizado Burbuja Teclas'],
                    'hendido': row['IT07 Mecanizado Hendido'],
                    'cepillado': row['IT07 Mecanizado Cepillado'],
                },
                'IT07_Taladro': row['IT07 Taladro'],
                'IT07_Can_romo': row['IT07 Can. Romo'],
                'IT07_Numerado': row['IT07 Numerado'],
                'IT08_Embalaje': row['IT08 Embalaje']
                }
                for _, row in x.iterrows()
            ]
        }
    ).tolist()
    
    return grouped_df