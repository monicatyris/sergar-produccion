import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion
import plotly.graph_objects as go

# Configuración de la página para layout responsive
st.set_page_config(
    page_title="Panel de Producción",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS para mejorar la visualización
st.markdown("""
    <style>
        /* Eliminar barras de desplazamiento */
        .main .block-container {
            padding-top: 0.5rem;
            padding-bottom: 0.5rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
        
        /* Ajustar sidebar */
        .css-1d391kg {
            padding-top: 0.5rem;
            padding-bottom: 0.5rem;
        }
        
        /* Ajustar altura de elementos */
        .stDataFrame {
            width: 100%;
            height: calc(100vh - 500px);
            overflow: auto;
        }
        
        /* Ajustar altura del gráfico Gantt */
        .element-container:has(> .stPlotlyChart) {
            height: calc(100vh - 300px);
        }
        
        /* Ajustar espaciado entre elementos */
        .element-container {
            margin-bottom: 0.25rem;
        }
        
        /* Ajustar tamaño de fuente */
        .stMarkdown h3 {
            margin-top: 0.5rem;
            margin-bottom: 0.5rem;
        }
        
        /* Ajustar botones y controles */
        .stButton > button {
            width: 100%;
        }
        
        /* Ajustar multiselect */
        .stMultiSelect {
            max-height: 100px;
        }
        
        /* Ocultar barras de desplazamiento pero mantener funcionalidad */
        ::-webkit-scrollbar {
            display: none;
        }
        
        /* Ajustar tabla de datos */
        .dataframe {
            font-size: 0.9em;
        }
        
        /* Ajustar contenedor principal */
        .main .block-container {
            max-width: 100%;
            padding-left: 1rem;
            padding-right: 1rem;
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
        if st.button("🗑️ Limpiar filtros", help="Elimina todos los filtros aplicados"):
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
    
    # Mostrar tabla de detalles filtrada
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
else:
    st.error("No se pudo encontrar una solución óptima para los pedidos actuales") 