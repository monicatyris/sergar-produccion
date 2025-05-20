import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion
import plotly.graph_objects as go

from processing.transformations import process_data
from bigquery.uploader import load_sales_orders
from config import credentials_path, TABLE_ID

# Configuración de la página (debe ser el primer comando de Streamlit)
st.set_page_config(
    page_title="Panel de Producción",
    page_icon="📊",
    layout="wide"
)

# Añadir estilos CSS después de la configuración de la página
st.markdown("""
    <style>
        .stButton>button {
            background-color: transparent;
            border: none;
            color: #666;
            padding: 0;
            font-size: 1.2em;
        }
        .stButton>button:hover {
            color: #333;
        }
    </style>
""", unsafe_allow_html=True)

# Título y descripción
st.title("📊 Panel de Producción")
st.markdown("""
Este panel muestra el cronograma de producción indicando el estado de los pedidos, procesos, etapas y fechas de entrega.
""")

# Definir fecha de inicio y actual
fecha_inicio = datetime(2024, 9, 26)
fecha_actual = datetime(2024, 9, 26)

# Sidebar para entrada de datos
with st.sidebar:
    st.image("logo-sergar.png")
    
    # Opción para cargar pedidos desde JSON
    st.subheader("Cargar Pedidos")
    uploaded_file = st.file_uploader("Cargar archivo JSON de pedidos", type=['json'])

     # Opción para cargar pedidos desde Excel
    st.subheader("Cargar Pedidos en Exel")
    uploaded_excel_file = st.file_uploader("Cargar archivo Excel de pedidos", type=['xlsx'])
    if uploaded_excel_file is not None:
        try:
            df = pd.read_excel(uploaded_excel_file, decimal=",", date_format="%d/%m/%Y")
            orders_list = process_data(df)
            load_sales_orders(orders_list, credentials_path, TABLE_ID)
            st.success("Archivo Excel cargado correctamente")
        except Exception as e:
            st.error(f"Error al cargar el archivo Excel: {str(e)}")
    
    # Definir lista de subprocesos válidos
    SUBPROCESOS_VALIDOS = {
        'Dibujo': ['Dibujo Técnico', 'Dibujo Artístico', 'Dibujo Vectorial'],
        'Impresión': ['Impresión Digital', 'Impresión Offset', 'Impresión Serigráfica'],
        'Corte': ['Corte Láser', 'Corte CNC', 'Corte Manual'],
        'Mecanizado': ['Fresado', 'Torneado', 'Taladrado'],
        'Laminado': ['Laminado Manual', 'Laminado Automático'],
        'Embalaje': ['Embalaje Manual', 'Embalaje Automático'],
        'Taladro': ['Taladro Manual', 'Taladro CNC'],
        'Barniz': ['Barniz Manual', 'Barniz Automático'],
        'Serigrafía': ['Serigrafía Manual', 'Serigrafía Automática'],
        'Digital': ['Digitalización', 'Edición Digital']
    }

    # Función para completar los datos de los procesos
    def completar_datos_procesos(pedidos):
        for pedido, data in pedidos.items():
            procesos_completos = []
            for proceso_info in data['procesos']:
                proceso = proceso_info[0]
                duracion = proceso_info[1]
                # Seleccionar un subproceso aleatorio de los disponibles para el proceso
                subproceso = SUBPROCESOS_VALIDOS.get(proceso, ['Sin Especificar'])[0]
                ot = f"OT-{pedido}-{len(procesos_completos)+1}"
                operario = "Por Asignar"
                procesos_completos.append([proceso, duracion, subproceso, ot, operario])
            data['procesos'] = procesos_completos
        return pedidos

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

