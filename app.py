import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion
from google.cloud import bigquery
import os
from ortools.sat.python import cp_model
from dotenv import load_dotenv
from typing import Dict, Any
from utils import (
    completar_datos_procesos,
    SECUENCIA_PROCESOS,
    SUBPROCESOS_VALIDOS,
)

from processing.transformations import process_data
from bigquery.uploader import insert_new_sales_orders, update_sales_orders_schedule_table
import streamlit.components.v1 as components
error_msg = "La aplicación ha fallado. Por favor, contacta con el servicio de soporte."

def post_planificacion(plan: dict, pedidos):
    print("Depurando post-planificacion:")
    print(plan)
    # Crear DataFrame para visualización
    df = pd.DataFrame(plan, columns=[
        'fecha_inicio_prevista',  # antes 'Inicio'
        'numero_pedido',          # antes 'OT' - pero realmente es numero_pedido
        'orden_proceso',          # antes 'Orden_Proceso'
        'nombre_articulo',        # antes 'Nombre'
        'cantidad',               # antes 'Cantidad'
        'dias_duracion',          # antes 'Duración'
        'proceso',                # antes 'Operación'
        'subproceso',             # antes 'Subproceso'
        'ot_id_linea',            # antes 'Numero de Pedido' - pero realmente es ot_id_linea
        'operario'                # antes 'Operario'
    ])
    
    # Convertir días a fechas
    df['fecha_inicio_prevista'] = df['fecha_inicio_prevista'].apply(lambda x: fecha_inicio + timedelta(days=x))
    df['fecha_fin_prevista'] = df.apply(lambda row: row['fecha_inicio_prevista'] + timedelta(days=row['dias_duracion']), axis=1)
    
    # Añadir información de secuencia de procesos
    df['secuencia'] = df.apply(lambda row: f"Paso {row['orden_proceso'] + 1} de {len(pedidos.get(str(row['numero_pedido']), {}).get('procesos', []))}", axis=1)
    
    # Determinar el estado de cada proceso
    def determinar_estado_planificacion(row: pd.Series) -> str:
        if row['fecha_fin_prevista'] < fecha_actual:
            return 'Planificado Finalizado'
        elif row['fecha_inicio_prevista'] <= fecha_actual <= row['fecha_fin_prevista']:
            return 'Activado'
        elif row['orden_proceso'] == 0 or all(
            (df[(df['ot_id_linea'] == row['ot_id_linea']) & (df['orden_proceso'] < row['orden_proceso'])]['fecha_inicio_prevista'] <= fecha_actual)
        ):
            return 'Listo para Activar'
        else:
            return 'Pendiente'

    def determinar_cumplimiento(row: pd.Series) -> str:
        # Obtener la fecha de entrega original del pedido
        # Verificar que el DataFrame filtrado no esté vacío antes de usar .iloc[0]
        df_filtrado = df_expanded[df_expanded['ot_id_linea'].astype(str) == str(row['ot_id_linea'])]
        if df_filtrado.empty:
            print(f"Advertencia: No se encontró ot_id_linea {row['ot_id_linea']} en df_expanded")
            return 'Sin fecha de entrega'
        
        fecha_entrega_original = pd.to_datetime(df_filtrado['fecha_entrega'].iloc[0])
        fecha_limite = fecha_entrega_original
        if row['fecha_fin_prevista'] > fecha_limite:
            return 'Fuera de Plazo'
        else:
            return 'En Plazo'

    df['estado'] = df.apply(determinar_estado_planificacion, axis=1)
    df['cumplimiento'] = df.apply(determinar_cumplimiento, axis=1)
    
    # Añadir fecha de entrega al DataFrame
    def obtener_fecha_entrega(ot_id_linea):
        # Verificar que el DataFrame filtrado no esté vacío antes de usar .iloc[0]
        df_filtrado = df_expanded[df_expanded['ot_id_linea'].astype(str) == str(ot_id_linea)]
        if df_filtrado.empty:
            print(f"Advertencia: No se encontró ot_id_linea {ot_id_linea} en df_expanded para fecha de entrega")
            return pd.NaT  # Retornar Not a Time si no se encuentra
        return pd.to_datetime(df_filtrado['fecha_entrega'].iloc[0])
    
    df['fecha_entrega'] = df['ot_id_linea'].apply(obtener_fecha_entrega)
    
    # Reordenar columnas para mejor visualización
    columnas_ordenadas = [
        'estado', 'cumplimiento', 'fecha_inicio_prevista', 'fecha_fin_prevista', 
        'fecha_entrega', 'ot_id_linea', 'numero_pedido', 'nombre_articulo', 'cantidad', 
        'proceso', 'subproceso', 'secuencia', 'dias_duracion', 'operario'
    ]
    df = df[columnas_ordenadas]

    # Guardar el resultado en final_sales_orders_schedule
    try:
        # Preparar el DataFrame para guardar
        df_to_save = df.copy()
        
        # Usar la función existente para actualizar la tabla
        print("Actualizando cronograma en BigQuery...")
        update_sales_orders_schedule_table(df_to_save, CREDENTIALS_PATH, TABLE_ID_CURRENT_SCHEDULE)
        print("Cronograma actualizado correctamente")
        st.success("Cronograma actualizado correctamente")
    except Exception as e:
        print(f"Error al guardar el cronograma en BigQuery: {str(e)}")
        st.warning(error_msg)

    return df_to_save

