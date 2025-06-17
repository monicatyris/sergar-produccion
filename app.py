import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion
import plotly.graph_objects as go
from google.cloud import bigquery
import os
from ortools.sat.python import cp_model
from dotenv import load_dotenv
from typing import Dict, List, Tuple, Any
from utils import (
    procesar_nombre_proceso,
    completar_datos_procesos,
    calcular_fechas_limite_internas,
    calcular_prioridad,
    MAPEO_PROCESOS,
    MAPEO_SUBPROCESOS,
    SECUENCIA_PROCESOS,
    SUBPROCESOS_VALIDOS,
    COSTES_PROCESOS
)

from processing.transformations import process_data
from bigquery.uploader import insert_new_sales_orders, update_sales_orders_schedule_table
import streamlit.components.v1 as components

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
        st.error(f"Error al cargar las credenciales: {str(e)}")
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
        st.error(f"Error al crear el cliente de BigQuery: {str(e)}")
        return None

# Configuración de BigQuery
try:
    #client = bigquery.Client.from_service_account_json(CREDENTIALS_PATH, location="europe-southwest1")
    client = get_bigquery_client()
    if client:
        # Cargar el cronograma actual desde final_sales_orders_schedule
        query = f'SELECT * FROM `{TABLE_ID_CURRENT_SCHEDULE}`'
        query_job = client.query(query)
        results = query_job.result()

        # Convertir resultados a DataFrame
        df = results.to_dataframe()

        # Expandir el campo articulos
        df = df.explode('articulos')

        # Convertir la columna articulos de string a diccionario si es necesario
        if isinstance(df['articulos'].iloc[0], str):
            df['articulos'] = df['articulos'].apply(json.loads)

        # Crear un nuevo DataFrame con los datos expandidos
        df_expanded = pd.json_normalize(df['articulos'])

        # Añadir la fecha de entrega y el número de pedido del DataFrame original
        df_expanded['fecha_entrega'] = df['fecha_entrega'].values
        df_expanded['numero_pedido'] = df['numero_pedido'].values

    else:
        st.error("No se pudo conectar a BigQuery")
        st.stop()
except Exception as e:
    st.error(f"Error al conectar con BigQuery: {str(e)}")
    st.info("""
    Por favor, verifica que:
    1. Las credenciales están configuradas correctamente
    2. El proyecto existe y está activo en Google Cloud
    3. La cuenta de servicio tiene los permisos necesarios en BigQuery
    4. El dataset y la tabla especificados existen y son accesibles
    """)
    st.stop()

# Definir fecha de inicio y actual
fecha_inicio = datetime(2023, 12, 28)  # Fecha base fija
# fecha_actual = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
fecha_actual = datetime(2024, 1, 1)  # Fecha simulada para ver diferentes estados

# Sidebar para entrada de datos
with st.sidebar:
    st.image("logo-sergar.png")

    # Opción para cargar pedidos desde Excel
    st.subheader("Cargar pedidos en Excel")
    uploaded_excel_file = st.file_uploader("Cargar archivo Excel de pedidos", type=['xlsx'])
    if uploaded_excel_file is not None:
        try:
            # 1. Procesar el archivo Excel
            df = pd.read_excel(uploaded_excel_file, decimal=",", date_format="%d/%m/%Y")
            orders_list = process_data(df)
            
            # 2. Insertar en sales_orders_production
            insert_new_sales_orders(orders_list, CREDENTIALS_PATH, TABLE_ID_SALES_ORDERS)
            
            # 3. Obtener datos de final_sales_orders_production
            query = f'SELECT * FROM `{TABLE_ID_CURRENT_SALES_ORDERS}`'
            query_job = client.query(query)
            results = query_job.result()
            df = results.to_dataframe()
            
            # 4. Procesar los datos para la planificación
            df = df.explode('articulos')
            if isinstance(df['articulos'].iloc[0], str):
                df['articulos'] = df['articulos'].apply(json.loads)
            df_expanded = pd.json_normalize(df['articulos'])
            df_expanded['fecha_entrega'] = df['fecha_entrega'].values
            df_expanded['numero_pedido'] = df['numero_pedido'].values
            
            st.success("Archivo Excel cargado correctamente")
        except Exception as e:
            st.error(f"Error al cargar el archivo Excel: {str(e)}")

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
    pedido_id = str(row['OT_ID_Linea'])
    
    if pedido_id not in pedidos:
        # Calcular días hasta la entrega desde la fecha base
        fecha_entrega = pd.to_datetime(row['fecha_entrega'])
        if str(row['OT_ID_Linea']) == '300200':
            fecha_entrega = pd.to_datetime('2023-12-25')
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
                    'ot': row.get('OT_ID_Linea', 'Sin OT')
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
    # Buscar el número de pedido correspondiente a este OT
    numero_pedido = df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(pedido_id)]['numero_pedido'].iloc[0]
    pedidos_urgentes.add(numero_pedido)

