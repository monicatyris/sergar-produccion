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
TABLE_ID = os.getenv('BIGQUERY_TABLE_ID')
table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

# Crear diccionario de credenciales desde variables de entorno
credentials_json = {
    "type": os.getenv('BIGQUERY_TYPE'),
    "project_id": os.getenv('BIGQUERY_PROJECT_ID'),
    "private_key_id": os.getenv('BIGQUERY_PRIVATE_KEY_ID'),
    "private_key": os.getenv('BIGQUERY_PRIVATE_KEY'),
    "client_email": os.getenv('BIGQUERY_CLIENT_EMAIL'),
    "client_id": os.getenv('BIGQUERY_CLIENT_ID'),
    "auth_uri": os.getenv('BIGQUERY_AUTH_URI'),
    "token_uri": os.getenv('BIGQUERY_TOKEN_URI'),
    "auth_provider_x509_cert_url": os.getenv('BIGQUERY_AUTH_PROVIDER_X509_CERT_URL'),
    "client_x509_cert_url": os.getenv('BIGQUERY_CLIENT_X509_CERT_URL'),
    "universe_domain": os.getenv('BIGQUERY_UNIVERSE_DOMAIN')
}

# Guardar las credenciales en un archivo temporal
credentials_path = "sergar-credentials.json"
try:
    with open(credentials_path, "w") as f:
        json.dump(credentials_json, f)

    # Crear cliente de BigQuery
    client = bigquery.Client.from_service_account_json(credentials_path)

    # Realizar la consulta
    query = f'SELECT * FROM `{table_id}`'
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

    # Definir fecha de inicio y actual
    fecha_inicio = datetime(2024, 1, 1)  # Fecha base fija
    fecha_actual = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Función para procesar nombres de procesos y subprocesos
    def procesar_nombre_proceso(nombre_completo):
        """
        Procesa el nombre completo de un proceso para extraer el proceso principal y subproceso.
        Ejemplo: 'IT07_Mecanizado_laser' -> ('Mecanizado', 'Láser')
        """
        # Mapeo de nombres de procesos
        MAPEO_PROCESOS = {
            'IT01_Dibujo': 'Dibujo',
            'IT02_Pantalla': 'Pantalla',
            'IT03_Corte': 'Corte',
            'IT04_Impresion': 'Impresión',
            'IT05_Grabado': 'Grabado',
            'IT06_Adhesivo': 'Adhesivo',
            'IT06_Laminado': 'Laminado',
            'IT07_Mecanizado': 'Mecanizado',
            'IT07_Taladro': 'Taladro',
            'IT07_Can_romo': 'Canteado',
            'IT07_Numerado': 'Numerado',
            'IT08_Embalaje': 'Embalaje',
            # Añadir mapeo inverso para nombres sin IT
            'Dibujo': 'Dibujo',
            'Pantalla': 'Pantalla',
            'Corte': 'Corte',
            'Impresión': 'Impresión',
            'Grabado': 'Grabado',
            'Adhesivo': 'Adhesivo',
            'Laminado': 'Laminado',
            'Mecanizado': 'Mecanizado',
            'Taladro': 'Taladro',
            'Canteado': 'Canteado',
            'Numerado': 'Numerado',
            'Embalaje': 'Embalaje'
        }

        # Mapeo de subprocesos
        MAPEO_SUBPROCESOS = {
            'laser': 'Láser',
            'digital': 'Digital',
            'serigrafia': 'Serigrafía',
            'fresado': 'Fresado',
            'plotter': 'Plotter',
            'burbuja_teclas': 'Burbuja teclas',
            'hendido': 'Hendido',
            'plegado': 'Plegado',
            'semicorte': 'Semicorte'
        }

        # Limpiar el nombre completo
        nombre_completo = nombre_completo.strip()

        # Si el nombre está vacío, retornar valores por defecto
        if not nombre_completo:
            return "Sin Proceso", "Sin especificar"

        # Si el nombre completo está en el mapeo de procesos, usarlo directamente
        if nombre_completo in MAPEO_PROCESOS:
            return MAPEO_PROCESOS[nombre_completo], "Sin especificar"

        # Separar el proceso y el subproceso
        # Primero, buscar el proceso base en el nombre
        proceso_base = None
        for key in MAPEO_PROCESOS.keys():
            if nombre_completo.startswith(key):
                proceso_base = key
                break

        if proceso_base is None:
            # Si no se encuentra un proceso base con IT, intentar con el nombre directo
            nombre_sin_it = nombre_completo.split('_')[-1] if '_' in nombre_completo else nombre_completo
            if nombre_sin_it in MAPEO_PROCESOS:
                return MAPEO_PROCESOS[nombre_sin_it], "Sin especificar"
            return nombre_completo, "Sin especificar"
        
        # Obtener el proceso mapeado
        proceso = MAPEO_PROCESOS[proceso_base]

        # Extraer el subproceso
        subproceso = nombre_completo[len(proceso_base):].strip()
        if subproceso.startswith('_'):
            subproceso = subproceso[1:].strip()

        # Si no hay subproceso o es '_', retornar sin subproceso
        if not subproceso or subproceso == '_':
            return proceso, "Sin especificar"

        # Limpiar el subproceso
        subproceso = subproceso.lower().strip()
        # Eliminar el nombre del proceso del subproceso si está presente
        subproceso = subproceso.replace(proceso_base.lower(), '').strip()
        # Eliminar espacios y guiones bajos adicionales
        subproceso = subproceso.replace('_', ' ').strip()

        # Buscar el subproceso en el mapeo
        subproceso_mapeado = MAPEO_SUBPROCESOS.get(subproceso, subproceso)
        # Si el subproceso no está en el mapeo, intentar con el formato con guiones bajos
        if subproceso_mapeado == subproceso:
            subproceso_alt = subproceso.replace(' ', '_')
            subproceso_mapeado = MAPEO_SUBPROCESOS.get(subproceso_alt, subproceso)

        return (proceso, subproceso_mapeado)

    # Función para completar los datos de los procesos
    def completar_datos_procesos(pedidos):
        for pedido, data in pedidos.items():
            procesos_completos = []
            procesos_agrupados = {}  # Para agrupar subprocesos por proceso principal

            for proceso_info in data['procesos']:
                nombre_completo = proceso_info[0]
                duracion = proceso_info[1]
                proceso, subproceso = procesar_nombre_proceso(nombre_completo)
                ot = proceso_info[3]  # Mantener el OT original (ID Linea)
                operario = "Por Asignar"

                # Agrupar subprocesos por proceso principal
                if proceso not in procesos_agrupados:
                    procesos_agrupados[proceso] = []
                
                procesos_agrupados[proceso].append({
                    'subproceso': subproceso,
                    'duracion': duracion,
                    'ot': ot,
                    'operario': operario
                })

            # Convertir los procesos agrupados a la estructura final
            for proceso, subprocesos in procesos_agrupados.items():
                for subproceso_info in subprocesos:
                    procesos_completos.append([
                        proceso,  # proceso principal
                        subproceso_info['duracion'],
                        subproceso_info['subproceso'],
                        subproceso_info['ot'],  # Mantener el OT original
                        subproceso_info['operario']
                    ])

            data['procesos'] = procesos_completos
        return pedidos

    # Definir secuencia de procesos (sin prefijo IT)
    SECUENCIA_PROCESOS = {
        'Dibujo': 1,
        'Pantalla': 2,
        'Corte': 3,
        'Impresión': 4,
        'Grabado': 5,
        'Adhesivo': 6,
        'Laminado': 7,
        'Mecanizado': 8,
        'Taladro': 9,
        'Canteado': 10,
        'Numerado': 11,
        'Embalaje': 12
    }

    # Definir lista de subprocesos válidos (sin prefijo IT)
    SUBPROCESOS_VALIDOS = {
        'Mecanizado': ['Sin especificar', 'Burbuja teclas', 'Fresado', 'Hendido', 'Láser', 'Plegado', 'Plotter', 'Semicorte'],
        'Impresión': ['Sin especificar', 'Digital', 'Serigrafía']
    }

    # Sidebar para entrada de datos
    with st.sidebar:
        st.image("logo-sergar.png")
        
        # Opción para cargar pedidos desde JSON
        st.subheader("Cargar Pedidos")
        uploaded_file = st.file_uploader("Cargar archivo JSON de pedidos", type=['json'])
        
        # Modificar la carga de pedidos
        if uploaded_file is not None:
            try:
                pedidos = json.load(uploaded_file)
                pedidos = completar_datos_procesos(pedidos)
                st.success("Archivo cargado correctamente")
            except:
                st.error("Error al cargar el archivo")
                with open('pedidos_actualizados.json', 'r', encoding='utf-8') as f:
                    pedidos = json.load(f)
                    pedidos = completar_datos_procesos(pedidos)
        else:
            with open('pedidos_actualizados.json', 'r', encoding='utf-8') as f:
                pedidos = json.load(f)
                pedidos = completar_datos_procesos(pedidos)

    # Procesar los datos para la planificación
    pedidos = {}
    procesos_unicos = set()  # Conjunto para almacenar procesos únicos
    
    for _, row in df.iterrows():
        articulo = row['articulos']
        pedido_id = str(row['numero_pedido'])
        
        if pedido_id not in pedidos:
            # Calcular días hasta la entrega desde la fecha base
            fecha_entrega = pd.to_datetime(row['fecha_entrega'])
            dias_hasta_entrega = (fecha_entrega - fecha_inicio).days
            
            # Asegurar que la fecha sea positiva
            if dias_hasta_entrega < 0:
                dias_hasta_entrega = 0
            
            pedidos[pedido_id] = {
                "nombre": articulo['nombre'],
                "cantidad": articulo['cantidad'],
                "fecha_entrega": dias_hasta_entrega,
                "procesos": []
            }
        
        # Procesar los procesos IT
        for key, value in articulo.items():
            if key.startswith('IT'):
                procesos_unicos.add(key)  # Añadir el proceso al conjunto
                if isinstance(value, dict):
                    # Procesar subprocesos
                    for subproceso, estado in value.items():
                        if pd.notna(estado) and estado != '':
                            nombre_completo = f"{key} {subproceso}"
                            procesos_unicos.add(nombre_completo)  # Añadir el proceso completo
                            duracion = 1  # Por defecto
                            ot = articulo.get('ID Linea', 'Sin OT')
                            operario = "Por Asignar"
                            
                            # Verificar si el proceso ya existe
                            proceso, subproceso = procesar_nombre_proceso(nombre_completo)
                            
                            if not any(p[0] == proceso and p[2] == subproceso for p in pedidos[pedido_id]["procesos"]):
                                pedidos[pedido_id]["procesos"].append([
                                    nombre_completo,  # nombre completo del proceso
                                    duracion,        # duracion
                                    "Sin Subproceso", # subproceso (se procesará después)
                                    ot,             # ot (ID Linea)
                                    operario        # operario
                                ])
                elif pd.notna(value) and value != '':
                    # Procesar procesos simples
                    nombre_completo = key
                    procesos_unicos.add(nombre_completo)  # Añadir el proceso simple
                    duracion = 1  # Por defecto
                    ot = articulo.get('ID Linea', 'Sin OT')
                    operario = "Por Asignar"
                    
                    # Verificar si el proceso ya existe
                    proceso, subproceso = procesar_nombre_proceso(nombre_completo)
                    
                    if not any(p[0] == proceso and p[2] == subproceso for p in pedidos[pedido_id]["procesos"]):
                        pedidos[pedido_id]["procesos"].append([
                            nombre_completo,  # nombre completo del proceso
                            duracion,        # duracion
                            "Sin Subproceso", # subproceso (se procesará después)
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
        def determinar_estado(row):
            if row['Fecha Fin'] < fecha_actual:
                return 'Finalizado'
            elif row['Fecha Inicio'] <= fecha_actual <= row['Fecha Fin']:
                return 'En Proceso'
            elif row['Orden_Proceso'] == 0 or all(df[(df['Pedido'] == row['Pedido']) & (df['Orden_Proceso'] < row['Orden_Proceso'])]['Fecha Fin'] <= fecha_actual):
                return 'Listo para Activar'
            else:
                return 'Pendiente'

        def determinar_cumplimiento(row):
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

        # Definir costes relativos de los procesos
        costes_procesos = {
            'Dibujo': 1.0,      # Coste base
            'Impresión': 1.2,   # 20% más costoso que dibujo
            'Serigrafía': 1.5,  # 50% más costoso que dibujo
            'Taladro': 1.3,     # 30% más costoso que dibujo
            'Corte': 1.4,       # 40% más costoso que dibujo
            'Resina': 2.0,      # 100% más costoso que dibujo (proceso externo)
            'Grabado': 1.1,     # 10% más costoso que dibujo
            'Barniz': 1.1,      # 10% más costoso que dibujo
            'Embalaje': 0.8     # 20% menos costoso que dibujo
        }

        # Función para calcular fechas límite internas
        def calcular_fechas_limite_internas(pedido, data):
            try:
                fecha_entrega = fecha_inicio + timedelta(days=data['fecha_entrega'])
                procesos = data['procesos']
                total_dias = sum(proceso_info[1] for proceso_info in procesos)  # La duración es el segundo elemento
                
                fechas_limite = {}
                dias_acumulados = 0
                
                for i, proceso_info in enumerate(procesos):
                    proceso = proceso_info[0]  # El nombre del proceso es el primer elemento
                    duracion = proceso_info[1]  # La duración es el segundo elemento
                    
                    # Distribuir el tiempo restante proporcionalmente
                    dias_asignados = (duracion / total_dias) * data['fecha_entrega']
                    fecha_limite = fecha_inicio + timedelta(days=int(dias_acumulados + dias_asignados))
                    fechas_limite[i] = fecha_limite
                    dias_acumulados += dias_asignados
                
                return fechas_limite
            except Exception as e:
                print(f"Error al calcular fechas límite internas para pedido {pedido}: {str(e)}")
                return {}  # Retornar diccionario vacío en caso de error

        # Calcular fechas límite internas para todos los pedidos
        fechas_limite_internas = {
            pedido: calcular_fechas_limite_internas(pedido, data) 
            for pedido, data in pedidos.items()
        }

        # Función para calcular la prioridad de un pedido
        def calcular_prioridad(pedido_id, pedido_data):
            """
            Calcula la prioridad de un pedido basado en varios factores:
            - Tiempo hasta la entrega
            - Cantidad de procesos
            - Estado de los procesos
            """
            try:
                # Factor de tiempo (más urgente = mayor prioridad)
                tiempo_hasta_entrega = pedido_data['fecha_entrega']
                factor_tiempo = 1 / (tiempo_hasta_entrega + 1)  # +1 para evitar división por cero
                
                # Factor de cantidad (más procesos = mayor prioridad)
                cantidad_procesos = len(pedido_data['procesos'])
                factor_cantidad = cantidad_procesos / 10  # Normalizado a 10 procesos
                
                # Factor de estado (procesos pendientes = mayor prioridad)
                procesos_pendientes = sum(1 for p in pedido_data['procesos'] if p[4] == "Por Asignar")
                factor_estado = procesos_pendientes / cantidad_procesos if cantidad_procesos > 0 else 0
                
                # Calcular prioridad final (0-100)
                prioridad = (factor_tiempo * 0.5 + factor_cantidad * 0.3 + factor_estado * 0.2) * 100
                
                return round(prioridad, 2)
            except Exception as e:
                print(f"Error al calcular prioridad para pedido {pedido_id}: {str(e)}")
                return 0

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
finally:
    # Asegurarnos de eliminar el archivo de credenciales incluso si hay un error
    if os.path.exists(credentials_path):
        os.remove(credentials_path) 