def pre_planificar_produccion(df_expanded: pd.DataFrame, fecha_actual: datetime):
    
    # Procesar los datos para la planificación
    pedidos: Dict[str, Dict[str, Any]] = {}
    procesos_unicos: set = set()

    # Contadores para depuración
    total_articulos = 0
    articulos_servidos = 0
    articulos_planificados = 0

    for _, row in df_expanded.iterrows():
        total_articulos += 1
        
        # Verificar si el artículo está totalmente servido
        if row.get('servido') == 'Totalmente servido':
            articulos_servidos += 1
            continue  # Saltar este artículo si está totalmente servido
            
        articulos_planificados += 1
        pedido_id = str(row['numero_pedido'])
        
        if pedido_id not in pedidos:
            # Calcular días hasta la entrega desde la fecha base
            fecha_entrega = pd.to_datetime(row['fecha_entrega'])
            dias_hasta_entrega = (fecha_entrega - fecha_inicio).days
            
            # Asegurar que la fecha sea positiva y tenga un mínimo de días para planificar
            dias_minimos_planificacion = 365  # Mínimo de días para planificar cualquier pedido
            if dias_hasta_entrega < dias_minimos_planificacion:
                dias_hasta_entrega = dias_minimos_planificacion
            
            pedidos[pedido_id] = {
                "nombre": row['nombre'],
                "cantidad": row['cantidad'],
                "fecha_entrega": dias_hasta_entrega,
                "procesos": []
            }
        
        # Procesar los procesos IT
        procesos_especificos = {}  # Diccionario para agrupar procesos por tipo
        for key, value in row.items():
            if key.startswith('IT'):
                # Separar el proceso y subproceso del nombre de la columna
                if '.' in key:
                    proceso, subproceso = key.split('.')
                    if subproceso == '_':
                        # Si es un proceso sin subproceso específico
                        nombre_completo = proceso
                        subproceso = "Sin Subproceso"
                    else:
                        nombre_completo = f"{proceso} {subproceso}"
                else:
                    # Si es un proceso simple sin subproceso
                    nombre_completo = key
                    subproceso = "Sin Subproceso"

                # Solo incluir procesos que estén "En espera"
                if pd.notna(value) and value == "En espera":
                    # Obtener el nombre base del proceso (sin subproceso)
                    proceso_base = nombre_completo.split()[0]
                    
                    # Agrupar por proceso base
                    if proceso_base not in procesos_especificos:
                        procesos_especificos[proceso_base] = []
                    
                    procesos_especificos[proceso_base].append({
                        'nombre_completo': nombre_completo,
                        'subproceso': subproceso,
                        'ot': row.get('ot_id_linea', 'Sin OT')
                    })

        # Procesar los procesos agrupados
        for proceso_base, procesos in procesos_especificos.items():
            # Si hay procesos específicos (no "Sin Subproceso"), eliminar el genérico
            tiene_especificos = any(p['subproceso'] != "Sin Subproceso" for p in procesos)
            
            for proceso in procesos:
                # Si hay específicos, solo incluir los que no son genéricos
                if not tiene_especificos or proceso['subproceso'] != "Sin Subproceso":
                    procesos_unicos.add(proceso['nombre_completo'])
                    # Calcular duración basada en la cantidad y el tipo de proceso
                    proceso_base = proceso['nombre_completo'].split()[0]
                    cantidad = row['cantidad']
                    
                    # Duración base por unidad según el proceso (en días)
                    duraciones_base = {
                        'Dibujo': 0.03648,      # 3.648 días para 100 unidades
                        'Impresión': 0.07296,   # 7.296 días para 100 unidades (Digital + Serigrafía)
                        'Taladro': 0.01824,     # 1.824 días para 100 unidades
                        'Corte': 0.01824,       # 1.824 días para 100 unidades
                        'Canteado': 0.01824,    # 1.824 días para 100 unidades
                        'Embalaje': 0.01824,    # 1.824 días para 100 unidades
                        'Pantalla': 0.03648,    # Similar a Dibujo
                        'Grabado': 0.03648,     # Similar a Dibujo
                        'Adhesivo': 0.01824,    # Similar a Corte
                        'Laminado': 0.01824,    # Similar a Corte
                        'Mecanizado': 0.01824,  # Similar a Taladro
                        'Numerado': 0.01824,    # Similar a Embalaje
                        'Serigrafía': 0.03648,  # Parte de Impresión
                        'Digital': 0.03648,     # Parte de Impresión
                        'Láser': 0.01824,       # Similar a Corte
                        'Fresado': 0.01824,     # Similar a Taladro
                        'Plotter': 0.01824,     # Similar a Corte
                        'Burbuja teclas': 0.01824,  # Similar a Taladro
                        'Hendido': 0.01824,     # Similar a Corte
                        'Plegado': 0.01824,     # Similar a Corte
                        'Semicorte': 0.01824    # Similar a Corte
                    }
                    
                    # Obtener la duración base para el proceso
                    duracion_base = duraciones_base.get(proceso_base, 0.03648)  # Por defecto, usar el tiempo de dibujo
                    
                    # Calcular duración total
                    duracion = round(cantidad * duracion_base, 3)
                    
                    # Asegurar una duración mínima de 0.5 días (4 horas)
                    duracion = max(duracion, 0.5)
                    
                    operario = "Por Asignar"
                    
                    # Verificar si el proceso ya existe
                    if not any(p[0] == proceso['nombre_completo'] and p[2] == proceso['subproceso'] 
                            for p in pedidos[pedido_id]["procesos"]):
                        pedidos[pedido_id]["procesos"].append([
                            proceso['nombre_completo'],  # nombre completo del proceso
                            duracion,                   # duracion
                            proceso['subproceso'],      # subproceso
                            proceso['ot'],             # ot (ID Linea)
                            operario                   # operario
                        ])
        
        # Procesar los nombres de procesos y subprocesos
        pedidos[pedido_id]["procesos"] = completar_datos_procesos({pedido_id: pedidos[pedido_id]})[pedido_id]["procesos"]
        
        # Ordenar los procesos según la secuencia predefinida
        pedidos[pedido_id]["procesos"].sort(key=lambda x: SECUENCIA_PROCESOS.get(x[0], 999))

    # Ordenar pedidos por fecha de entrega y seleccionar los 10 más urgentes
    pedidos_ordenados = sorted(pedidos.items(), key=lambda x: x[1]['fecha_entrega'])

    # Obtener los números de pedido únicos de los 10 más urgentes
    pedidos_urgentes = set()
    for pedido_id, _ in pedidos_ordenados[:10]:  # Cambiado de 50 a 10
        pedidos_urgentes.add(pedido_id)

    # Incluir todos los OTs que pertenecen a estos pedidos
    pedidos_planificacion = {}
    for pedido_id, data in pedidos.items():
        if pedido_id in pedidos_urgentes:
            pedidos_planificacion[pedido_id] = data

    
    # Depuración: Ver los pedidos a planificar
    print("\nPedidos a planificar:")
    for pedido_id, data in pedidos_planificacion.items():
        print(f"Pedido ID: {pedido_id}")
        print(f"Datos: {data}")
        print("\n")
    
    # Ejecutar planificación
    plan, makespan, status = planificar_produccion(pedidos_planificacion)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        st.success("Se encontró una solución óptima para los 10 pedidos más urgentes")
    elif status == cp_model.INFEASIBLE:
        st.error("No se encontró una solución factible para los 10 pedidos más urgentes")
        st.info("""
        Posibles razones:
        1. Las fechas de entrega son demasiado cercanas
        2. La duración de los procesos es mayor que el tiempo disponible
        3. Hay conflictos en la secuencia de procesos
        """)
        st.warning(error_msg)
    elif status == cp_model.MODEL_INVALID:
        st.error("El modelo es inválido para los 10 pedidos más urgentes")
        st.info("""
        Posibles razones:
        1. Variables no definidas correctamente
        2. Restricciones contradictorias
        3. Valores de entrada inválidos
        """)
        st.warning(error_msg)
    else:
        print(f"Estado desconocido: {status}")
        st.warning(error_msg)
    
    return plan, makespan, status