# Incluir todos los OTs que pertenecen a estos pedidos
pedidos_planificacion = {}
for pedido_id, data in pedidos.items():
    numero_pedido = df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(pedido_id)]['numero_pedido'].iloc[0]
    if numero_pedido in pedidos_urgentes:
        pedidos_planificacion[pedido_id] = data

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
elif status == cp_model.MODEL_INVALID:
    st.error("El modelo es inválido para los 10 pedidos más urgentes")
    st.info("""
    Posibles razones:
    1. Variables no definidas correctamente
    2. Restricciones contradictorias
    3. Valores de entrada inválidos
    """)
else:
    st.error(f"Estado desconocido: {status}")

if plan:
    # Crear DataFrame para visualización
    df = pd.DataFrame(plan, columns=['Inicio', 'OT', 'Orden_Proceso', 'Nombre', 'Cantidad', 'Duración', 'Operación', 'Subproceso', 'OT_ID', 'Operario'])
    
    # Convertir días a fechas
    df['Fecha Inicio Prevista'] = df['Inicio'].apply(lambda x: fecha_inicio + timedelta(days=x))
    df['Fecha Fin Prevista'] = df.apply(lambda row: row['Fecha Inicio Prevista'] + timedelta(days=row['Duración']), axis=1)
    
    # Añadir información de secuencia de procesos
    df['Secuencia'] = df.apply(lambda row: f"Paso {row['Orden_Proceso'] + 1} de {len(pedidos[str(row['OT'])]['procesos'])}", axis=1)
    
    # Determinar el estado de cada proceso
    def determinar_estado_planificacion(row: pd.Series) -> str:
        if row['Fecha Fin Prevista'] < fecha_actual:
            return 'Planificado Finalizado'
        elif row['Fecha Inicio Prevista'] <= fecha_actual <= row['Fecha Fin Prevista']:
            return 'Activado'
        elif row['Orden_Proceso'] == 0 or all(
            (df[(df['OT'] == row['OT']) & (df['Orden_Proceso'] < row['Orden_Proceso'])]['Fecha Inicio Prevista'] <= fecha_actual)
        ):
            return 'Listo para Activar'
        else:
            return 'Pendiente'

    def determinar_cumplimiento(row: pd.Series) -> str:
        # Obtener la fecha de entrega original del pedido
        fecha_entrega_original = pd.to_datetime(df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(row['OT'])]['fecha_entrega'].iloc[0])
        # Si es la OT 300200, usar la fecha modificada
        if str(row['OT']) == '300200':
            fecha_entrega_original = pd.to_datetime('2023-12-25')
        fecha_limite = fecha_entrega_original
        if row['Fecha Fin Prevista'] > fecha_limite:
            return 'Fuera de Plazo'
        else:
            return 'En Plazo'

    df['Estado'] = df.apply(determinar_estado_planificacion, axis=1)
    df['Cumplimiento'] = df.apply(determinar_cumplimiento, axis=1)
    
    # Añadir número de pedido al DataFrame
    df['Número de Pedido'] = df['OT'].apply(lambda x: df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(x)]['numero_pedido'].iloc[0] if not df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(x)].empty else 'N/A')
    
    # Añadir fecha de entrega al DataFrame
    df['Fecha de Entrega'] = df['OT'].apply(lambda x: pd.to_datetime('2023-12-25') if str(x) == '300200' else pd.to_datetime(df_expanded[df_expanded['OT_ID_Linea'].astype(str) == str(x)]['fecha_entrega'].iloc[0]))
    
    # Renombrar columnas para mejor comprensión
    df = df.rename(columns={
        'Duración': 'Duración (días)',
        'Operación': 'Proceso',
        'OT_ID': 'Número de OT'
    })
    
    # Reordenar columnas para mejor visualización
    columnas_ordenadas = [
        'Estado', 'Cumplimiento', 'Fecha Inicio Prevista', 'Fecha Fin Prevista', 
        'Fecha de Entrega', 'OT', 'Número de Pedido', 'Nombre', 'Cantidad', 
        'Proceso', 'Subproceso', 'Secuencia', 'Duración (días)', 'Número de OT', 'Operario'
    ]
    df = df[columnas_ordenadas]

    # Filtros en la sidebar
    with st.sidebar:
        st.subheader("Filtrar")
        
        # Botón para limpiar filtros
        if st.button("🗑️ Limpiar filtros"):
            for key in ['pedido_filtro', 'ot_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
                if key in st.session_state:
                    st.session_state[key] = []
            st.rerun()
        
        # Inicializar df_filtrado con el DataFrame original
        df_filtrado = df.copy()
        
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
            # Filtrar procesos que se realizan dentro del rango seleccionado
            mascara_fechas = (
                # El proceso comienza dentro del rango
                ((df_filtrado['Fecha Inicio Prevista'] >= fecha_actual) & 
                 (df_filtrado['Fecha Inicio Prevista'] <= fecha_limite)) |
                # O el proceso termina dentro del rango
                ((df_filtrado['Fecha Fin Prevista'] >= fecha_actual) & 
                 (df_filtrado['Fecha Fin Prevista'] <= fecha_limite)) |
                # O el proceso abarca todo el rango
                ((df_filtrado['Fecha Inicio Prevista'] <= fecha_actual) & 
                 (df_filtrado['Fecha Fin Prevista'] >= fecha_limite)) |
                # O el proceso ya comenzó pero aún no ha terminado
                ((df_filtrado['Fecha Inicio Prevista'] <= fecha_actual) & 
                 (df_filtrado['Fecha Fin Prevista'] >= fecha_actual)) |
                # O el proceso ya terminó pero fue en los últimos 7 días
                ((df_filtrado['Fecha Fin Prevista'] >= fecha_actual - timedelta(days=dias)) & 
                 (df_filtrado['Fecha Fin Prevista'] <= fecha_actual))
            )
            df_filtrado = df_filtrado[mascara_fechas]
        
        # Checkbox para mostrar/ocultar diagrama de Gantt
        mostrar_gantt = st.checkbox("📊 Mostrar diagrama de Gantt", value=False)
        
        # Inicializar filtros en session_state si no existen
        for key in ['pedido_filtro', 'ot_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
            if key not in st.session_state:
                st.session_state[key] = []
        
        # Filtro de número de pedido
        pedido_filtro = st.multiselect(
            "Número de Pedido",
            options=sorted(df_filtrado['Número de Pedido'].unique()),
            key='pedido_filtro'
        )
        
        # Filtrar OTs según el pedido seleccionado
        if pedido_filtro:
            df_filtrado = df_filtrado[df_filtrado['Número de Pedido'].isin(pedido_filtro)]
        
        # Filtro de OT
        ot_filtro = st.multiselect(
            "Número de OT",
            options=sorted(df_filtrado['OT'].unique()),
            key='ot_filtro'
        )
        
        # Actualizar df_filtrado con los OTs seleccionados
        if ot_filtro:
            df_filtrado = df_filtrado[df_filtrado['OT'].isin(ot_filtro)]
        
        # Obtener procesos disponibles según los OT seleccionados
        procesos_disponibles = df_filtrado['Proceso'].unique()
        
        procesos_filtro = st.multiselect(
            "Proceso",
            options=sorted(procesos_disponibles),
            key='procesos_filtro'
        )
        
        # Actualizar df_filtrado con los procesos seleccionados
        if procesos_filtro:
            df_filtrado = df_filtrado[df_filtrado['Proceso'].isin(procesos_filtro)]
        
        # Obtener subprocesos disponibles según los procesos seleccionados
        subprocesos_disponibles = []
        if procesos_filtro:
            for proceso in procesos_filtro:
                # Obtener subprocesos válidos para este proceso
                subprocesos_validos = SUBPROCESOS_VALIDOS.get(proceso, ['Sin especificar'])
                # Filtrar solo los subprocesos que existen en los datos
                subprocesos_existentes = df_filtrado[df_filtrado['Proceso'] == proceso]['Subproceso'].unique()
                # Agregar los subprocesos con el formato "Proceso - Subproceso"
                for subproceso in subprocesos_validos:
                    if subproceso in subprocesos_existentes:
                        if subproceso == 'Sin especificar':
                            subprocesos_disponibles.append(f"{proceso} - Sin especificar")
                        else:
                            subprocesos_disponibles.append(f"{proceso} - {subproceso}")
        else:
            subprocesos_disponibles = df_filtrado['Subproceso'].unique()
        
        subprocesos_filtro = st.multiselect(
            "Subproceso",
            options=sorted(subprocesos_disponibles),
            key='subprocesos_filtro'
        )
        
        # Actualizar df_filtrado con los subprocesos seleccionados
        if subprocesos_filtro:
            # Extraer solo el subproceso de la selección (eliminar el prefijo del proceso)
            subprocesos_seleccionados = [s.split(' - ')[1] for s in subprocesos_filtro]
            df_filtrado = df_filtrado[df_filtrado['Subproceso'].isin(subprocesos_seleccionados)]
        
        # Obtener estados disponibles según los filtros anteriores
        estados_disponibles = df_filtrado['Estado'].unique()
        
        estados_filtro = st.multiselect(
            "Estado de la OT",
            options=sorted(estados_disponibles),
            key='estados_filtro'
        )
        
        # Actualizar df_filtrado con los estados seleccionados
        if estados_filtro:
            df_filtrado = df_filtrado[df_filtrado['Estado'].isin(estados_filtro)]
        
        # Obtener cumplimientos disponibles según los filtros anteriores
        cumplimientos_disponibles = df_filtrado['Cumplimiento'].unique()
        
        cumplimiento_filtro = st.multiselect(
            "Cumplimiento de la entrega",
            options=sorted(cumplimientos_disponibles),
            key='cumplimiento_filtro'
        )
        
        # Actualizar df_filtrado con los cumplimientos seleccionados
        if cumplimiento_filtro:
            df_filtrado = df_filtrado[df_filtrado['Cumplimiento'].isin(cumplimiento_filtro)]

    # Crear DataFrame para Gantt
    df_gantt = pd.DataFrame({
        'Task': [f"{row['OT']} - {row['Proceso']}" for _, row in df_filtrado.iterrows()],
        'Start': [row['Fecha Inicio Prevista'] for _, row in df_filtrado.iterrows()],
        'Finish': [row['Fecha Fin Prevista'] for _, row in df_filtrado.iterrows()],
        'Resource': [row['Proceso'] for _, row in df_filtrado.iterrows()]
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

    # Crear figura de Gantt con Plotly
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
        st.metric("Número de OTs", len(df_filtrado['OT'].unique()))
    with col2:
        st.metric("Total de Operaciones", len(df_filtrado))
    
    # Definir los estilos para cada estado
    def color_row(row):
        # Primero verificamos si está fuera de plazo
        if row['Cumplimiento'] == 'Fuera de Plazo':
            return ['background-color: #FFE4E1'] * len(row)  # Rojo suave
        
        # Si no está fuera de plazo, aplicamos los colores según el estado
        if row['Estado'] == 'Planificado Finalizado':
            return ['background-color: #E6F3FF'] * len(row)  # Azul suave
        elif row['Estado'] == 'Activado':
            return ['background-color: #FFF8DC'] * len(row)  # Amarillo suave
        elif row['Estado'] == 'Listo para Activar':
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

    # Guardar el resultado en final_sales_orders_schedule
    try:
        # Preparar el DataFrame para guardar
        df_to_save = df_filtrado.copy()
        
        # Convertir las fechas a formato string para BigQuery
        df_to_save['Fecha Inicio Prevista'] = df_to_save['Fecha Inicio Prevista'].dt.strftime('%Y-%m-%d')
        df_to_save['Fecha Fin Prevista'] = df_to_save['Fecha Fin Prevista'].dt.strftime('%Y-%m-%d')
        df_to_save['Fecha de Entrega'] = df_to_save['Fecha de Entrega'].dt.strftime('%Y-%m-%d')
        
        # Usar la función existente para actualizar la tabla
        update_sales_orders_schedule_table(df_to_save, CREDENTIALS_PATH, TABLE_ID_CURRENT_SCHEDULE)
        st.success("Cronograma actualizado correctamente en BigQuery")
    except Exception as e:
        st.error(f"Error al guardar el cronograma en BigQuery: {str(e)}")
else:
    st.error("No se pudo encontrar una solución óptima para los pedidos actuales") 