# Ejecutar planificación
plan, makespan, status = planificar_produccion(pedidos)

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

    # Modificar las fechas del ejemplo específico antes de la planificación
    if '42174' in pedidos:
        # Establecer la fecha límite para el pedido 42174 (25/09/2024)
        pedidos['42174']['fecha_entrega'] = -1  # -1 días desde la fecha de inicio (26/09/2024)

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
        
        # Botón para limpiar filtros con ícono
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🗑️"):
                for key in ['pedidos_filtro', 'procesos_filtro', 'subprocesos_filtro', 'estados_filtro', 'cumplimiento_filtro']:
                    if key in st.session_state:
                        st.session_state[key] = []
                st.rerun()
        with col2:
            st.markdown("Limpiar filtros", help="Elimina todos los filtros aplicados")
        
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
                subprocesos_disponibles.extend(SUBPROCESOS_VALIDOS.get(proceso, ['Sin Especificar']))
        else:
            subprocesos_disponibles = df_filtrado['Subproceso'].unique()
        
        subprocesos_filtro = st.multiselect(
            "Subproceso",
            options=sorted(subprocesos_disponibles),
            key='subprocesos_filtro'
        )
        
        # Actualizar df_filtrado con los subprocesos seleccionados
        if subprocesos_filtro:
            df_filtrado = df_filtrado[df_filtrado['Subproceso'].isin(subprocesos_filtro)]
        
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

    # Crear DataFrame para Gantt con datos filtrados
    if len(df_filtrado) == 0:
        st.error("""
        **No se encontraron resultados para los filtros aplicados**
        
        Modifica uno o más filtros para ampliar los resultados de tu búsqueda.
        """)
        st.stop()

    df_gantt = pd.DataFrame({
        'Task': [f"{row['Pedido']} - {row['Proceso']}" for _, row in df_filtrado.iterrows()],
        'Start': [row['Fecha Inicio'] for _, row in df_filtrado.iterrows()],
        'Finish': [row['Fecha Fin'] for _, row in df_filtrado.iterrows()],
        'Resource': [row['Proceso'] for _, row in df_filtrado.iterrows()]
    })
    
    # Definir colores fijos para cada tipo de proceso
    colores_procesos = {
        'Dibujo': '#1f77b4',      # Azul
        'Impresión': '#fdb462',   # Naranja suave
        'Corte': '#9467bd',       # Púrpura
        'Mecanizado': '#8c564b',  # Marrón
        'Laminado': '#e377c2',    # Rosa
        'Embalaje': '#b3b3b3',    # Gris más claro
        'Taladro': '#bcbd22',     # Verde oliva
        'Barniz': '#17becf',      # Cian
        'Serigrafía': '#fb8072',  # Coral
        'Digital': '#80b1d3'      # Azul claro
    }
    
    # Crear figura de Gantt con Plotly
    st.markdown("### Cronograma de producción")
    fig = ff.create_gantt(df_gantt,
                         index_col='Resource',
                         show_colorbar=True,
                         group_tasks=True,
                         showgrid_x=True,
                         showgrid_y=True,
                         title='',
                         bar_width=0.4)
    
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
            gridcolor='LightGrey'
        ),
        bargap=0.2,
        bargroupgap=0.1,
        font=dict(
            family="Roboto, sans-serif",
            size=12
        )
    )
    
    # Asignar colores consistentes a cada proceso
    for trace in fig.data:
        proceso = trace.name.split(' - ')[-1]  # Obtener el nombre del proceso
        if proceso in colores_procesos:
            trace.marker.color = colores_procesos[proceso]
            trace.marker.line.color = colores_procesos[proceso]
            trace.marker.line.width = 1
    
    # Forzar la actualización de los colores
    fig.update_traces(marker=dict(line=dict(width=1)))
    
    # Mostrar gráfico
    st.plotly_chart(fig, use_container_width=True)
    
    # Mostrar tabla de detalles filtrada con estilos
    st.markdown("### Detalles por pedido")
    
    # Reordenar y seleccionar columnas
    columnas_ordenadas = [
        'Pedido', 'Número de OT', 'Secuencia', 'Proceso', 'Subproceso',
        'Fecha Inicio', 'Fecha Fin', 'Duración (días)', 'Estado',
        'Cumplimiento', 'Operario'
    ]
    df_filtrado = df_filtrado[columnas_ordenadas]
    
    # Mostrar tabla sin estilos y sin índices
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

    # Función para calcular la prioridad de un pedido
    def calcular_prioridad(pedido, data):
        try:
            # Factor de urgencia (basado en días restantes hasta la fecha de entrega)
            dias_restantes = max(1, data['fecha_entrega'])  # Asegurar que no sea cero
            factor_urgencia = 1 / dias_restantes
            
            # Factor de coste (basado en cantidad y costes de procesos)
            coste_total = 0
            for proceso_info in data['procesos']:
                proceso = proceso_info[0]  # El nombre del proceso es el primer elemento
                duracion = proceso_info[1]  # La duración es el segundo elemento
                if proceso in costes_procesos:
                    coste_total += costes_procesos[proceso] * duracion
            
            factor_coste = data['cantidad'] * coste_total
            
            # Factor de complejidad (basado en número de procesos)
            factor_complejidad = len(data['procesos'])
            
            # Factor de procesos críticos (Resina, Grabado, Barniz)
            procesos_criticos = sum(1 for proceso_info in data['procesos'] 
                                 if proceso_info[0] in ['Resina', 'Grabado', 'Barniz'])
            factor_criticos = 1 + (procesos_criticos * 0.2)  # 20% más por cada proceso crítico
            
            # Cálculo de la prioridad final
            prioridad = factor_urgencia * factor_coste * factor_complejidad * factor_criticos
            return prioridad
        except Exception as e:
            print(f"Error al calcular prioridad para pedido {pedido}: {str(e)}")
            return 0  # Retornar 0 en caso de error

    # Calcular prioridades para todos los pedidos
    prioridades = {pedido: calcular_prioridad(pedido, data) for pedido, data in pedidos.items()}

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

    # Añadir prioridad y fechas límite internas al DataFrame
    df['Prioridad'] = df['Pedido'].apply(lambda x: prioridades[str(x)])
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