def estandarizar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estandariza el DataFrame para que tenga la misma estructura independientemente de su origen.
    """
    # Crear una copia para no modificar el original
    df_estandarizado = df.copy()
    
    # Mapeo de nombres de columnas
    mapeo_columnas = {
        'Fecha Inicio Prevista': 'fecha_inicio_prevista',
        'Fecha Fin Prevista': 'fecha_fin_prevista',
        'Fecha de Entrega': 'fecha_entrega',
        'OT': 'ot_id_linea',
        'Número de Pedido': 'numero_pedido',
        'Nombre': 'nombre_articulo',
        'Cantidad': 'cantidad',
        'Proceso': 'proceso',
        'Subproceso': 'subproceso',
        'Secuencia': 'secuencia',
        'Duración (días)': 'dias_duracion',
        'Operario': 'operario',
        'Estado': 'estado',
        'Cumplimiento': 'cumplimiento'
    }
    
    # Renombrar columnas si existen
    columnas_a_renombrar = {k: v for k, v in mapeo_columnas.items() if k in df_estandarizado.columns}
    if columnas_a_renombrar:
        df_estandarizado = df_estandarizado.rename(columns=columnas_a_renombrar)
    
    # Convertir fechas a datetime si existen
    columnas_fecha = ['fecha_inicio_prevista', 'fecha_fin_prevista', 'fecha_entrega']
    for col in columnas_fecha:
        if col in df_estandarizado.columns:
            df_estandarizado[col] = pd.to_datetime(df_estandarizado[col])
    
    return df_estandarizado

# Cargar variables de entorno
load_dotenv()

# Configuración de la página (debe ser el primer comando de Streamlit)
st.set_page_config(
    page_title="Panel de Producción",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)
# Configuración de BigQuery desde variables de entorno
# Obtener configuración según el entorno
if os.path.exists(os.getenv('BIGQUERY_CREDENTIALS_PATH', '')):
    # En local, usar variables de entorno
    PROJECT_ID = os.getenv('BIGQUERY_PROJECT_ID')
    DATASET_ID = os.getenv('BIGQUERY_DATASET_ID')
    TABLE_NAME_SALES_ORDERS = os.getenv('BIGQUERY_TABLE_NAME_SALES_ORDERS')
    TABLE_NAME_CURRENT_SALES_ORDERS = os.getenv('BIGQUERY_TABLE_NAME_CURRENT_SALES_ORDERS')
    TABLE_NAME_CURRENT_SCHEDULE = os.getenv('BIGQUERY_TABLE_NAME_CURRENT_SCHEDULE')
else:
    # En producción (Streamlit Cloud), usar secrets
    PROJECT_ID = st.secrets.get('BIGQUERY', {}).get('project_id')
    DATASET_ID = st.secrets.get('BIGQUERY', {}).get('dataset_id')
    TABLE_NAME_SALES_ORDERS = st.secrets.get('BIGQUERY', {}).get('table_name_sales_orders')
    TABLE_NAME_CURRENT_SALES_ORDERS = st.secrets.get('BIGQUERY', {}).get('table_name_current_sales_orders')
    TABLE_NAME_CURRENT_SCHEDULE = st.secrets.get('BIGQUERY', {}).get('table_name_current_schedule')

# Construir los IDs completos de las tablas
TABLE_ID_SALES_ORDERS = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME_SALES_ORDERS}"
TABLE_ID_CURRENT_SALES_ORDERS = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME_CURRENT_SALES_ORDERS}"
TABLE_ID_CURRENT_SCHEDULE = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME_CURRENT_SCHEDULE}"

CREDENTIALS_PATH = os.getenv('BIGQUERY_CREDENTIALS_PATH')

# Función para obtener las credenciales
def get_credentials():
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
        st.warning(error_msg)
        return None

# Función para crear el cliente de BigQuery
def get_bigquery_client():
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
        st.warning(error_msg)
        return None

# Configuración de BigQuery
try:
    #client = bigquery.Client.from_service_account_json(CREDENTIALS_PATH, location="europe-southwest1")
    client = get_bigquery_client()
    if client:
        # Verificar que las tablas existen
        try:
            # Verificar final_sales_orders_schedule
            query = f"""
            SELECT table_name 
            FROM `{PROJECT_ID}.{DATASET_ID}.INFORMATION_SCHEMA.TABLES` 
            WHERE table_name = '{TABLE_NAME_CURRENT_SCHEDULE}'
            """
            query_job = client.query(query)
            results = list(query_job.result())
            
            if not results:
                print(f"No existe la tabla: {results}")
                st.warning(error_msg)
                # Inicializar df_expanded como DataFrame vacío
                st.stop()
            else:
                # Cargar el cronograma actual desde final_sales_orders_schedule
                query = f'SELECT * FROM `{TABLE_ID_CURRENT_SCHEDULE}`'
                query_job = client.query(query)
                results = query_job.result()

                # Convertir resultados a DataFrame
                df = results.to_dataframe()
                
                if df.empty or df['fecha_inicio_prevista'].isnull().all():
                    st.info("No hay información de la planificación todavía. Se creará contenido cuando se suba el primer archivo.")
                    df_estandarizado = pd.DataFrame(columns = ['estado', 'cumplimiento', 'fecha_inicio_prevista', 'fecha_fin_prevista', 'fecha_entrega', 'ot_id_linea', 'numero_pedido', 'nombre_articulo', 'cantidad', 'proceso', 'subproceso', 'secuencia', 'dias_duracion', 'operario', 'fecha_actualizacion_tabla'])
                else:
                    # Estandarizar el DataFrame
                    df_estandarizado = estandarizar_dataframe(df)
        except Exception as e:
            print(f"Error al verificar la tabla {TABLE_NAME_CURRENT_SCHEDULE}: {str(e)}")
            st.warning(error_msg)
            st.stop()

    else:
        print("No se pudo conectar a BigQuery")
        st.warning(error_msg)
        st.stop()
except Exception as e:
    print(f"Error al conectar con BigQuery: {str(e)}")
    st.info("""
    Por favor, verifica que:
    1. Las credenciales están configuradas correctamente
    2. El proyecto existe y está activo en Google Cloud
    3. La cuenta de servicio tiene los permisos necesarios en BigQuery
    4. El dataset y la tabla especificados existen y son accesibles
    """)
    
    st.warning(error_msg)
    st.stop()

# Definir fecha de inicio y actual
fecha_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
fecha_actual = fecha_inicio  # O puedes poner una fecha fija para pruebas, por ejemplo: datetime(2024, 1, 1)

# Inicializar session_state para persistir el DataFrame
if 'df_estandarizado' not in st.session_state:
    st.session_state.df_estandarizado = df_estandarizado

# Inicializar bandera para controlar el procesamiento de archivos
if 'archivo_procesado' not in st.session_state:
    st.session_state.archivo_procesado = False

# Sidebar para entrada de datos
with st.sidebar:
    st.image("logo-sergar.png")

    # Opción para cargar pedidos desde Excel
    st.subheader("Cargar pedidos en Excel")
    uploaded_excel_file = st.file_uploader("Cargar archivo Excel de pedidos", type=['xlsx'])
    
    # Botón para procesar archivo (solo si hay archivo cargado y no se ha procesado)
    if uploaded_excel_file is not None and not st.session_state.archivo_procesado:
        if st.button("🔄 Procesar archivo Excel"):
            try:
                # 1. Procesar el archivo Excel
                print("Procesando archivo Excel...")
                df = pd.read_excel(uploaded_excel_file, decimal=",", date_format="%d/%m/%Y")
                
                # Depuración: Ver los valores originales
                print("\nValores originales del Excel:")
                print("Columnas disponibles:", df.columns.tolist())
                print("\nPrimeras filas del Excel:")
                print(df.head())
                
                orders_list = process_data(df)
                print("Archivo Excel procesado correctamente")

                # 2. Insertar en sales_orders_production
                print("Insertando en sales_orders_production...")
                insert_new_sales_orders(orders_list, CREDENTIALS_PATH, TABLE_ID_SALES_ORDERS)
                print("sales_orders_production insertado correctamente")
                
                # 3. Obtener datos de final_sales_orders_production
                print("Obteniendo datos de final_sales_orders_production...")
                query = f'SELECT * FROM `{TABLE_ID_CURRENT_SALES_ORDERS}`'
                query_job = client.query(query)
                results = query_job.result()
                df = results.to_dataframe()
                print("datos de final_sales_orders_production obtenidos correctamente")
                
                # 4. Procesar los datos para la planificación
                print("Procesando datos para la planificación...")
                df = df.explode('articulos')
                if isinstance(df['articulos'].iloc[0], str):
                    df['articulos'] = df['articulos'].apply(json.loads)
                df_expanded = pd.json_normalize(df['articulos'])
                
                # Depuración: Ver los valores después de normalizar
                print("\nValores después de normalizar:")
                print("Columnas en df_expanded:", df_expanded.columns.tolist())
                print("\nPrimeras filas de df_expanded:")
                print(df_expanded.head())
                
                df_expanded['fecha_entrega'] = df['fecha_entrega'].values
                df_expanded['numero_pedido'] = df['numero_pedido'].values
                
                # Depuración: Ver los valores después de asignar numero_pedido
                print("\nValores después de asignar numero_pedido:")
                print(df_expanded.head())
                
                print("datos procesados correctamente")
                # Estandarizar el DataFrame
                df_expanded = estandarizar_dataframe(df_expanded)

                # Depuración: Ver los valores después de estandarizar
                print("\nValores después de estandarizar:")
                print(df_expanded.head())
                
                print("Pre-planificación de la producción...")
                plan, makespan, status = pre_planificar_produccion(df_expanded, fecha_actual)
                print("Pre-planificación de la producción completada")
                if plan:
                    print("Post-planificación de la producción...")

                    # Depuración: Ver los valores después de post-planificación
                    print("\nValores después de post-planificación:")
                    # guardar el df_expanded en un archivo csv
                    df_expanded.to_csv('df_expanded.csv', index=False)

                    df_estandarizado = post_planificacion(plan, df_expanded)
                    print("Post-planificación de la producción completada")

                    # Depuración: Ver los valores después de post-planificación
                    print("\nValores después de post-planificación:")
                    print(df_estandarizado.head())
                    # guardar el df_estandarizado en un archivo csv
                    df_estandarizado.to_csv('df_estandarizado_post_planificacion.csv', index=False)

                    # ACTUALIZAR EL DATAFRAME EN SESSION_STATE PARA QUE LOS FILTROS TRABAJEN CON LOS DATOS MÁS RECIENTES
                    print("Actualizando DataFrame en session_state con los datos más recientes...")
                    st.session_state.df_estandarizado = df_estandarizado.copy()
                    
                    # RECARGAR DATOS DESDE TABLE_ID_CURRENT_SCHEDULE PARA ASEGURAR QUE LOS FILTROS TRABAJEN CON LOS DATOS ACTUALIZADOS
                    print("Recargando datos desde TABLE_ID_CURRENT_SCHEDULE...")
                    try:
                        # Cargar el cronograma actualizado desde final_sales_orders_schedule
                        query = f'SELECT * FROM `{TABLE_ID_CURRENT_SCHEDULE}`'
                        query_job = client.query(query)
                        results = query_job.result()

                        # Convertir resultados a DataFrame
                        df_actualizado = results.to_dataframe()
                        
                        if not df_actualizado.empty:
                            # Estandarizar el DataFrame actualizado
                            df_actualizado_estandarizado = estandarizar_dataframe(df_actualizado)
                            # Actualizar session_state con los datos más recientes de BigQuery
                            st.session_state.df_estandarizado = df_actualizado_estandarizado
                            print("Datos recargados correctamente desde BigQuery")
                        else:
                            print("No se encontraron datos en TABLE_ID_CURRENT_SCHEDULE")
                            
                    except Exception as e:
                        print(f"Error al recargar datos desde BigQuery: {str(e)}")
                        # Si falla la recarga, mantener los datos locales
                        print("Manteniendo datos locales como respaldo")

                    # Marcar archivo como procesado
                    st.session_state.archivo_procesado = True
                    st.success("¡Archivo procesado correctamente!")
                    st.rerun()

                else:
                    st.error("No se pudo encontrar una solución óptima para los pedidos actuales")
                    st.warning(error_msg)
            except Exception as e:
                print(f"Error al cargar el archivo Excel: {str(e)}")
                st.error("Error al cargar el archivo Excel")
                st.warning(error_msg)
    
    # Mostrar estado del archivo
    if uploaded_excel_file is not None:
        if st.session_state.archivo_procesado:
            st.success("✅ Archivo procesado")
            if st.button("🔄 Procesar nuevo archivo"):
                st.session_state.archivo_procesado = False
                st.rerun()
        else:
            st.info("📁 Archivo cargado - Haz clic en 'Procesar archivo Excel'")

    # Filtros en la sidebar
    st.subheader("Filtrar")
    
    # Botón para limpiar filtros
    if st.button("🗑️ Limpiar filtros"):
        for key in ['pedido_filtro', 'ot_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
            if key in st.session_state:
                st.session_state[key] = []
        st.rerun()
    
    # Usar el DataFrame de session_state para los filtros
    df_filtrado = st.session_state.df_estandarizado.copy()
    
    # Selector de rango de fechas
    st.subheader("📅 Rango de fechas")
    opciones_fechas = {
        "1 Semana": 7,
        "1 Mes": 30,
        "6 Meses": 180,
        "Año actual": 365,
        "1 Año": 365,
        "Todo": None
    }
    
    rango_seleccionado = st.selectbox(
        "Seleccionar rango",
        options=list(opciones_fechas.keys()),
        index=5  # Por defecto seleccionar "Todo"
    )
    
    # Aplicar filtro de fechas
    if rango_seleccionado != "Todo":
        dias = opciones_fechas[rango_seleccionado]
        fecha_limite = fecha_actual + timedelta(days=dias)
        
        # Verificar que las columnas existen antes de usarlas
        if 'fecha_inicio_prevista' in df_filtrado.columns and 'fecha_fin_prevista' in df_filtrado.columns:
            # Filtrar procesos que se realizan dentro del rango seleccionado
            mascara_fechas = (
                # El proceso comienza dentro del rango
                ((df_filtrado['fecha_inicio_prevista'] >= fecha_actual) & 
                 (df_filtrado['fecha_inicio_prevista'] <= fecha_limite)) |
                # O el proceso termina dentro del rango
                ((df_filtrado['fecha_fin_prevista'] >= fecha_actual) & 
                 (df_filtrado['fecha_fin_prevista'] <= fecha_limite)) |
                # O el proceso abarca todo el rango
                ((df_filtrado['fecha_inicio_prevista'] <= fecha_actual) & 
                 (df_filtrado['fecha_fin_prevista'] >= fecha_limite)) |
                # O el proceso ya comenzó pero aún no ha terminado
                ((df_filtrado['fecha_inicio_prevista'] <= fecha_actual) & 
                 (df_filtrado['fecha_fin_prevista'] >= fecha_actual)) |
                # O el proceso ya terminó pero fue en los últimos 7 días
                ((df_filtrado['fecha_fin_prevista'] >= fecha_actual - timedelta(days=dias)) & 
                 (df_filtrado['fecha_fin_prevista'] <= fecha_actual))
            )
            df_filtrado = df_filtrado[mascara_fechas]
        else:
            st.warning("No se encontraron las columnas de fechas necesarias para el filtrado")
    
    # Checkbox para mostrar/ocultar diagrama de Gantt
    mostrar_gantt = st.checkbox("📊 Mostrar diagrama de Gantt", value=False)
    
    # Inicializar filtros en session_state si no existen
    for key in ['pedido_filtro', 'ot_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
        if key not in st.session_state:
            st.session_state[key] = []
    
    # Filtro de número de pedido
    pedido_filtro = st.multiselect(
        "Número de Pedido",
        options=sorted(df_filtrado['numero_pedido'].unique()),
        key='pedido_filtro'
    )
    
    # Filtrar OTs según el pedido seleccionado
    if pedido_filtro:
        df_filtrado = df_filtrado[df_filtrado['numero_pedido'].isin(pedido_filtro)]
    
    # Filtro de OT
    ot_filtro = st.multiselect(
        "Número de OT",
        options=sorted(df_filtrado['ot_id_linea'].unique()),
        key='ot_filtro'
    )
    
    # Actualizar df_filtrado con los OTs seleccionados
    if ot_filtro:
        df_filtrado = df_filtrado[df_filtrado['ot_id_linea'].isin(ot_filtro)]
    
    # Obtener procesos disponibles según los OT seleccionados
    procesos_disponibles = df_filtrado['proceso'].unique()
    
    procesos_filtro = st.multiselect(
        "Proceso",
        options=sorted(procesos_disponibles),
        key='procesos_filtro'
    )
    
    # Actualizar df_filtrado con los procesos seleccionados
    if procesos_filtro:
        df_filtrado = df_filtrado[df_filtrado['proceso'].isin(procesos_filtro)]
    
    # Obtener subprocesos disponibles según los procesos seleccionados
    subprocesos_disponibles = []
    if procesos_filtro:
        for proceso in procesos_filtro:
            # Obtener subprocesos válidos para este proceso
            subprocesos_validos = SUBPROCESOS_VALIDOS.get(proceso, ['Sin especificar'])
            # Filtrar solo los subprocesos que existen en los datos
            subprocesos_existentes = df_filtrado[df_filtrado['proceso'] == proceso]['subproceso'].unique()
            # Agregar los subprocesos con el formato "Proceso - Subproceso"
            for subproceso in subprocesos_validos:
                if subproceso in subprocesos_existentes:
                    if subproceso == 'Sin especificar':
                        subprocesos_disponibles.append(f"{proceso} - Sin especificar")
                    else:
                        subprocesos_disponibles.append(f"{proceso} - {subproceso}")
    else:
        subprocesos_disponibles = df_filtrado['subproceso'].unique()
    
    subprocesos_filtro = st.multiselect(
        "Subproceso",
        options=sorted(subprocesos_disponibles),
        key='subprocesos_filtro'
    )
    
    # Actualizar df_filtrado con los subprocesos seleccionados
    if subprocesos_filtro:
        # Extraer solo el subproceso de la selección (eliminar el prefijo del proceso)
        subprocesos_seleccionados = [s.split(' - ')[1] for s in subprocesos_filtro]
        df_filtrado = df_filtrado[df_filtrado['subproceso'].isin(subprocesos_seleccionados)]
    
    # Obtener estados disponibles según los filtros anteriores
    estados_disponibles = df_filtrado['estado'].unique()
    
    estados_filtro = st.multiselect(
        "Estado de la OT",
        options=sorted(estados_disponibles),
        key='estados_filtro'
    )
    
    # Actualizar df_filtrado con los estados seleccionados
    if estados_filtro:
        df_filtrado = df_filtrado[df_filtrado['estado'].isin(estados_filtro)]
    
    # Obtener cumplimientos disponibles según los filtros anteriores
    cumplimientos_disponibles = df_filtrado['cumplimiento'].unique()
    
    cumplimiento_filtro = st.multiselect(
        "Cumplimiento de la entrega",
        options=sorted(cumplimientos_disponibles),
        key='cumplimiento_filtro'
    )
    
    # Actualizar df_filtrado con los cumplimientos seleccionados
    if cumplimiento_filtro:
        df_filtrado = df_filtrado[df_filtrado['cumplimiento'].isin(cumplimiento_filtro)]

# Crear DataFrame para Gantt
df_gantt = pd.DataFrame({
    'Task': [f"{row['ot_id_linea']} - {row['proceso']}" for _, row in df_filtrado.iterrows()],
    'Start': [row['fecha_inicio_prevista'] for _, row in df_filtrado.iterrows()],
    'Finish': [row['fecha_fin_prevista'] for _, row in df_filtrado.iterrows()],
    'Resource': [row['proceso'] for _, row in df_filtrado.iterrows()]
})

# Obtener valores únicos de Resource
recursos_unicos = df_gantt['Resource'].unique()

# Crear diccionario de colores para los procesos
colores_procesos = {
    'Dibujo': '#1f77b4',      # Azul Streamlit
    'Pantalla': '#ff7f0e',    # Naranja Streamlit
    'Corte': '#2ca02c',       # Verde Streamlit
    'Impresión': '#d62728',   # Rojo Streamlit
    'Grabado': '#9467bd',     # Púrpura Streamlit
    'Adhesivo': '#8c564b',    # Marrón Streamlit
    'Laminado': '#e377c2',    # Rosa Streamlit
    'Mecanizado': '#8B4513',  # Marrón sienna Streamlit
    'Taladro': '#bcbd22',     # Verde oliva Streamlit
    'Numerado': '#17becf',    # Cian Streamlit
    'Embalaje': '#ff9896',    # Rojo suave Streamlit
    'Can. Romo': '#98df8a'    # Verde suave Streamlit
}

colores_actuales = {}
for recurso in recursos_unicos:
    # Usar el nombre base del proceso (sin subproceso)
    proceso_base = recurso.split(' - ')[0] if ' - ' in recurso else recurso
    # Buscar el color correspondiente o usar un color por defecto
    colores_actuales[recurso] = colores_procesos.get(proceso_base, '#808080')  # Gris por defecto


if mostrar_gantt:
    st.markdown("### Cronograma de producción")
    
    # Calcular altura dinámica basada en el número de tareas
    altura_base = 600  # altura base en píxeles
    altura_por_tarea = 50  # Aumentado de 30 a 50 para dar más espacio
    altura_minima = 400  # altura mínima en píxeles
    altura_maxima = 2000  # Aumentado para permitir más espacio vertical
    altura_calculada = min(max(altura_base + (len(df_gantt) * altura_por_tarea), altura_minima), altura_maxima)
    
    fig = ff.create_gantt(df_gantt,
                        index_col='Resource',
                        show_colorbar=True,
                        group_tasks=True,
                        showgrid_x=True,
                        showgrid_y=True,
                        title='',
                        bar_width=0.4,
                        colors=colores_actuales,
                        show_hover_fill=True)

    # Configurar el layout del gráfico
    fig.update_layout(
        height=altura_calculada,
        xaxis_title="Fechas",
        yaxis_title="Operaciones",
        showlegend=True,
        xaxis=dict(
            type='date',
            showgrid=True,
            gridwidth=1,
            gridcolor='LightGrey',
            rangeslider=dict(visible=False),  # Desactivar el rangeslider
            range=[df_gantt['Start'].min(), df_gantt['Finish'].max()],  # Establecer el rango de fechas
            rangeselector=dict(visible=False)   # Ocultar los botones de rango
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='LightGrey',
            tickangle=0,  # Ángulo de las etiquetas
            tickfont=dict(size=11),  # Tamaño de la fuente
            automargin=True,  # Ajuste automático de márgenes
            side='left',  # Asegurar que las etiquetas estén a la izquierda
            dtick=1  # Mostrar todas las etiquetas
        ),
        margin=dict(l=300, r=50, t=50, b=50),  # Reducido el margen izquierdo ya que las etiquetas son más cortas
        font=dict(
            family="Roboto, sans-serif",
            size=12
        )
    )

    # Convertir a HTML y mostrarlo en un iframe scrollable
    html_gantt = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": True}
    )

    # Mostrar el gráfico en un iframe con scroll
    components.html(html_gantt, height=600, scrolling=True)

# Mostrar tabla de detalles filtrada
st.markdown("### Detalles por OT")

# Métricas principales al principio
col1, col2 = st.columns(2)
with col1:
    st.metric("Número de OTs", len(df_filtrado['ot_id_linea'].unique()))
with col2:
    st.metric("Total de Operaciones", len(df_filtrado))

# Definir los estilos para cada estado
def color_row(row):
    # Primero verificamos si está fuera de plazo
    if row['cumplimiento'] == 'Fuera de Plazo':
        return ['background-color: #FFE4E1'] * len(row)  # Rojo suave
    
    # Si no está fuera de plazo, aplicamos los colores según el estado
    if row['estado'] == 'Planificado Finalizado':
        return ['background-color: #E6F3FF'] * len(row)  # Azul suave
    elif row['estado'] == 'Activado':
        return ['background-color: #FFF8DC'] * len(row)  # Amarillo suave
    elif row['estado'] == 'Listo para Activar':
        return ['background-color: #E0FFF0'] * len(row)  # Verde suave
    else:  # Pendiente
        return [''] * len(row)

# Aplicar los estilos a la tabla
styled_df = df_filtrado.style.apply(color_row, axis=1)

# Ajustar la altura de la tabla según si el diagrama de Gantt está visible
if mostrar_gantt:
    st.dataframe(styled_df, hide_index=True, use_container_width=True)
else:
    # Calcular altura basada en el número de filas (aproximadamente 35px por fila)
    altura_por_fila = 35
    altura_minima = 400  # altura mínima en píxeles
    altura_maxima = 800  # altura máxima en píxeles
    altura_calculada = min(max(len(df_filtrado) * altura_por_fila, altura_minima), altura_maxima)
    
    st.dataframe(
        styled_df, 
        hide_index=True, 
        use_container_width=True,
        height=altura_calculada
    ) 