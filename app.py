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
    SUBPROCESOS_VALIDOS
)

from processing.transformations import process_data
from bigquery.uploader import load_sales_orders, load_sales_orders_table

# Cargar variables de entorno
load_dotenv()

# Configuración de la página (debe ser el primer comando de Streamlit)
st.set_page_config(
    page_title="Panel de Producción",
    page_icon="📊",
    layout="wide"
)

# Configuración de BigQuery desde variables de entorno
PROJECT_ID = os.getenv('BIGQUERY_PROJECT_ID')
DATASET_ID = os.getenv('BIGQUERY_DATASET_ID')
TABLE_NAME = os.getenv('BIGQUERY_TABLE_NAME')
TABLE_NAME_SALES_ORDERS = os.getenv('BIGQUERY_TABLE_NAME_SALES_ORDERS', 'sales_orders')
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}"
CREDENTIALS_PATH = os.getenv('BIGQUERY_CREDENTIALS_PATH')

# Crear cliente de BigQuery desde el archivo de credenciales
try:
    client = bigquery.Client.from_service_account_json(CREDENTIALS_PATH, location="europe-southwest1")
    
    # Realizar la consulta
    query = f'SELECT * FROM `{TABLE_ID}`'
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

    # Añadir la fecha de entrega del DataFrame original
    df_expanded['fecha_entrega'] = df['fecha_entrega'].values

    # Guardar df_expanded en un archivo CSV para revisión
    df_expanded.to_csv('df_expanded.csv', index=False, encoding='utf-8')

    
    # Columnas del nuevo DataFrame:
    #    Index(['nombre', 'OT_ID_Linea', 'familia', 'cantidad', 'importe',
    #        'IT01_Dibujo', 'IT02_Pantalla', 'IT03_Corte', 'IT05_Grabado',
    #        'IT06_Adhesivo', 'IT06_Laminado', 'IT07_Taladro', 'IT07_Can_romo',
    #        'IT07_Numerado', 'IT08_Embalaje', 'IT04_Impresion._',
    #        'IT04_Impresion.digital', 'IT04_Impresion.serigrafia',
    #        'IT07_Mecanizado._', 'IT07_Mecanizado.plotter',
    #        'IT07_Mecanizado.fresado', 'IT07_Mecanizado.laser',
    #        'IT07_Mecanizado.semicorte', 'IT07_Mecanizado.plegado',
    #        'IT07_Mecanizado.burbuja_teclas', 'IT07_Mecanizado.hendido',
    #        'IT07_Mecanizado.cepillado'],
    #    dtype='object') """

    # Definir fecha de inicio y actual
    fecha_inicio = datetime(2024, 1, 1)  # Fecha base fija
    fecha_actual = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Sidebar para entrada de datos
    with st.sidebar:
        st.image("logo-sergar.png")

        # Opción para cargar pedidos desde Excel
        st.subheader("Cargar Pedidos en Exel")
        uploaded_excel_file = st.file_uploader("Cargar archivo Excel de pedidos", type=['xlsx'])
        if uploaded_excel_file is not None:
            try:
                df = pd.read_excel(uploaded_excel_file, decimal=",", date_format="%d/%m/%Y")
                orders_list = process_data(df)
                load_sales_orders(orders_list, CREDENTIALS_PATH, TABLE_ID) 
                load_sales_orders_table(df, CREDENTIALS_PATH, PROJECT_ID, DATASET_ID, TABLE_NAME_SALES_ORDERS)
                st.success("Archivo Excel cargado correctamente")
            except Exception as e:
                st.error(f"Error al cargar el archivo Excel: {str(e)}")

    # Procesar los datos para la planificación
    pedidos: Dict[str, Dict[str, Any]] = {}
    procesos_unicos: set = set()  # Conjunto para almacenar procesos únicos
    
    for _, row in df_expanded.iterrows():
        pedido_id = str(row['OT_ID_Linea'])
        
        if pedido_id not in pedidos:
            # Calcular días hasta la entrega desde la fecha base
            fecha_entrega = pd.to_datetime(row['fecha_entrega'])
            dias_hasta_entrega = (fecha_entrega - fecha_inicio).days
            
            # Asegurar que la fecha sea positiva
            if dias_hasta_entrega < 0:
                dias_hasta_entrega = 0
            
            pedidos[pedido_id] = {
                "nombre": row['nombre'],
                "cantidad": row['cantidad'],
                "fecha_entrega": dias_hasta_entrega,
                "procesos": []
            }
        
        # Procesar los procesos IT
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

                if pd.notna(value) and value != '':
                    procesos_unicos.add(nombre_completo)  # Añadir el proceso completo
                    duracion = 1  # Por defecto
                    ot = row.get('OT_ID_Linea', 'Sin OT')
                    operario = "Por Asignar"
                    
                    # Verificar si el proceso ya existe
                    if not any(p[0] == nombre_completo and p[2] == subproceso for p in pedidos[pedido_id]["procesos"]):
                        pedidos[pedido_id]["procesos"].append([
                            nombre_completo,  # nombre completo del proceso
                            duracion,        # duracion
                            subproceso,      # subproceso
                            ot,             # ot (ID Linea)
                            operario        # operario
                        ])
        
        # Procesar los nombres de procesos y subprocesos
        pedidos[pedido_id]["procesos"] = completar_datos_procesos({pedido_id: pedidos[pedido_id]})[pedido_id]["procesos"]
        
        # Ordenar los procesos según la secuencia predefinida
        pedidos[pedido_id]["procesos"].sort(key=lambda x: SECUENCIA_PROCESOS.get(x[0], 999))

    # Ordenar pedidos por fecha de entrega y seleccionar los 5 más urgentes
    pedidos_ordenados = sorted(pedidos.items(), key=lambda x: x[1]['fecha_entrega'])
    pedidos_planificacion = dict(pedidos_ordenados[:5])

    # DEBUG: Checkbox en el sidebar
    with st.sidebar:
        st.subheader("🔧 Opciones de Depuración")
        debug_mode = st.checkbox("Modo Depuración", value=False)

    # DEBUG: Información de depuración en la página principal
    if debug_mode:
        st.subheader("🔍 Información de Depuración")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("### Pedidos en planificación")
            st.write(list(pedidos_planificacion.keys()))
            st.write("### Columnas disponibles")
            st.write(df_expanded.columns.tolist())
        
        with col2:
            st.write("### IDs en df_expanded")
            st.write(df_expanded['OT_ID_Linea'].unique().tolist())
        
        st.write("### Datos de los pedidos en planificación")
        df_expanded['OT_ID_Linea'] = df_expanded['OT_ID_Linea'].astype(str)
        df_planificacion = df_expanded[df_expanded['OT_ID_Linea'].isin(pedidos_planificacion.keys())]
        
        if not df_planificacion.empty:
            st.dataframe(
                df_planificacion,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "OT_ID_Linea": st.column_config.TextColumn("OT ID", width="small"),
                    "nombre": st.column_config.TextColumn("Nombre", width="large"),
                    "cantidad": st.column_config.NumberColumn("Cantidad", width="small"),
                    "importe": st.column_config.NumberColumn("Importe", width="small", format="%.2f €"),
                    "fecha_entrega": st.column_config.DateColumn("Fecha Entrega", width="medium", format="DD/MM/YYYY")
                }
            )
        else:
            st.warning("No se encontraron datos para los pedidos seleccionados")
            st.write("IDs en pedidos_planificacion:", list(pedidos_planificacion.keys()))
            st.write("IDs en df_expanded:", df_expanded['OT_ID_Linea'].unique().tolist())

    # Ejecutar planificación
    plan, makespan, status = planificar_produccion(pedidos_planificacion)

    if status == cp_model.OPTIMAL:
        st.success("Se encontró una solución óptima para los 5 pedidos más urgentes")
    elif status == cp_model.FEASIBLE:
        st.warning("Se encontró una solución factible pero no óptima para los 5 pedidos más urgentes")
    elif status == cp_model.INFEASIBLE:
        st.error("No se encontró una solución factible para los 5 pedidos más urgentes")
        st.info("""
        Posibles razones:
        1. Las fechas de entrega son demasiado cercanas
        2. La duración de los procesos es mayor que el tiempo disponible
        3. Hay conflictos en la secuencia de procesos
        """)
    elif status == cp_model.MODEL_INVALID:
        st.error("El modelo es inválido para los 5 pedidos más urgentes")
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
        df = pd.DataFrame(plan, columns=['Inicio', 'Pedido', 'Orden_Proceso', 'Nombre', 'Duración', 'Operación', 'Subproceso', 'OT', 'Operario'])
        
        # Convertir días a fechas
        df['Fecha Inicio'] = df['Inicio'].apply(lambda x: fecha_inicio + timedelta(days=x))
        df['Fecha Fin'] = df.apply(lambda row: row['Fecha Inicio'] + timedelta(days=row['Duración']), axis=1)
        
        # Añadir información de secuencia de procesos
        df['Secuencia'] = df.apply(lambda row: f"Paso {row['Orden_Proceso'] + 1} de {len(pedidos[str(row['Pedido'])]['procesos'])}", axis=1)
        
        # Determinar el estado de cada proceso
        def determinar_estado(row: pd.Series) -> str:
            if row['Fecha Fin'] < fecha_actual:
                return 'Finalizado'
            elif row['Fecha Inicio'] <= fecha_actual <= row['Fecha Fin']:
                return 'En Proceso'
            elif row['Orden_Proceso'] == 0 or all(df[(df['Pedido'] == row['Pedido']) & (df['Orden_Proceso'] < row['Orden_Proceso'])]['Fecha Fin'] <= fecha_actual):
                return 'Listo para Activar'
            else:
                return 'Pendiente'

        def determinar_cumplimiento(row: pd.Series) -> str:
            fecha_limite = fecha_inicio + timedelta(days=pedidos[str(row['Pedido'])]['fecha_entrega'])
            if row['Fecha Fin'] > fecha_limite:
                return 'Fuera de Plazo'
            else:
                return 'En Plazo'

        df['Estado'] = df.apply(determinar_estado, axis=1)
        df['Cumplimiento'] = df.apply(determinar_cumplimiento, axis=1)
        
        # Reordenar y renombrar columnas para mejor visualización
        columnas_ordenadas = ['Estado', 'Cumplimiento', 'Fecha Inicio', 'Fecha Fin', 'Pedido', 'Nombre', 'Operación', 'Subproceso', 'Secuencia', 'Duración', 'OT', 'Operario']
        df = df[columnas_ordenadas]
        
        # Renombrar columnas para mejor comprensión
        df = df.rename(columns={
            'Duración': 'Duración (días)',
            'Operación': 'Proceso',
            'OT': 'Número de OT'
        })

        # Filtros en la sidebar
        with st.sidebar:
            st.subheader("Filtrar")
            
            # Botón para limpiar filtros
            if st.button("🗑️ Limpiar filtros"):
                for key in ['pedidos_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
                    if key in st.session_state:
                        st.session_state[key] = []
                st.rerun()
            
            # Inicializar filtros en session_state si no existen
            for key in ['pedidos_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
                if key not in st.session_state:
                    st.session_state[key] = []
            
            pedidos_filtro = st.multiselect(
                "Número de pedido",
                options=sorted(df['Pedido'].unique()),
                key='pedidos_filtro'
            )
            
            # Obtener procesos disponibles según los pedidos seleccionados
            if pedidos_filtro:
                df_filtrado = df[df['Pedido'].isin(pedidos_filtro)]
                procesos_disponibles = df_filtrado['Proceso'].unique()
            else:
                df_filtrado = df
                procesos_disponibles = df['Proceso'].unique()
            
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
                "Estado del pedido",
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

        # Crear DataFrame para Gantt
        df_gantt = pd.DataFrame({
            'Task': [f"{row['Pedido']} - {row['Proceso']}" for _, row in df_filtrado.iterrows()],
            'Start': [row['Fecha Inicio'] for _, row in df_filtrado.iterrows()],
            'Finish': [row['Fecha Fin'] for _, row in df_filtrado.iterrows()],
            'Resource': [row['Proceso'] for _, row in df_filtrado.iterrows()]
        })

        # Obtener valores únicos de Resource
        recursos_unicos = df_gantt['Resource'].unique()
        
        # Crear diccionario de colores solo para los recursos presentes
        colores_procesos = {
            'IT01_Dibujo': '#1f77b4', # Azul
            'IT02_Impresion': '#fdb462', # Naranja suave
            'IT03_Corte': '#9467bd',  # Púrpura
            'IT04_Mecanizado': '#8c564b', # Marrón
            'IT05_Laminado': '#e377c2', # Rosa
            'IT06_Embalaje': '#b3b3b3', # Gris más claro
            'IT07_Taladro': '#bcbd22', # Verde oliva
            'IT08_Barniz': '#17becf', # Cian
            'IT09_Serigrafia': '#fb8072', # Coral
            'IT10_Digital': '#80b1d3', # Azul claro
            'IT11_Resina': '#ff9896', # Rojo suave
            'IT12_Grabado': '#98df8a', # Verde suave
            'IT13_Acabado': '#c5b0d5', # Púrpura suave
            'IT14_Control': '#ffbb78', # Naranja suave
            'IT15_Almacen': '#aec7e8', # Azul suave
            'IT16_Transporte': '#c49c94', # Marrón suave
            'IT17_Montaje': '#f7b6d2', # Rosa suave
            'IT18_Pruebas': '#dbdb8d', # Amarillo suave
            'IT19_Calidad': '#9edae5', # Cian suave
            'IT20_Entrega': '#e7cb94'  # Beige suave
        }

        colores_actuales = {}
        for i, recurso in enumerate(recursos_unicos):
            # Usar un color del diccionario original si existe, o generar uno nuevo
            if recurso in colores_procesos:
                colores_actuales[recurso] = colores_procesos[recurso]
            else:
                # Generar un color aleatorio si no está en el diccionario original
                import random
                r = random.randint(0, 255)
                g = random.randint(0, 255)
                b = random.randint(0, 255)
                colores_actuales[recurso] = f'rgb({r},{g},{b})'

        # Crear figura de Gantt con Plotly
        st.markdown("### Cronograma de producción")
        fig = ff.create_gantt(df_gantt,
                             index_col='Resource',
                             show_colorbar=True,
                             group_tasks=True,
                             showgrid_x=True,
                             showgrid_y=True,
                             title='',
                             bar_width=0.4,
                             colors=colores_actuales)

        # Configurar el layout del gráfico
        fig.update_layout(
            height=600,
            xaxis_title="Fechas",
            yaxis_title="Operaciones",
            showlegend=True,
            xaxis=dict(
                type='date',
                showgrid=True,
                gridwidth=1,
                gridcolor='LightGrey',
                rangeselector=dict(
                    buttons=list([
                        dict(count=7, label="1 Semana", step="day", stepmode="backward"),
                        dict(count=1, label="1 Mes", step="month", stepmode="backward"),
                        dict(count=6, label="6 Meses", step="month", stepmode="backward"),
                        dict(count=1, label="Año actual", step="year", stepmode="todate"),
                        dict(count=1, label="1 Año", step="year", stepmode="backward"),
                        dict(step="all", label="Todo")
                    ])
                )
            ),
            yaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor='LightGrey',
                tickangle=45,
                tickfont=dict(size=10)
            ),
            margin=dict(l=250, r=50, t=50, b=50),
            font=dict(
                family="Roboto, sans-serif",
                size=12
            )
        )
        
        # Mostrar gráfico
        st.plotly_chart(fig, use_container_width=True)
        
        # Mostrar tabla de detalles filtrada
        st.markdown("### Detalles por pedido")
        st.dataframe(df_filtrado, hide_index=True)
        
        # Métricas principales
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Fecha de Finalización", (fecha_inicio + timedelta(days=makespan)).strftime("%d/%m/%Y"))
        with col2:
            st.metric("Número de Pedidos", len(df_filtrado['Pedido'].unique()))
        with col3:
            st.metric("Total de Operaciones", len(df_filtrado))
        
        # Resumen por proceso
        st.subheader("Resumen por Proceso")
        proceso_tiempos = df_filtrado.groupby('Proceso')['Duración (días)'].sum()
        st.bar_chart(proceso_tiempos)
        
        # Instrucciones para operarios
        st.subheader("📋 Instrucciones para Operarios")
        for _, row in df_filtrado.iterrows():
            estado_emoji = {
                'Fuera de Plazo': '⚠️',
                'En Plazo': '✅',
                'Finalizado': '✅',
                'En Proceso': '🔄',
                'Listo para Activar': '🟢',
                'Pendiente': '⏳'
            }
            
            # Obtener la fecha límite del pedido
            fecha_limite = fecha_inicio + timedelta(days=pedidos[str(row['Pedido'])]['fecha_entrega'])
            
            st.markdown(f"""
            **Pedido {row['Pedido']} - {row['Proceso']}** {estado_emoji[row['Cumplimiento']]}
            - Subproceso: {row['Subproceso']}
            - Número de OT: {row['Número de OT']}
            - Operario: {row['Operario']}
            - Fecha de Inicio: {row['Fecha Inicio'].strftime('%d/%m/%Y')}
            - Fecha de Finalización: {row['Fecha Fin'].strftime('%d/%m/%Y')}
            - Fecha Límite: {fecha_limite.strftime('%d/%m/%Y')}
            - Duración: {row['Duración (días)']} días
            - Estado: {row['Estado']}
            - Cumplimiento: {row['Cumplimiento']}
            """)

        # Calcular fechas límite internas para todos los pedidos
        fechas_limite_internas = {
            pedido: calcular_fechas_limite_internas(pedido, data, fecha_inicio) 
            for pedido, data in pedidos.items()
        }

        # Añadir prioridad y fechas límite internas al DataFrame
        df['Prioridad'] = df['Pedido'].apply(lambda x: calcular_prioridad(x, pedidos[str(x)]))
        df['Fecha Límite Interna'] = df.apply(
            lambda row: fechas_limite_internas[str(row['Pedido'])][int(row['Secuencia'].split()[1]) - 1], 
            axis=1
        )

        # Reordenar columnas para mejor visualización
        columnas_ordenadas = [
            'Estado', 'Cumplimiento', 'Prioridad', 'Fecha Inicio', 'Fecha Fin', 
            'Fecha Límite Interna', 'Pedido', 'Nombre', 'Proceso', 'Subproceso', 
            'Secuencia', 'Duración (días)', 'Número de OT', 'Operario'
        ]
        df = df[columnas_ordenadas]

        # Añadir métricas de prioridad
        st.subheader("Métricas de Prioridad")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Pedidos Críticos", len(df[df['Prioridad'] > df['Prioridad'].median()]))
        with col2:
            st.metric("Procesos Fuera de Plazo", len(df[df['Cumplimiento'] == 'Fuera de Plazo']))
        with col3:
            st.metric("Procesos en Riesgo", len(df[df['Fecha Fin'] > df['Fecha Límite Interna']]))

        # Añadir gráfico de prioridades
        st.subheader("Distribución de Prioridades")
        st.bar_chart(df.groupby('Pedido')['Prioridad'].mean().sort_values(ascending=False))
    else:
        st.error("No se pudo encontrar una solución óptima para los pedidos actuales")

except Exception as e:
    st.error(f"Error al conectar con BigQuery: {str(e)}")
    st.info("""
    Por favor, verifica que:
    1. El archivo de credenciales existe en la ruta especificada
    2. El proyecto 'sergar' existe y está activo en Google Cloud
    3. La cuenta de servicio tiene los permisos necesarios en BigQuery
    4. El dataset y la tabla especificados existen y son accesibles
    """)
    st.stop() 